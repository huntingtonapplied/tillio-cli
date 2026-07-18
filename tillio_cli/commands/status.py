"""tillio status — show project and recent contribution info."""

import click
from rich.panel import Panel
from rich.table import Table
from tillio_cli.git import run_git, get_repo_url, get_branch
from tillio_cli.api import TillioClient, AuthError, APIError
from tillio_cli.output import get_console, is_json, print_json
from tillio_cli.exit_codes import EXIT_AUTH, EXIT_NOT_GIT_REPO


STATUS_ICONS = {
    "PENDING": "\u23f3",
    "EVALUATING": "\u26a1",
    "PENDING_REVIEW": "\U0001f440",
    "APPROVED": "\u2705",
    "REJECTED": "\u274c",
    "DISPUTED": "\u26a0\ufe0f",
    "WITHDRAWN": "\U0001f6ab",
    "PENDING_CLAIM": "\U0001f4cb",
}


@click.command()
@click.pass_context
def status(ctx):
    """Show linked project and recent contributions."""
    try:
        run_git(["rev-parse", "--is-inside-work-tree"])
    except (RuntimeError, FileNotFoundError):
        click.echo("Not a git repository. Run this from inside a git repo.", err=True)
        raise SystemExit(EXIT_NOT_GIT_REPO)

    repo_url = get_repo_url()
    branch = get_branch()

    try:
        client = TillioClient()
    except AuthError as e:
        click.echo(f"\u2717 {e}", err=True)
        raise SystemExit(EXIT_AUTH)

    # Look up project
    project = client.lookup_project(repo_url) if repo_url else None
    contribs = client.list_contributions() if project else []

    if is_json(ctx):
        print_json({
            "repository_url": repo_url or None,
            "branch": branch,
            "project": project,
            "recent_contributions": contribs[:5] if contribs else [],
        })
        return

    console = get_console(ctx)

    if not repo_url:
        console.print(Panel(
            f"Repository: [dim](no remote)[/dim]\n"
            f"Branch:     {branch}",
            expand=False,
        ))
        click.echo()
        click.echo("No remote configured. Use 'tillio submit --project-id <id>' to submit.")
        return

    if project:
        proj_status = project.get("status", "unknown")
        console.print(Panel(
            f"Repository: [cyan]{repo_url}[/cyan]\n"
            f"Branch:     {branch}\n"
            f"Project:    [bold]{project['name']}[/bold] ({proj_status})\n"
            f"Project ID: [dim]{project['id']}[/dim]",
            expand=False,
        ))
    else:
        console.print(Panel(
            f"Repository: [cyan]{repo_url}[/cyan]\n"
            f"Branch:     {branch}\n"
            f"Project:    [dim]Not linked to Tillio yet[/dim]",
            expand=False,
        ))
        click.echo()
        click.echo("Run 'tillio submit' to auto-create a project")
        return

    # Show recent contributions
    click.echo()
    if contribs:
        click.echo("Recent contributions:")
        table = Table(show_edge=False, pad_edge=False, box=None, padding=(0, 1, 0, 1))
        table.add_column("Status", min_width=14)
        table.add_column("Units", justify="right", style="bold")
        table.add_column("Title")

        for c in contribs[:5]:
            units = c.get("unitsAssigned") or c.get("units_assigned") or c.get("actual_value")
            units_str = f"{float(units):.1f}" if units is not None else "Pending"
            status_val = c.get("status", "unknown")
            icon = STATUS_ICONS.get(status_val, "")
            status_display = f"{icon} {status_val}" if icon else status_val
            title = (c.get("title") or "")[:50]
            table.add_row(status_display, units_str, title)

        console.print(table)
    else:
        click.echo("No contributions yet. Run 'tillio submit' to get started.")
