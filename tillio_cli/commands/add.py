"""tillio add — create a project in Tillio from a repository URL."""

import click
from tillio_cli.git import get_repo_url
from tillio_cli.api import TillioClient, AuthError, APIError
from tillio_cli.output import is_json, print_json
from tillio_cli.exit_codes import EXIT_AUTH, EXIT_VALIDATION, EXIT_NOT_GIT_REPO


@click.command()
@click.argument("repo_url", default="")
@click.pass_context
def add(ctx, repo_url: str):
    """Create or link a project in Tillio from a repository URL.

    \b
    If no URL is provided, uses the current repo's remote URL.

    \b
    Examples:
        tillio add                                  # use current repo
        tillio add https://github.com/user/repo     # specific URL
    """
    json_mode = is_json(ctx)

    if not repo_url:
        repo_url = get_repo_url()
        if not repo_url:
            if json_mode:
                print_json({"error": "No repository URL provided and no git remote found"})
            else:
                click.echo("\u2717 No repository URL provided and no git remote found.", err=True)
                click.echo("  Usage: tillio add <repo-url>", err=True)
                click.echo("  Or run from inside a git repo with a remote.", err=True)
            raise SystemExit(EXIT_NOT_GIT_REPO)

    try:
        client = TillioClient()
    except AuthError as e:
        if json_mode:
            print_json({"error": str(e)})
        else:
            click.echo(f"\u2717 {e}", err=True)
        raise SystemExit(EXIT_AUTH)

    # Try to find or create
    try:
        result = client.post("/v1/projects/from-repo", {"repository_url": repo_url})
    except APIError as e:
        if json_mode:
            print_json({"error": str(e), "repository_url": repo_url})
        else:
            click.echo(f"\u2717 Failed to add project: {e}", err=True)
        raise SystemExit(EXIT_VALIDATION)

    if json_mode:
        print_json(result)
        return

    created = result.get("created", False)
    name = result.get("name", "Unknown")
    pid = result.get("id", "")

    if created:
        click.echo(f"\u2713 Created project: {name}")
    else:
        click.echo(f"\u2713 Project already exists: {name}")

    click.echo(f"  Project ID: {pid}")
    click.echo(f"  Repository: {repo_url}")
    click.echo()
    click.echo("  Next steps:")
    click.echo("    tillio submit          # submit commits as contributions")
    click.echo("    tillio status          # check project status")
