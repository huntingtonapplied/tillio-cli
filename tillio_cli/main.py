"""Tillio CLI entry point."""

import os
import signal
import sys

import click
from tillio_cli import __version__
from tillio_cli.log import setup_logging, logger
from tillio_cli.exit_codes import EXIT_GENERAL, EXIT_SIGINT, EXIT_SIGTERM
from tillio_cli.config import load_config, validate_config
from tillio_cli.update_check import UpdateChecker
from tillio_cli.commands.login import login
from tillio_cli.commands.status import status
from tillio_cli.commands.submit import submit
from tillio_cli.commands.eval import eval
from tillio_cli.commands.projects import projects
from tillio_cli.commands.contributions import contributions
from tillio_cli.commands.completion import completion
from tillio_cli.commands.add import add
from tillio_cli.commands.score_repo import score_repo
from tillio_cli.commands.fingerprint import fingerprint
from tillio_cli.commands.doctor import doctor
from tillio_cli.commands.index import index


@click.group()
@click.version_option(version=__version__, prog_name="tillio")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), default="table",
              help="Output format (default: table)")
@click.option("--no-color", is_flag=True, default=False, envvar="NO_COLOR",
              help="Disable colored output")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Show informational messages (INFO level)")
@click.option("--debug", is_flag=True, default=False,
              help="Show debug messages including HTTP requests")
@click.option("--ci", is_flag=True, default=False,
              help="CI mode: no color, no spinners, no interactive prompts")
@click.pass_context
def cli(ctx, output, no_color, verbose, debug, ci):
    """Tillio CLI — submit contributions from your terminal."""
    # Auto-detect CI environment
    if not ci and (os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or os.getenv("GITLAB_CI")):
        ci = True

    if ci:
        no_color = True

    ctx.ensure_object(dict)
    ctx.obj["output"] = output
    ctx.obj["no_color"] = no_color
    ctx.obj["verbose"] = verbose
    ctx.obj["debug"] = debug
    ctx.obj["ci"] = ci
    setup_logging(verbose=verbose, debug=debug)

    # Validate config and warn about issues
    config = load_config()
    if config:
        warnings = validate_config(config)
        for w in warnings:
            click.echo(f"Warning: {w}", err=True)


cli.add_command(login)
cli.add_command(status)
cli.add_command(submit)
cli.add_command(eval)
cli.add_command(projects)
cli.add_command(contributions)
cli.add_command(completion)
cli.add_command(add)
cli.add_command(score_repo)
cli.add_command(fingerprint)
cli.add_command(doctor)
cli.add_command(index)


_update_checker = UpdateChecker()


def main():
    """Entry point with top-level signal and exception handling."""
    signal.signal(signal.SIGTERM, lambda sig, frame: sys.exit(EXIT_SIGTERM))
    _update_checker.start()
    try:
        cli(standalone_mode=False)
    except click.exceptions.Exit as e:
        raise SystemExit(e.exit_code)
    except (KeyboardInterrupt, click.Abort):
        raise SystemExit(EXIT_SIGINT)
    except SystemExit:
        raise
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        raise SystemExit(EXIT_GENERAL)
    finally:
        _update_checker.notify_if_outdated()


if __name__ == "__main__":
    main()
