"""tillio index — generate TILLIO.md from project eval index."""

import os
import click
from tillio_cli.api import TillioClient, AuthError, APIError
from tillio_cli.git import get_repo_url
from tillio_cli.output import get_console, is_json, print_json
from tillio_cli.exit_codes import EXIT_AUTH, EXIT_GENERAL


@click.command()
@click.option("--project-id", default=None, help="Tillio project ID (auto-detected from repo URL)")
@click.option("--output", "-o", "output_path", default="TILLIO.md",
              help="Output file path (default: TILLIO.md)")
@click.option("--stdout", is_flag=True, help="Print to stdout instead of writing file")
@click.pass_context
def index(ctx, project_id, output_path, stdout):
    """Generate TILLIO.md from the project evaluation index.

    Shows which files have been evaluated, their scores, and which
    files are stale (changed since last evaluation).

    \b
    Examples:
        tillio index                        # write TILLIO.md in current dir
        tillio index --stdout               # print to terminal
        tillio index -o docs/INDEX.md       # custom output path
    """
    json_mode = is_json(ctx)
    console = get_console(ctx) if not json_mode else None

    try:
        client = TillioClient()
    except AuthError as e:
        if json_mode:
            print_json({"error": str(e)})
        else:
            click.echo(f"\u2717 {e}", err=True)
        raise SystemExit(EXIT_AUTH)

    # Resolve project
    if not project_id:
        repo_url = get_repo_url()
        if repo_url:
            project = client.lookup_project(repo_url)
            if project:
                project_id = project["id"]
            else:
                if json_mode:
                    print_json({"error": "No project found for this repository"})
                else:
                    click.echo("No Tillio project found for this repository.", err=True)
                raise SystemExit(EXIT_GENERAL)
        else:
            if json_mode:
                print_json({"error": "No --project-id and no git remote URL"})
            else:
                click.echo("No --project-id and no git remote URL.", err=True)
            raise SystemExit(EXIT_GENERAL)

    # Fetch index from API
    try:
        result = client.get(f"/v1/projects/{project_id}/index")
    except APIError as e:
        if json_mode:
            print_json({"error": str(e)})
        else:
            click.echo(f"\u2717 Failed to fetch project index: {e}", err=True)
        raise SystemExit(EXIT_GENERAL)

    if json_mode:
        print_json(result)
        return

    # Extract markdown content
    content = result.get("markdown") or result.get("data", {}).get("markdown", "")
    if not content:
        click.echo("No index data available. Run `tillio eval code` first.")
        return

    if stdout:
        click.echo(content)
    else:
        with open(output_path, "w") as f:
            f.write(content)
        console.print(f"Wrote {output_path}", style="green")

        # Show summary
        stats = result.get("stats") or result.get("data", {}).get("stats", {})
        if stats:
            console.print(
                f"  {stats.get('total_indexed', 0)} files indexed, "
                f"{stats.get('current', 0)} current, "
                f"{stats.get('stale', 0)} stale"
            )
