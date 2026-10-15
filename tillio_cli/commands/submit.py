"""tillio submit — parse local commits and send to Tillio API."""

import click
from rich.table import Table
from tillio_cli.git import run_git, get_repo_url, get_branch, parse_commits, get_diff_content, build_submission
from tillio_cli.api import TillioClient, AuthError, DuplicateError, APIError
from tillio_cli.output import get_console, is_json, print_json
from tillio_cli.exit_codes import EXIT_AUTH, EXIT_GENERAL, EXIT_NOT_GIT_REPO, EXIT_VALIDATION, EXIT_SIGINT

# Max commits for streaming (inline evaluation). Beyond this, use non-streaming.
STREAM_MAX_COMMITS = 10


@click.command()
@click.argument("commit_range", default="HEAD")
@click.option("--project-id", default=None, help="Tillio project ID (auto-detected from repo URL if not set)")
@click.option("--dry-run", is_flag=True, help="Preview what would be submitted without sending")
@click.option("--full-context", is_flag=True, default=False, help="Include code diffs for richer AI evaluation")
@click.option("--no-context", is_flag=True, default=False, help="Force summary mode (metadata only)")
@click.pass_context
def submit(ctx, commit_range: str, project_id: str, dry_run: bool, full_context: bool, no_context: bool):
    """
    Submit commits as contributions.

    \b
    Examples:
        tillio submit              # last commit (HEAD)
        tillio submit HEAD~3..HEAD # last 3 commits
        tillio submit abc123       # specific commit
    """
    json_mode = is_json(ctx)
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False

    try:
        run_git(["rev-parse", "--is-inside-work-tree"])
    except (RuntimeError, FileNotFoundError):
        if json_mode:
            print_json({"error": "Not a git repository"})
        else:
            click.echo("✗ Not a git repository.", err=True)
        raise SystemExit(EXIT_NOT_GIT_REPO)

    repo_url = get_repo_url()
    branch = get_branch()

    # Parse commits from local git
    try:
        commits = parse_commits(commit_range)
    except RuntimeError as e:
        if json_mode:
            print_json({"error": f"Failed to read git history: {e}"})
        else:
            click.echo(f"✗ Failed to read git history: {e}", err=True)
        raise SystemExit(EXIT_GENERAL)

    if not commits:
        if json_mode:
            print_json({"submitted": 0, "message": "No commits found"})
        else:
            click.echo("No commits found in the specified range.")
        return

    # Dry-run: show what would be submitted and exit
    if dry_run:
        preview = {
            "dry_run": True,
            "repository_url": repo_url,
            "branch": branch,
            "commit_count": len(commits),
            "commits": commits,
        }
        if json_mode:
            print_json(preview)
        else:
            console = get_console(ctx)
            console.print(f"Dry run — {len(commits)} commit(s) from '{branch}':", style="bold")
            click.echo()

            table = Table(show_edge=False, pad_edge=False, box=None)
            table.add_column("SHA", style="cyan", min_width=8)
            table.add_column("Changes", justify="right")
            table.add_column("Files", justify="right")
            table.add_column("Message")

            for c in commits:
                files = len(c.get("files_changed", []))
                changes = f"+{c['additions']}/-{c['deletions']}"
                table.add_row(
                    c["sha"][:8],
                    changes,
                    str(files),
                    c["message"][:60],
                )

            console.print(table)
            click.echo()
            console.print("No data sent. Remove --dry-run to submit.", style="dim")
        return

    if not json_mode:
        click.echo(f"Submitting {len(commits)} commit(s) from '{branch}'...")
        click.echo()

    try:
        client = TillioClient()
    except AuthError as e:
        if json_mode:
            print_json({"error": str(e)})
        else:
            click.echo(f"✗ {e}", err=True)
        raise SystemExit(EXIT_AUTH)

    # Resolve project
    if not project_id:
        if not repo_url:
            if json_mode:
                print_json({"error": "No remote URL and no --project-id specified"})
            else:
                click.echo("✗ No remote URL and no --project-id specified.", err=True)
                click.echo("  Set a remote: git remote add origin <url>", err=True)
                click.echo("  Or specify: tillio submit --project-id <id>", err=True)
            raise SystemExit(EXIT_VALIDATION)

        project = client.lookup_project(repo_url)
        if project:
            project_id = project["id"]
            if not json_mode:
                click.echo(f"Project: {project['name']}")
        else:
            # Auto-create project
            if not json_mode:
                click.echo(f"Creating project from {repo_url}...")
            try:
                project = client.post("/v1/projects/from-repo", {"repository_url": repo_url})
                project_id = project["id"]
                if not json_mode:
                    click.echo(f"✓ Created project: {project['name']}")
            except APIError as e:
                if json_mode:
                    print_json({"error": f"Failed to create project: {e}"})
                else:
                    click.echo(f"✗ Failed to create project: {e}", err=True)
                raise SystemExit(EXIT_VALIDATION)

    # Determine whether to include diffs
    include_diffs = full_context
    if not full_context and not no_context:
        # Check project's evaluation_mode setting
        if isinstance(project, dict):
            # /v1/projects/by-repo is intentionally lightweight and may not include evaluation_mode.
            if "evaluation_mode" not in project and project_id:
                try:
                    proj_data = client.get(f"/v1/projects/{project_id}")
                    if isinstance(proj_data, dict):
                        project = proj_data
                except APIError:
                    pass

            eval_mode = project.get("evaluation_mode", "summary")
        else:
            # project_id was passed directly, fetch project to check mode
            try:
                proj_data = client.get(f"/v1/projects/{project_id}")
                eval_mode = proj_data.get("evaluation_mode", "summary") if isinstance(proj_data, dict) else "summary"
            except APIError:
                eval_mode = "summary"
        include_diffs = eval_mode == "full"

    if include_diffs:
        if not json_mode:
            click.echo("  (including code diffs and context for evaluation)")
        from tillio_cli.context import build_context_bundle
        for c in commits:
            c["diff"] = get_diff_content(c["sha"])
            c["context_bundle"] = build_context_bundle(c["sha"], c.get("files_changed", []))

    # Build and submit
    payload = {
        "repository_url": repo_url,
        "branch": branch,
        "commits": commits,
    }

    use_streaming = len(commits) <= STREAM_MAX_COMMITS

    if use_streaming:
        _submit_streaming(client, project_id, payload, json_mode, ci_mode)
    else:
        if not json_mode:
            click.echo(f"({len(commits)} commits — submitting without inline evaluation)")
        _submit_basic(client, project_id, payload, json_mode)


def _submit_streaming(client, project_id, payload, json_mode, ci_mode=False):
    """Submit via SSE streaming endpoint with inline evaluation."""
    console = get_console()
    processed = []  # track what the server already saved
    spinner = None

    try:
        summary = None
        for event, event_data in client.submit_commits_stream(project_id, payload):
            if json_mode:
                print_json({"event": event, **event_data})
                if event == "complete":
                    summary = event_data
                continue

            sha = event_data.get("sha", "?")

            if event == "received":
                if spinner:
                    spinner.stop()
                    spinner = None
                processed.append(sha)
                status = event_data.get("status", "")
                if status == "duplicate":
                    console.print(f"  {sha} — already submitted", style="dim")
                elif status == "PENDING_CLAIM":
                    console.print(f"\u2713 {sha} — received (unclaimed, author not on Tillio)", style="green")
                else:
                    console.print(f"\u2713 {sha} — received", style="green")

            elif event == "evaluating":
                if ci_mode:
                    click.echo(f"  {sha} evaluating...")
                else:
                    spinner = console.status(f"  {sha} evaluating...", spinner="dots")
                    spinner.start()

            elif event == "scored":
                if spinner:
                    spinner.stop()
                    spinner = None
                units = event_data.get("units", 0)
                confidence = event_data.get("confidence", 0)
                scope = event_data.get("scope")
                score_info = f"{units:.0f} units (quality: {confidence:.0%}"
                if scope is not None:
                    score_info += f", scope: {float(scope):.0%}"
                score_info += ")"
                console.print(f"  {sha} \u2713 {score_info}", style="green")

            elif event == "error":
                if spinner:
                    spinner.stop()
                    spinner = None
                msg = event_data.get("message", "unknown error")
                console.print(f"  {sha} \u2717 {msg}", style="red")

            elif event == "complete":
                summary = event_data

        if spinner:
            spinner.stop()
            spinner = None

        if not json_mode and summary:
            click.echo()
            submitted = summary.get("submitted", 0)
            evaluated = summary.get("evaluated", 0)
            duplicates = summary.get("duplicates", 0)
            if evaluated:
                console.print(f"\u2713 {evaluated} commit(s) evaluated", style="bold green")
            elif submitted:
                console.print(f"\u2713 {submitted} commit(s) submitted", style="bold green")
            if duplicates:
                console.print(f"  {duplicates} duplicate(s) skipped", style="dim")

    except KeyboardInterrupt:
        if spinner:
            spinner.stop()
        click.echo()
        if processed:
            click.echo(f"Interrupted. {len(processed)} commit(s) already saved: {', '.join(processed)}")
        else:
            click.echo("Interrupted before any commits were saved.")
        raise SystemExit(EXIT_SIGINT)

    except APIError as e:
        if spinner:
            spinner.stop()
        # Fallback: if streaming endpoint unavailable (404, proxy issue), use non-streaming
        if "404" in str(e):
            if not json_mode:
                click.echo("(streaming unavailable — falling back)")
            _submit_basic(client, project_id, payload, json_mode)
            return

        if json_mode:
            print_json({"error": f"Submission failed: {e}"})
        else:
            click.echo(f"\u2717 Submission failed: {e}", err=True)
        raise SystemExit(EXIT_GENERAL)


def _submit_basic(client, project_id, payload, json_mode):
    """Submit via non-streaming endpoint (no inline evaluation)."""
    try:
        result = client.submit_commits(project_id, payload)
    except DuplicateError as e:
        if json_mode:
            print_json({"submitted": 0, "duplicates": len(payload["commits"]), "message": str(e)})
        else:
            click.echo(f"All commits already submitted. {e}")
        return
    except APIError as e:
        if json_mode:
            print_json({"error": f"Submission failed: {e}"})
        else:
            click.echo(f"✗ Submission failed: {e}", err=True)
        raise SystemExit(EXIT_GENERAL)

    if json_mode:
        print_json(result)
        return

    click.echo()
    for c in result.get("contributions", []):
        sha = c.get("sha", "?")
        status = c.get("status", "unknown")
        if status == "duplicate":
            click.echo(f"  {sha} — already submitted")
        elif status == "PENDING_CLAIM":
            click.echo(f"✓ {sha} — submitted (unclaimed, author not on Tillio)")
        else:
            click.echo(f"✓ {sha} — submitted (evaluation queued)")

    click.echo()
    submitted = result.get("submitted", 0)
    duplicates = result.get("duplicates", 0)
    if submitted:
        click.echo(f"✓ {submitted} commit(s) submitted (evaluation queued)")
    if duplicates:
        click.echo(f"  {duplicates} duplicate(s) skipped")
