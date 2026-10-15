"""tillio eval code — score files/directories by content.

This is the sampling-aware replacement for `tillio score-repo`.
Delegates to the same core logic in score_repo.py.
"""

import click
from tillio_cli.commands.score_repo import score_repo


@click.command()
@click.argument("targets", nargs=-1, required=True)
@click.option("--project-id", default=None, help="Tillio project ID (auto-detected from repo URL)")
@click.option("--category", default="TECHNICAL", type=click.Choice(
    ["TECHNICAL", "RESEARCH", "DESIGN", "MARKETING", "BUSINESS", "STEWARDSHIP"],
    case_sensitive=False,
), help="Contribution category")
@click.option("--recursive/--no-recursive", "-r", default=True, help="Recurse into subdirectories")
@click.option("--dry-run", is_flag=True, help="Preview what would be scored")
@click.option("--title", default=None, help="Custom contribution title")
@click.option("--description", default=None, help="Custom description")
@click.pass_context
def code(ctx, targets, project_id, category, recursive, dry_run, title, description):
    """Score files or directories by content.

    Files are selected by priority (recency, structural importance, dependency
    weight) and the token budget scales automatically with repo size.

    \b
    Examples:
        tillio eval code src/services/auth.py         # score a single file
        tillio eval code src/services/                 # score a directory
        tillio eval code src/ lib/ --category TECHNICAL
        tillio eval code src/ --dry-run                # preview only
    """
    # Delegate to score_repo's implementation
    ctx.invoke(
        score_repo,
        targets=targets,
        project_id=project_id,
        category=category,
        recursive=recursive,
        dry_run=dry_run,
        title=title,
        description=description,
    )
