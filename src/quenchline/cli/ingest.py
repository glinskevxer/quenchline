"""Datalogger import commands."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click

from ..errors import ValidationError
from ..ingest.pipeline import import_folder, import_text
from ..ingest.profiles import ProfileLibrary
from ..ingest.quarantine import ImportLog, Quarantine
from ..report.table import Align, Column, Table, render_kv
from .context import Context


@click.group("ingest")
def ingest_group() -> None:
    """Read vendor datalogger files."""


@ingest_group.command("profiles")
@click.option(
    "--file",
    "profile_file",
    type=click.Path(path_type=Path),
    default=None,
    help="a toml file of extra profiles",
)
def profiles(profile_file: Path | None) -> None:
    """List the mapping profiles this install can read files with."""
    library = _library(profile_file)
    table = Table(
        columns=[
            Column("profile"),
            Column("time column"),
            Column("unit"),
            Column("scale", align=Align.CENTRE),
            Column("delimiter", align=Align.CENTRE),
            Column("channels"),
        ],
        title="mapping profiles",
    )
    for name in library.names():
        profile = library.get(name)
        table.add(
            profile.name,
            profile.time_heading,
            profile.time_unit.value,
            profile.scale.symbol,
            "tab" if profile.delimiter == "\t" else profile.delimiter,
            ", ".join(profile.keys),
        )
    click.echo(table.render())


@ingest_group.command("check")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--profile", "profile_name", required=True)
@click.option(
    "--file",
    "profile_file",
    type=click.Path(path_type=Path),
    default=None,
    help="a toml file of extra profiles",
)
@click.pass_obj
def check_file(
    context: Context, path: Path, profile_name: str, profile_file: Path | None
) -> None:
    """Read a file without importing it and say what it holds."""
    library = _library(profile_file)
    started = datetime.combine(context.today, datetime.min.time())
    result = import_text(
        path.name,
        path.read_text(),
        profile_name,
        started,
        library,
        ImportLog(),
        tolerance=1.0,
    )
    click.echo(str(result))
    click.echo("")
    click.echo(_quarantine_block(result.quarantine))
    if result.trace is not None:
        click.echo("")
        click.echo(_channel_table(result.trace).render())


@ingest_group.command("run")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--profile", "profile_name", required=True)
@click.option("--pattern", default="*.csv", help="which files to read")
@click.option("--tolerance", type=float, default=0.02, help="allowed share of bad rows")
@click.option(
    "--file",
    "profile_file",
    type=click.Path(path_type=Path),
    default=None,
)
@click.pass_obj
def run_folder(
    context: Context,
    folder: Path,
    profile_name: str,
    pattern: str,
    tolerance: float,
    profile_file: Path | None,
) -> None:
    """Read every matching file in a folder."""
    if not 0 <= tolerance <= 1:
        raise ValidationError("tolerance is a fraction", field="tolerance")
    library = _library(profile_file)
    started = datetime.combine(context.today, datetime.min.time())
    run = import_folder(
        folder,
        profile_name,
        started,
        library,
        ImportLog(),
        pattern=pattern,
        tolerance=tolerance,
    )
    table = Table(
        columns=[
            Column("file"),
            Column("outcome"),
            Column("rows", align=Align.RIGHT),
            Column("rejected", align=Align.RIGHT),
            Column("detail"),
        ],
        title=f"import from {folder}",
    )
    for result in run.files:
        table.add(
            result.name,
            result.outcome.value,
            result.quarantine.seen,
            result.quarantine.rejected,
            result.detail or None,
        )
    click.echo(table.render())
    click.echo("")
    click.echo(f"{len(run.imported)} imported, {len(run.rejected)} rejected")


def _library(profile_file: Path | None) -> ProfileLibrary:
    library = ProfileLibrary.with_built_ins()
    if profile_file is not None:
        library.load_file(profile_file)
    return library


def _quarantine_block(quarantine: Quarantine) -> str:
    counts = quarantine.by_reason()
    rows: list[tuple[str, object]] = [
        ("rows seen", quarantine.seen),
        ("accepted", quarantine.accepted),
        ("rejected", quarantine.rejected),
    ]
    rows.extend((reason.value, count) for reason, count in counts.items() if count)
    return render_kv(rows, title="rows")


def _channel_table(trace: object) -> Table:
    table = Table(
        columns=[
            Column("channel"),
            Column("role"),
            Column("readings", align=Align.RIGHT),
            Column("peak", align=Align.RIGHT, places=0),
            Column("gaps", align=Align.RIGHT),
        ],
        title="channels",
    )
    for channel in trace.channels:  # type: ignore[attr-defined]
        peak = channel.peak()
        table.add(
            channel.key,
            channel.role.value,
            len(channel.readings),
            peak.degf if peak is not None else None,
            len(channel.gaps()),
        )
    return table
