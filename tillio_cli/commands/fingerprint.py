"""tillio fingerprint — analyze and store repository size/complexity stats."""

import os
import click
from datetime import datetime, timezone
from collections import defaultdict
from tillio_cli.git import run_git, get_repo_url
from tillio_cli.api import TillioClient, AuthError, APIError
from tillio_cli.output import get_console, is_json, print_json
from tillio_cli.exit_codes import EXIT_AUTH, EXIT_GENERAL, EXIT_NOT_FOUND, EXIT_NOT_GIT_REPO, EXIT_VALIDATION

# Extensions to count as code
CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".scala",
    ".sh", ".bash", ".zsh", ".sql", ".html", ".css", ".scss", ".vue",
    ".svelte", ".tf", ".yaml", ".yml", ".toml",
}

# Dirs to skip
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", "dist", "build", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".next", ".cache", "vendor",
    "target", "bin", "obj",
}


def _analyze_repo(cwd=None):
    """Walk the repo and gather size/complexity stats."""
    root = cwd or "."

    total_lines = 0
    total_files = 0
    languages = defaultdict(int)  # ext -> lines
    dir_stats = defaultdict(lambda: {"lines": 0, "files": 0})

    for dirpath, dirs, filenames in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]

        rel_dir = os.path.relpath(dirpath, root)

        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in CODE_EXTS:
                continue

            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    lines = sum(1 for _ in f)
            except OSError:
                continue

            total_lines += lines
            total_files += 1
            languages[ext] += lines

            # Track top-level directory stats
            top_dir = rel_dir.split(os.sep)[0] if rel_dir != "." else "."
            dir_stats[top_dir]["lines"] += lines
            dir_stats[top_dir]["files"] += 1

    # Get commit/contributor counts from git
    total_commits = 0
    total_contributors = 0
    try:
        commit_output = run_git(["rev-list", "--count", "HEAD"], cwd=cwd)
        total_commits = int(commit_output.strip())
    except (RuntimeError, ValueError):
        pass

    try:
        contrib_output = run_git(["shortlog", "-sn", "--all", "--no-merges"], cwd=cwd)
        total_contributors = len([l for l in contrib_output.splitlines() if l.strip()])
    except RuntimeError:
        pass

    # Sort directories by lines
    top_directories = sorted(
        [{"path": p, **s} for p, s in dir_stats.items()],
        key=lambda x: -x["lines"],
    )[:20]

    avg_file_size = total_lines // total_files if total_files > 0 else 0

    return {
        "total_lines": total_lines,
        "total_files": total_files,
        "total_commits": total_commits,
        "total_contributors": total_contributors,
        "languages": dict(languages),
        "top_directories": top_directories,
        "avg_file_size": avg_file_size,
        "fingerprinted_at": datetime.now(timezone.utc).isoformat(),
    }


@click.command()
@click.option("--project-id", default=None, help="Tillio project ID (auto-detected from repo URL)")
@click.option("--repo-path", default=None, type=click.Path(exists=True), help="Path to repository")
@click.option("--dry-run", is_flag=True, help="Analyze and display stats without uploading")
@click.pass_context
def fingerprint(ctx, project_id, repo_path, dry_run):
    """
    Analyze repository and store size/complexity fingerprint.

    The fingerprint calibrates scope scores for AI evaluation — it tells
    the scoring model how large the project is so individual contributions
    are scored proportionally.

    \b
    Examples:
        tillio fingerprint                     # fingerprint current repo
        tillio fingerprint --repo-path /path   # fingerprint another repo
        tillio fingerprint --dry-run           # preview only
    """
    json_mode = is_json(ctx)
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False
    cwd = repo_path
    console = get_console(ctx) if not json_mode else None

    # Validate git repo
    try:
        run_git(["rev-parse", "--is-inside-work-tree"], cwd=cwd)
    except (RuntimeError, FileNotFoundError):
        if json_mode:
            print_json({"error": "Not a git repository"})
        else:
            click.echo("✗ Not a git repository.", err=True)
        raise SystemExit(EXIT_NOT_GIT_REPO)

    spinner = None
    if not json_mode and not ci_mode:
        spinner = console.status("Analyzing repository...", spinner="dots")
        spinner.start()

    stats = _analyze_repo(cwd)

    if spinner:
        spinner.stop()

    # Display stats
    if not json_mode:
        console.print(f"[bold]Repository Fingerprint[/bold]")
        console.print(f"  Lines of code:  {stats['total_lines']:,}")
        console.print(f"  Files:          {stats['total_files']:,}")
        console.print(f"  Commits:        {stats['total_commits']:,}")
        console.print(f"  Contributors:   {stats['total_contributors']:,}")
        console.print(f"  Avg file size:  {stats['avg_file_size']} lines")
        click.echo()

        if stats["languages"]:
            console.print("[bold]Languages:[/bold]")
            sorted_langs = sorted(stats["languages"].items(), key=lambda x: -x[1])
            for ext, lines in sorted_langs[:10]:
                pct = lines / stats["total_lines"] * 100 if stats["total_lines"] else 0
                console.print(f"  {ext:8s} {lines:>8,} lines ({pct:.0f}%)")
            click.echo()

        if stats["top_directories"]:
            console.print("[bold]Top Directories:[/bold]")
            for d in stats["top_directories"][:10]:
                console.print(f"  {d['path']:30s} {d['lines']:>8,} lines, {d['files']:>4} files")
            click.echo()

    if dry_run:
        if json_mode:
            print_json({"dry_run": True, **stats})
        else:
            console.print("Dry run — not uploaded. Remove --dry-run to store.", style="dim")
        return

    # Upload
    try:
        client = TillioClient()
    except AuthError as e:
        if json_mode:
            print_json({"error": str(e)})
        else:
            click.echo(f"✗ {e}", err=True)
        raise SystemExit(EXIT_AUTH)

    # Resolve project
    repo_url = get_repo_url(cwd)
    if not project_id:
        if not repo_url:
            if json_mode:
                print_json({"error": "No --project-id and no git remote URL"})
            else:
                click.echo("✗ No --project-id and no git remote URL.", err=True)
            raise SystemExit(EXIT_VALIDATION)

        project = client.lookup_project(repo_url)
        if project:
            project_id = project["id"]
        else:
            if json_mode:
                print_json({"error": f"No project found for {repo_url}"})
            else:
                click.echo(f"✗ No project found for {repo_url}. Run: tillio add", err=True)
            raise SystemExit(EXIT_NOT_FOUND)

    try:
        result = client.post(f"/v1/projects/{project_id}/fingerprint", stats)
    except APIError as e:
        if json_mode:
            print_json({"error": str(e)})
        else:
            click.echo(f"✗ Upload failed: {e}", err=True)
        raise SystemExit(EXIT_GENERAL)

    if json_mode:
        print_json(result)
    else:
        console.print("✓ Fingerprint stored on project", style="bold green")
        console.print("  Future evaluations will use these stats to calibrate scope scores.", style="dim")
