"""tillio login — authenticate and store API key."""

import click
from rich.panel import Panel
from tillio_cli.config import save_config, load_config, get_api_url
from tillio_cli.api import TillioClient, APIError
from tillio_cli.output import get_console
from tillio_cli.exit_codes import EXIT_VALIDATION


@click.command()
@click.option("--key", default=None, help="Your Tillio API key (skips wizard)")
@click.option("--url", default=None, help="API URL (default: http://localhost:8000)")
@click.pass_context
def login(ctx, key: str, url: str):
    """Authenticate with the Tillio platform.

    \b
    Examples:
        tillio login                     # interactive wizard
        tillio login --key tillio_abc123  # non-interactive
    """
    console = get_console(ctx)
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False

    if not key and ci_mode:
        click.echo("✗ --key is required in CI mode: tillio login --key <key>", err=True)
        raise SystemExit(EXIT_VALIDATION)

    if not key:
        # Interactive wizard
        click.echo()
        click.echo("  Welcome to Tillio!")
        click.echo()
        click.echo("  To get your API key:")
        click.echo("    1. Go to your Tillio instance /account")
        click.echo("    2. Click the Developer tab")
        click.echo("    3. Copy your API key")
        click.echo()
        key = click.prompt("  API Key", hide_input=True)
        if not url:
            use_custom = click.confirm("  Use a custom API URL?", default=False)
            if use_custom:
                url = click.prompt("  API URL", default="http://localhost:8000")

    key = key.strip()
    config = load_config()
    config["api_key"] = key
    if url:
        config["api_url"] = url.strip()
    save_config(config)

    api_url = url or get_api_url()
    click.echo(f"\u2713 API key saved to ~/.tillio/config.yaml")
    click.echo(f"  API URL: {api_url}")

    # Verify the key works
    try:
        client = TillioClient(api_key=key, api_url=api_url)
        project_list = client.list_projects()
        console.print(Panel(
            f"\u2713 Authenticated — {len(project_list)} project(s) found\n\n"
            "  [dim]tillio projects[/dim]         list your projects\n"
            "  [dim]tillio submit[/dim]           submit commits\n"
            "  [dim]tillio contributions[/dim]    view your contributions",
            title="Connected",
            border_style="green",
            expand=False,
        ))
    except Exception as e:
        click.echo(f"\u26a0 Key saved but verification failed: {e}", err=True)
        click.echo("  Check your key and try again: tillio login", err=True)
