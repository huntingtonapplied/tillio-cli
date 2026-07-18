"""tillio projects — list, create, and delete projects."""

import click
from rich.table import Table
from tillio_cli.api import TillioClient, AuthError, APIError
from tillio_cli.output import get_console, is_structured, print_structured
from tillio_cli.exit_codes import EXIT_AUTH, EXIT_GENERAL


STATUS_ICONS = {
    "ACTIVE": "\u2705",
    "DRAFT": "\U0001f4dd",
    "READY": "\U0001f680",
    "ARCHIVED": "\U0001f4e6",
}


@click.command()
@click.option("--limit", "-n", default=20, show_default=True, help="Max results to return")
@click.option("--status", "-s", default=None, help="Filter by status (draft, active, archived)")
@click.option("--quiet", "-q", is_flag=True, help="Print only project IDs")
@click.option("--csv", "csv_mode", is_flag=True, help="Output as CSV")
@click.option("--create", "create_name", default=None, help="Create a new project with this name")
@click.option("--delete", "delete_id", default=None, help="Delete a project by ID")
@click.option("--search", default=None, help="Search projects by name (fuzzy match)")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompts")
@click.pass_context
def projects(ctx, limit, status, quiet, csv_mode, create_name, delete_id, search, yes):
    """List, create, or delete projects on Tillio.

    \b
    Examples:
        tillio projects                        # list all
        tillio projects --status active        # only active
        tillio projects --search "test qa"     # fuzzy search
        tillio projects --create "My Project"  # create new project
        tillio projects --delete <id>          # delete a project
        tillio projects --quiet                # IDs only (for scripts)
        tillio projects --csv                  # CSV output
        tillio -o yaml projects                # YAML output
    """
    structured = is_structured(ctx)

    try:
        client = TillioClient()
    except AuthError as e:
        if structured:
            print_structured(ctx, {"error": str(e)})
        else:
            click.echo(f"\u2717 {e}", err=True)
        raise SystemExit(EXIT_AUTH)

    # Create mode
    if create_name:
        _create_project(ctx, client, create_name, structured)
        return

    # Delete mode
    if delete_id:
        ci_mode = ctx.obj.get("ci", False) if ctx.obj else False
        _delete_project(ctx, client, delete_id, structured, skip_confirm=yes or ci_mode)
        return

    # List mode (default)
    params = {}
    if limit != 20:
        params["limit"] = limit
    if status:
        params["status"] = status

    try:
        project_list = client.list_projects(params=params)
    except APIError as e:
        if structured:
            print_structured(ctx, {"error": str(e)})
        else:
            click.echo(f"\u2717 {e}", err=True)
        raise SystemExit(EXIT_GENERAL)

    # Fuzzy search filter (client-side)
    if search:
        search_lower = search.lower()
        project_list = [
            p for p in project_list
            if search_lower in (p.get("name") or "").lower()
            or search_lower in (p.get("description") or "").lower()
        ]
        if not project_list and not structured:
            click.echo(f"No projects matching \"{search}\".")
            all_projects = client.list_projects()
            suggestions = _fuzzy_matches(search, all_projects)
            if suggestions:
                click.echo(f"  Did you mean:")
                for s in suggestions[:3]:
                    click.echo(f"    - {s}")
            return

    if structured:
        print_structured(ctx, project_list)
        return

    if not project_list:
        click.echo("No projects found.")
        return

    # Quiet mode
    if quiet:
        for p in project_list:
            click.echo(p.get("id", ""))
        return

    # CSV mode
    if csv_mode:
        click.echo("id,name,status,contribution_count")
        for p in project_list:
            name = (p.get("name") or "").replace(",", ";")
            st = p.get("status", "")
            cc = p.get("contribution_count", "")
            click.echo(f"{p.get('id', '')},{name},{st},{cc}")
        return

    # Table mode (default)
    console = get_console(ctx)
    table = Table(show_edge=False, pad_edge=False, box=None)
    table.add_column("Name", style="cyan", min_width=20)
    table.add_column("Status", min_width=10)
    table.add_column("Contribs", justify="right", style="bold")
    table.add_column("ID", style="dim")

    for p in project_list:
        name = (p.get("name") or "Untitled")[:36]
        st = p.get("status", "unknown")
        icon = STATUS_ICONS.get(st.upper(), "")
        status_display = f"{icon} {st}" if icon else st
        contrib_count = p.get("contribution_count")
        contrib_str = str(contrib_count) if contrib_count is not None else "-"
        pid = p.get("id", "")
        table.add_row(name, status_display, contrib_str, pid)

    console.print(table)

    if len(project_list) == limit:
        console.print(f"\nShowing first {limit}. Use --limit to see more.", style="dim")


def _create_project(ctx, client, name, structured):
    """Create a new project."""
    try:
        result = client.post("/v1/projects", {
            "name": name,
            "status": "draft",
            "visibility": "private",
        })
    except APIError as e:
        if structured:
            print_structured(ctx, {"error": str(e)})
        else:
            click.echo(f"\u2717 Failed to create project: {e}", err=True)
        raise SystemExit(EXIT_GENERAL)

    if structured:
        print_structured(ctx, result)
        return

    pid = result.get("id", "")
    click.echo(f"\u2713 Created project: {name}")
    click.echo(f"  Project ID: {pid}")
    click.echo()
    click.echo("  Next steps:")
    click.echo("    tillio submit              # submit commits")
    click.echo(f"    tillio submit --project-id {pid}")


def _delete_project(ctx, client, project_id, structured, skip_confirm=False):
    """Delete a project by ID."""
    if not structured and not skip_confirm:
        click.confirm(f"Delete project {project_id}? This cannot be undone", abort=True)

    try:
        client.delete(f"/v1/projects/{project_id}")
    except APIError as e:
        if structured:
            print_structured(ctx, {"error": str(e)})
        else:
            click.echo(f"\u2717 Failed to delete project: {e}", err=True)
        raise SystemExit(EXIT_GENERAL)

    if structured:
        print_structured(ctx, {"deleted": project_id})
    else:
        click.echo(f"\u2713 Deleted project {project_id}")


def _fuzzy_matches(query: str, projects: list) -> list:
    """Find project names similar to query."""
    query_lower = query.lower()
    scored = []
    for p in projects:
        name = p.get("name") or ""
        name_lower = name.lower()
        if query_lower in name_lower:
            scored.append((name, 100))
        else:
            overlap = sum(1 for c in query_lower if c in name_lower)
            ratio = overlap / max(len(query_lower), 1) * 100
            if ratio > 40:
                scored.append((name, ratio))
    scored.sort(key=lambda x: -x[1])
    return [name for name, _ in scored]
