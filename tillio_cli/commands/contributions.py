"""tillio contributions — list your contributions with scores."""

import click
from datetime import datetime, timezone
from rich.table import Table
from tillio_cli.api import TillioClient, AuthError, APIError
from tillio_cli.output import get_console, is_json, is_structured, print_json, print_structured
from tillio_cli.exit_codes import EXIT_AUTH, EXIT_GENERAL


STATUS_DISPLAY = {
    "PENDING":        ("\u23f3", "Pending"),        # ⏳
    "EVALUATING":     ("\u26a1", "Evaluating"),     # ⚡
    "PENDING_REVIEW": ("\U0001f440", "In Review"),  # 👀
    "SUBMITTED":      ("\U0001f4e4", "Submitted"),  # 📤
    "APPROVED":       ("\u2705", "Approved"),        # ✅
    "REJECTED":       ("\u274c", "Rejected"),        # ❌
    "DISPUTED":       ("\u26a0\ufe0f", "Disputed"),  # ⚠️
    "WITHDRAWN":      ("\U0001f6ab", "Withdrawn"),   # 🚫
    "PENDING_CLAIM":  ("\U0001f4cb", "Unclaimed"),   # 📋
}


def _format_status(status_str: str) -> str:
    """Format status with icon and human-readable label."""
    entry = STATUS_DISPLAY.get(status_str)
    if entry:
        return f"{entry[0]} {entry[1]}"
    return status_str


def _relative_time(iso_str) -> str:
    """Convert ISO timestamp to relative time (e.g., '2m ago', '1h ago')."""
    if not iso_str:
        return ""
    try:
        # Handle various ISO formats
        ts = iso_str.replace("Z", "+00:00")
        if "+" not in ts and ts.count("-") <= 2:
            ts += "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        secs = int(delta.total_seconds())
        if secs < 0:
            return "just now"
        if secs < 60:
            return f"{secs}s ago"
        mins = secs // 60
        if mins < 60:
            return f"{mins}m ago"
        hours = mins // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days < 30:
            return f"{days}d ago"
        return f"{days // 30}mo ago"
    except (ValueError, TypeError):
        return ""


def _format_units(value) -> str:
    """Format units, handling None/null gracefully."""
    if value is None:
        return "Pending"
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "Pending"


def _format_score(value) -> str:
    """Format confidence score, handling None/null gracefully."""
    if value is None:
        return "Pending"
    try:
        return f"{float(value):.0%}"
    except (TypeError, ValueError):
        return "Pending"


@click.command()
@click.option("--limit", "-n", default=20, show_default=True, help="Max results to return")
@click.option("--status", "-s", default=None, help="Filter by status (PENDING, APPROVED, etc.)")
@click.option("--project", "-p", default=None, help="Filter by project ID")
@click.option("--after", default=None, help="Show contributions after date (YYYY-MM-DD)")
@click.option("--quiet", "-q", is_flag=True, help="Print only contribution IDs")
@click.option("--csv", "csv_mode", is_flag=True, help="Output as CSV")
@click.pass_context
def contributions(ctx, limit, status, project, after, quiet, csv_mode):
    """List your contributions with evaluation scores.

    \b
    Examples:
        tillio contributions                        # all recent
        tillio contributions --status APPROVED       # only approved
        tillio contributions --project <id>          # by project
        tillio contributions --after 2026-04-01      # since April 1
        tillio contributions --quiet                 # IDs only (for scripts)
        tillio contributions --csv                   # CSV output
    """
    try:
        client = TillioClient()
    except AuthError as e:
        click.echo(f"\u2717 {e}", err=True)
        raise SystemExit(EXIT_AUTH)

    params = {}
    if limit != 20:
        params["limit"] = limit
    if status:
        params["status"] = status
    if project:
        params["project_id"] = project
    if after:
        params["date_from"] = after

    try:
        contribs = client.list_contributions(params=params)
    except APIError as e:
        if is_structured(ctx):
            print_structured(ctx, {"error": str(e)})
        else:
            click.echo(f"\u2717 {e}", err=True)
        raise SystemExit(EXIT_GENERAL)

    if is_structured(ctx):
        print_structured(ctx, contribs)
        return

    if not contribs:
        click.echo("No contributions found.")
        return

    # Quiet mode: IDs only
    if quiet:
        for c in contribs:
            click.echo(c.get("id", ""))
        return

    # CSV mode
    if csv_mode:
        click.echo("id,project,title,status,units,score,scope,submitted_at")
        for c in contribs:
            proj = c.get("project")
            proj_name = proj.get("name", "") if isinstance(proj, dict) else ""
            title = (c.get("title") or "").replace(",", ";")
            st = c.get("status", "")
            units = c.get("unitsAssigned") or c.get("units_assigned") or c.get("actual_value") or ""
            score = c.get("confidenceScore") or c.get("confidence_score") or ""
            scope = c.get("scopeScore") or c.get("scope_score") or ""
            submitted = c.get("submittedAt") or c.get("submitted_at") or c.get("createdAt") or c.get("created_at") or ""
            click.echo(f"{c.get('id', '')},{proj_name},{title},{st},{units},{score},{scope},{submitted}")
        return

    # Table mode (default)
    console = get_console(ctx)
    table = Table(show_edge=False, pad_edge=False, box=None)
    table.add_column("Project", style="cyan", min_width=16)
    table.add_column("Title", min_width=20)
    table.add_column("Status", min_width=12)
    table.add_column("Units", justify="right", style="bold")
    table.add_column("Quality", justify="right")
    table.add_column("Scope", justify="right")
    table.add_column("Submitted", justify="right", style="dim")

    for c in contribs:
        proj = c.get("project")
        if isinstance(proj, dict):
            proj_name = (proj.get("name") or "Unknown")[:24]
        else:
            proj_name = "Unknown"

        title = (c.get("title") or "Untitled")[:32]
        st = c.get("status", "unknown")
        status_display = _format_status(st)

        units = c.get("unitsAssigned") or c.get("units_assigned") or c.get("actual_value")
        score = c.get("confidenceScore") or c.get("confidence_score")
        scope = c.get("scopeScore") or c.get("scope_score")

        units_str = _format_units(units)
        score_str = _format_score(score)
        scope_str = _format_score(scope)

        submitted = c.get("submittedAt") or c.get("submitted_at") or c.get("createdAt") or c.get("created_at")
        time_str = _relative_time(submitted)

        table.add_row(proj_name, title, status_display, units_str, score_str, scope_str, time_str)

    console.print(table)

    if len(contribs) == limit:
        console.print(f"\nShowing first {limit}. Use --limit to see more.", style="dim")
