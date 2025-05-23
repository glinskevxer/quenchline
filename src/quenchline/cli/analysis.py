"""Analysis commands."""

from __future__ import annotations

import click

from ..analysis.selection import Job, rank
from ..analysis.workload import measure
from ..errors import ValidationError
from ..measure import Volume
from ..report.table import Align, Column, Table, render_kv
from ..temperature import Scale, Temperature, TemperatureDelta
from .context import Context, parse_day


@click.group("analyse")
def analysis_group() -> None:
    """Pick a furnace and look at where the work went."""


@analysis_group.command("choose")
@click.option("--at", "at_text", required=True, help="the job temperature")
@click.option("--band", type=float, required=True, help="the band the job needs, degF")
@click.option("--cubic-feet", type=float, default=None, help="how much room the load needs")
@click.option("--all", "show_all", is_flag=True, help="show the refusals as well")
@click.pass_obj
def choose_furnace(
    context: Context,
    at_text: str,
    band: float,
    cubic_feet: float | None,
    show_all: bool,
) -> None:
    """Rank the furnaces for one job."""
    if band <= 0:
        raise ValidationError("the band must be positive", field="band")
    job = Job(
        Temperature.parse(at_text, default_scale=Scale.FAHRENHEIT),
        TemperatureDelta(band, Scale.FAHRENHEIT),
        Volume(cubic_feet) if cubic_feet is not None else None,
    )
    candidates = rank(context.shop().furnaces.all(), job)
    if not show_all:
        candidates = [candidate for candidate in candidates if candidate.is_able]
    if not candidates:
        raise ValidationError(
            f"no furnace can hold {job.band.format()} at {job.at.format()}", field="job"
        )

    table = Table(
        columns=[
            Column("furnace"),
            Column("class", align=Align.RIGHT),
            Column("band", align=Align.RIGHT, places=0),
            Column("slack", align=Align.RIGHT, places=2),
            Column("spare cuft", align=Align.RIGHT, places=1),
            Column("verdict"),
            Column("why not"),
        ],
        title=f"furnaces for {job.band.format()} at {job.at.format()}",
    )
    for candidate in candidates:
        table.add(
            candidate.tag,
            candidate.furnace.furnace_class.value,
            candidate.furnace.tolerance.degf,
            candidate.slack,
            candidate.spare_volume,
            "able" if candidate.is_able else "refused",
            ", ".join(r.value for r in candidate.refusals) or None,
        )
    click.echo(table.render())


@analysis_group.command("workload")
@click.option("--from", "start", required=True, help="first day of the period")
@click.option("--to", "end", required=True, help="last day of the period")
@click.pass_obj
def workload(context: Context, start: str, end: str) -> None:
    """How much of a period each furnace was occupied for."""
    first = parse_day(start, context.today)
    last = parse_day(end, context.today)
    result = measure(context.shop().loads.all(), first, last)
    busiest = result.busiest
    click.echo(
        render_kv(
            [
                ("period", f"{first.isoformat()} to {last.isoformat()}"),
                ("period hours", f"{result.period_hours:.0f}"),
                ("loads", result.total_loads),
                ("furnaces used", len(result.furnaces)),
                ("busiest", busiest.furnace if busiest is not None else None),
                ("overbooked", len(result.overbooked())),
            ],
            title="workload",
        )
    )
    if not result.furnaces:
        return
    table = Table(
        columns=[
            Column("furnace"),
            Column("loads", align=Align.RIGHT),
            Column("pieces", align=Align.RIGHT),
            Column("occupied"),
            Column("occupancy", align=Align.RIGHT, places=2),
            Column("certified", align=Align.RIGHT),
            Column("rejected", align=Align.RIGHT),
        ],
        title="furnace workload",
    )
    for entry in result.furnaces:
        table.add(
            entry.furnace,
            entry.loads,
            entry.pieces,
            entry.occupied.format(),
            entry.occupancy(result.period_hours),
            entry.certified,
            entry.rejected,
        )
    click.echo("")
    click.echo(table.render())
