"""The root command.

Errors are caught here and printed as one line rather than as a traceback,
because the people running this are heat treaters and a traceback tells them
nothing they can act on. The exit code says which kind of thing went wrong, so a
nightly script can tell a missing record from a bad argument.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import click

from .. import __version__
from ..errors import ConflictError, NotFoundError, QuenchlineError, StateError, ValidationError
from .analysis import analysis_group
from .context import Context, parse_day
from .db import db_group
from .furnaces import furnace_group
from .ingest import ingest_group
from .loads import load_group
from .ncr import ncr_group
from .report import report_group
from .sensors import sensor_group

EXIT_VALIDATION = 2
EXIT_NOT_FOUND = 3
EXIT_CONFLICT = 4
EXIT_STATE = 5
EXIT_OTHER = 1


def exit_code_for(error: QuenchlineError) -> int:
    if isinstance(error, NotFoundError):
        return EXIT_NOT_FOUND
    if isinstance(error, ConflictError):
        return EXIT_CONFLICT
    if isinstance(error, StateError):
        return EXIT_STATE
    if isinstance(error, ValidationError):
        return EXIT_VALIDATION
    return EXIT_OTHER


class QuenchlineGroup(click.Group):
    """A group that turns a domain error into a one line message and an exit code."""

    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        except QuenchlineError as error:
            click.echo(f"error: {error}", err=True)
            ctx.exit(exit_code_for(error))


@click.group(cls=QuenchlineGroup)
@click.version_option(version=__version__, prog_name="quenchline")
@click.option(
    "--settings",
    "settings_path",
    type=click.Path(path_type=Path),
    default=None,
    help="path to a quenchline.toml",
)
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=None,
    help="path to the shop database",
)
@click.option(
    "--today",
    default=None,
    help="the date to report as of, YYYY-MM-DD",
)
@click.pass_context
def main(
    ctx: click.Context,
    settings_path: Path | None,
    database: Path | None,
    today: str | None,
) -> None:
    """Pyrometry and process records for a heat treating shop."""
    context = Context.build(
        settings_path=settings_path,
        database=database,
        today=parse_day(today, date.today()),
    )
    ctx.obj = context
    ctx.call_on_close(context.close)


main.add_command(analysis_group)
main.add_command(db_group)
main.add_command(furnace_group)
main.add_command(ingest_group)
main.add_command(load_group)
main.add_command(ncr_group)
main.add_command(report_group)
main.add_command(sensor_group)


@main.command("settings")
@click.pass_obj
def show_settings(context: Context) -> None:
    """Print the settings this run resolved."""
    from ..report.table import render_kv

    values = context.settings.as_mapping()
    rows: list[tuple[str, object]] = [
        ("today", context.today.isoformat()),
        ("database in use", str(context.database_path)),
    ]
    rows.extend(sorted((key, _render(value)) for key, value in values.items()))
    click.echo(render_kv(rows, title="settings"))


def _render(value: object) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def run(argv: list[str] | None = None) -> int:
    """Entry point that turns a domain error into an exit code."""
    try:
        returned = main.main(args=argv, standalone_mode=False)
    except QuenchlineError as error:
        click.echo(f"error: {error}", err=True)
        return exit_code_for(error)
    except click.exceptions.Exit as exit_signal:
        return int(exit_signal.exit_code)
    except click.ClickException as error:
        error.show()
        return error.exit_code
    except click.exceptions.Abort:
        click.echo("aborted", err=True)
        return EXIT_OTHER
    return int(returned) if isinstance(returned, int) else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run())
