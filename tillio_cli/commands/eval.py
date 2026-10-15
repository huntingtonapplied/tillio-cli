"""tillio eval — evaluation command group.

Subcommands:
    tillio eval contribution <id>   — evaluate a contribution by ID
    tillio eval code <paths...>     — score files/directories by content
    tillio eval repo <url>          — evaluate a remote repository

Backward compatibility:
    tillio eval <uuid>              — dispatches to `eval contribution`
"""

import re
import click
from tillio_cli.commands.eval_contribution import contribution
from tillio_cli.commands.eval_code import code
from tillio_cli.commands.eval_repo import repo

# UUID pattern for backward compat detection
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class EvalGroup(click.Group):
    """Custom group that detects bare UUID arguments for backward compat.

    `tillio eval <uuid>` dispatches to `tillio eval contribution <uuid>`
    without requiring the user to type the subcommand name.
    """

    def parse_args(self, ctx, args):
        # If the first arg looks like a UUID and isn't a known subcommand,
        # inject "contribution" before it for backward compat
        if args and _UUID_PATTERN.match(args[0]) and args[0] not in self.commands:
            args = ["contribution"] + args
        return super().parse_args(ctx, args)


@click.group(cls=EvalGroup)
@click.pass_context
def eval(ctx):
    """Evaluate code, repos, or contributions."""
    pass


eval.add_command(contribution)
eval.add_command(code)
eval.add_command(repo)
