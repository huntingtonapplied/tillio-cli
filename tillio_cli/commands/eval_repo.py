"""tillio eval repo <url> — evaluate a remote repository by URL."""

import click
from tillio_cli.api import TillioClient, AuthError, APIError
from tillio_cli.output import get_console, is_json, print_json
from tillio_cli.exit_codes import EXIT_AUTH, EXIT_GENERAL, EXIT_VALIDATION, EXIT_SIGINT


@click.command()
@click.argument("url")
@click.option("--category", default="TECHNICAL", type=click.Choice(
    ["TECHNICAL", "RESEARCH", "DESIGN", "MARKETING", "BUSINESS", "STEWARDSHIP"],
    case_sensitive=False,
), help="Evaluation category")
@click.option("--watch", is_flag=True, default=False,
              help="Stream progress events in real-time (SSE)")
@click.pass_context
def repo(ctx, url: str, category: str, watch: bool):
    """Evaluate a remote repository by URL.

    Clones the repo on the server, samples files by priority, and
    returns evaluation scores. No project is created.

    Use --watch to see real-time progress (cloning, sampling, scoring).

    \b
    Examples:
        tillio eval repo https://github.com/pallets/click
        tillio eval repo https://github.com/owner/repo --category RESEARCH
        tillio eval repo https://github.com/owner/repo --watch
    """
    json_mode = is_json(ctx)
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False
    console = get_console(ctx) if not json_mode else None

    # Validate URL
    if not url.startswith("https://"):
        if json_mode:
            print_json({"error": "URL must start with https://"})
        else:
            click.echo("URL must start with https://", err=True)
        raise SystemExit(EXIT_VALIDATION)

    # Authenticate
    try:
        client = TillioClient()
    except AuthError as e:
        if json_mode:
            print_json({"error": str(e)})
        else:
            click.echo(f"\u2717 {e}", err=True)
        raise SystemExit(EXIT_AUTH)

    if watch:
        _eval_streaming(client, url, category, json_mode, ci_mode, console)
    else:
        _eval_sync(client, url, category, json_mode, ci_mode, console)


def _eval_streaming(client, url, category, json_mode, ci_mode, console):
    """Evaluate with SSE streaming progress."""
    spinner = None
    try:
        for event, data in client.eval_repo_stream(url, category.upper()):
            if json_mode:
                print_json({"event": event, **data})
                continue

            if event == "cloning":
                if spinner:
                    spinner.stop()
                if ci_mode:
                    click.echo("Cloning repository...")
                else:
                    spinner = console.status("Cloning repository...", spinner="dots")
                    spinner.start()

            elif event == "sampling":
                if spinner:
                    spinner.stop()
                total_files = data.get("total_files")
                if total_files:
                    msg = (
                        f"Scanned {total_files} files, {data.get('total_lines', 0):,} lines "
                        f"| {data.get('files_sampled', '?')} sampled "
                        f"({data.get('strategy', '')}, {data.get('tier', '')})"
                    )
                    console.print(msg)
                if ci_mode:
                    click.echo("Sampling files...")
                else:
                    spinner = console.status("Sampling files...", spinner="dots")
                    spinner.start()

            elif event == "evaluating":
                if spinner:
                    spinner.stop()
                batch_msg = f"Evaluating batch {data.get('batch_index', 0) + 1}/{data.get('total_batches', 1)}..."
                if ci_mode:
                    click.echo(batch_msg)
                else:
                    spinner = console.status(batch_msg, spinner="dots")
                    spinner.start()

            elif event == "scored":
                # Per-batch score — show briefly if multi-batch
                pass

            elif event == "complete":
                if spinner:
                    spinner.stop()
                _display_results(console, data)

            elif event == "error":
                if spinner:
                    spinner.stop()
                console.print(f"\u2717 {data.get('message', 'Unknown error')}", style="red")
                raise SystemExit(EXIT_GENERAL)

    except KeyboardInterrupt:
        if spinner:
            spinner.stop()
        click.echo("\nInterrupted.")
        raise SystemExit(EXIT_SIGINT)

    except APIError as e:
        if spinner:
            spinner.stop()
        # Fall back to sync if streaming endpoint not available
        if "404" in str(e):
            if not json_mode:
                click.echo("(streaming unavailable — using synchronous eval)")
            _eval_sync(client, url, category, json_mode, False, console)
            return
        if json_mode:
            print_json({"error": str(e)})
        else:
            click.echo(f"\u2717 {e}", err=True)
        raise SystemExit(EXIT_GENERAL)


def _eval_sync(client, url, category, json_mode, ci_mode, console):
    """Evaluate synchronously (single request)."""
    if not json_mode:
        console.print(f"Evaluating {url}...")
        click.echo()

    spinner = None
    if not json_mode and not ci_mode:
        spinner = console.status("Cloning and evaluating...", spinner="dots")
        spinner.start()

    try:
        result = client.eval_repo(url, category.upper())
    except APIError as e:
        if spinner:
            spinner.stop()
        if json_mode:
            print_json({"error": str(e)})
        else:
            click.echo(f"\u2717 Evaluation failed: {e}", err=True)
        raise SystemExit(EXIT_GENERAL)

    if spinner:
        spinner.stop()

    if json_mode:
        print_json(result)
        return

    _display_results(console, result)


def _display_results(console, result):
    """Render evaluation results to the console."""
    scores = result.get("scores", {})
    rationale = result.get("rationale", "")
    repo_meta = result.get("repo_metadata", {})
    sampling = result.get("sampling", {})
    duration_ms = result.get("eval_duration_ms", 0)

    # Repo info
    console.print(f"[bold]{repo_meta.get('name', '?')}[/bold]")
    console.print(
        f"  {repo_meta.get('total_files', '?')} files, "
        f"{repo_meta.get('total_lines', '?'):,} lines"
    )
    if sampling:
        console.print(
            f"  Sampled {sampling.get('files_sampled', '?')}/{sampling.get('files_total', '?')} files "
            f"({sampling.get('strategy', '?')}, {sampling.get('tier', '?')} repo)",
            style="dim",
        )
    click.echo()

    # Scores
    console.print("[bold]Evaluation Results[/bold]")
    console.print(f"  Confidence: {float(scores.get('confidence_score', 0)):.0%}")
    console.print(f"  Novelty:    {float(scores.get('novelty_score', 0)):.0%}")
    console.print(f"  Impact:     {float(scores.get('impact_score', 0)):.0%}")
    console.print(f"  Alignment:  {float(scores.get('alignment_score', 0)):.0%}")
    scope = scores.get("scope_score")
    if scope is not None:
        console.print(f"  Scope:      {float(scope):.0%}")
    click.echo()

    if rationale:
        console.print(f"[dim]{rationale}[/dim]")

    if duration_ms:
        click.echo()
        console.print(f"Completed in {duration_ms / 1000:.1f}s", style="dim")
