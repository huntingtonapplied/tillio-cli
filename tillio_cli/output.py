"""Output formatting helpers for CLI commands."""

from __future__ import annotations

import json
import sys
from typing import Optional

import click
from rich.console import Console


def get_console(ctx: Optional[click.Context] = None) -> Console:
    """Return a rich Console that writes to the current stdout.

    A fresh Console is created each call so it picks up Click's test runner
    redirects and always reflects the current --no-color setting.
    """
    no_color = False
    if ctx:
        no_color = (ctx.obj or {}).get("no_color", False)
    return Console(file=sys.stdout, no_color=no_color, highlight=False)


def get_format(ctx: click.Context) -> str:
    """Get the output format from the Click context."""
    return (ctx.obj or {}).get("output", "table")


def is_json(ctx: click.Context) -> bool:
    """Check if JSON output is requested."""
    return get_format(ctx) == "json"


def is_yaml(ctx: click.Context) -> bool:
    """Check if YAML output is requested."""
    return get_format(ctx) == "yaml"


def is_structured(ctx: click.Context) -> bool:
    """Check if any structured output (json or yaml) is requested."""
    return get_format(ctx) in ("json", "yaml")


def print_json(data):
    """Print data as formatted JSON."""
    click.echo(json.dumps(data, indent=2, default=str))


def print_yaml(data):
    """Print data as YAML."""
    try:
        import yaml
        click.echo(yaml.safe_dump(data, default_flow_style=False, sort_keys=False))
    except ImportError:
        # yaml is already a dependency (used by api.py for config)
        click.echo(json.dumps(data, indent=2, default=str))


def print_structured(ctx: click.Context, data):
    """Print data in the requested structured format (json or yaml)."""
    fmt = get_format(ctx)
    if fmt == "yaml":
        print_yaml(data)
    else:
        print_json(data)
