"""Load commands."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click

from ..errors import ValidationError
from ..identity import FurnaceTag, LotNumber, SensorTag, WorkOrder
from ..ingest.pipeline import import_text
from ..ingest.profiles import ProfileLibrary
from ..ingest.quarantine import ImportLog
from ..loads.deviation import evaluate
from ..loads.disposition import Policy, decide
from ..loads.record import Load, LoadState, PartLine
from ..loads.reporting import (
    channel_table,
    deviation_table,
    load_header,
    parts_table,
    run_summary,
    segment_table,
)
from ..loads.segment import segment
from ..measure import Mass, MassUnit
from ..report.table import Align, Column, Table
from .context import Context


@click.group("load")
def load_group() -> None:
    """Plan, run and disposition loads."""


@load_group.command("plan")
@click.argument("lot")
@click.option("--work-order", required=True)
@click.option("--furnace", required=True)
@click.option("--recipe", required=True, help="recipe code")
@click.option("--revision", required=True, help="recipe revision")
@click.option("--weight", default=None, help="load weight, such as 1450lb")
@click.option(
    "--part",
    "parts",
    multiple=True,
    help="part:quantity[:material] triple, repeatable",
)
@click.pass_obj
def plan(
    context: Context,
    lot: str,
    work_order: str,
    furnace: str,
    recipe: str,
    revision: str,
    weight: str | None,
    parts: tuple[str, ...],
) -> None:
    """Book a load onto a furnace."""
    record = Load(
        lot=LotNumber.parse(lot),
        work_order=WorkOrder.parse(work_order),
        furnace=FurnaceTag.parse(furnace),
        recipe_code=recipe,
        recipe_revision=revision,
        parts=tuple(_part(text) for text in parts),
        weight=(
            Mass.parse(weight, default_unit=MassUnit.POUND) if weight is not None else None
        ),
    )
    context.shop().loads.insert(record)
    click.echo(f"planned {record}")


@load_group.command("charge")
@click.argument("lot")
@click.option("--at", "at_text", default=None, help="time charged, ISO format")
@click.option("--sensor", "sensors", multiple=True, help="load sensor tag, repeatable")
@click.pass_obj
def charge(context: Context, lot: str, at_text: str | None, sensors: tuple[str, ...]) -> None:
    """Move a planned load into the furnace."""
    shop = context.shop()
    record = shop.loads.get(lot)
    moved = record.charge(
        _moment(at_text, context),
        tuple(SensorTag.parse(tag) for tag in sensors),
    )
    shop.loads.save(moved)
    click.echo(f"{moved.lot} charged with {len(moved.load_sensors)} load sensor(s)")


@load_group.command("start")
@click.argument("lot")
@click.option("--at", "at_text", default=None, help="time started, ISO format")
@click.pass_obj
def start(context: Context, lot: str, at_text: str | None) -> None:
    """Start the cycle."""
    shop = context.shop()
    moved = shop.loads.get(lot).start(_moment(at_text, context))
    shop.loads.save(moved)
    click.echo(f"{moved.lot} running")


@load_group.command("finish")
@click.argument("lot")
@click.option("--at", "at_text", default=None, help="time finished, ISO format")
@click.pass_obj
def finish(context: Context, lot: str, at_text: str | None) -> None:
    """Mark the cycle finished. The trace is attached separately."""
    shop = context.shop()
    moved = shop.loads.get(lot).finish(_moment(at_text, context))
    shop.loads.save(moved)
    click.echo(f"{moved.lot} complete")


@load_group.command("attach")
@click.argument("lot")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--profile", "profile_name", required=True, help="mapping profile name")
@click.option("--tolerance", type=float, default=0.02)
@click.pass_obj
def attach(context: Context, lot: str, path: Path, profile_name: str, tolerance: float) -> None:
    """Read a logger file and hang it on a load."""
    shop = context.shop()
    record = shop.loads.get(lot)
    started = record.started_at or datetime.combine(context.today, datetime.min.time())
    result = import_text(
        str(path.resolve()),
        path.read_text(),
        profile_name,
        started,
        ProfileLibrary.with_built_ins(),
        ImportLog(),
        tolerance=tolerance,
    )
    if result.trace is None:
        raise ValidationError(
            f"{path.name} produced no usable trace: {result.detail or result.outcome.value}",
            field="path",
        )
    already = shop.loads.with_trace_digest(result.digest)
    others = [item for item in already if str(item.lot) != str(record.lot)]
    if others:
        raise ValidationError(f"that file is already on load {others[0].lot}", field="path")
    shop.loads.save(
        record.attach(result.trace, digest=result.digest).with_profile(profile_name)
    )
    click.echo(
        f"{record.lot} carries {path.name}, "
        f"{result.quarantine.accepted} row(s) over {len(result.trace.channels)} channel(s)"
    )


@load_group.command("hold")
@click.argument("lot")
@click.option("--reason", required=True)
@click.pass_obj
def hold(context: Context, lot: str, reason: str) -> None:
    """Put a load on hold."""
    shop = context.shop()
    moved = shop.loads.get(lot).hold(reason)
    shop.loads.save(moved)
    shop.audit.record("held", "load", str(moved.lot), detail=reason)
    click.echo(f"{moved.lot} held: {reason}")


@load_group.command("reject")
@click.argument("lot")
@click.option("--reason", required=True)
@click.pass_obj
def reject(context: Context, lot: str, reason: str) -> None:
    """Reject a load."""
    shop = context.shop()
    moved = shop.loads.get(lot).reject(reason)
    shop.loads.save(moved)
    shop.audit.record("rejected", "load", str(moved.lot), detail=reason)
    click.echo(f"{moved.lot} rejected: {reason}")


@load_group.command("list")
@click.option(
    "--state",
    type=click.Choice([s.value for s in LoadState]),
    default=None,
    help="only loads in one state",
)
@click.option("--furnace", default=None, help="only loads on one furnace")
@click.pass_obj
def list_loads(context: Context, state: str | None, furnace: str | None) -> None:
    """Print the load register."""
    shop = context.shop()
    if furnace is not None:
        records = shop.loads.on_furnace(furnace)
    elif state is not None:
        records = shop.loads.in_state(LoadState(state))
    else:
        records = shop.loads.all()
    table = Table(
        columns=[
            Column("lot"),
            Column("work order"),
            Column("furnace"),
            Column("recipe"),
            Column("pieces", align=Align.RIGHT),
            Column("state"),
            Column("finished"),
        ],
        title="loads",
    )
    for record in records:
        table.add(
            str(record.lot),
            str(record.work_order),
            str(record.furnace),
            record.recipe,
            record.piece_count,
            record.state.value,
            record.finished_at.date().isoformat() if record.finished_at else None,
        )
    click.echo(table.render())


@load_group.command("floor")
@click.pass_obj
def floor(context: Context) -> None:
    """What is in a furnace right now."""
    records = context.shop().on_the_floor()
    if not records:
        click.echo("nothing on the floor")
        return
    for record in records:
        click.echo(f"{record.lot} {record.state.value} on {record.furnace}")


@load_group.command("evaluate")
@click.argument("lot")
@click.option(
    "--revision", default=None, help="grade against a revision other than the run one"
)
@click.option("--rework-limit", type=int, default=2)
@click.option("--reworks", type=int, default=0, help="how many times this lot has been rerun")
@click.option("--no-concession", is_flag=True, help="the order forbids concessions")
@click.pass_obj
def evaluate_load(
    context: Context,
    lot: str,
    revision: str | None,
    rework_limit: int,
    reworks: int,
    no_concession: bool,
) -> None:
    """Grade a load's trace against the cycle it claims to have run."""
    shop = context.shop()
    record = shop.loads.get(lot)
    if not record.trace_source:
        raise ValidationError(f"{record.lot} has no logger file attached", field="trace")
    recipe = shop.recipes.get(record.recipe_code, revision or record.recipe_revision).recipe

    path = Path(record.trace_source)
    if not path.exists():
        raise ValidationError(
            f"the logger file for {record.lot} is no longer at {path}", field="trace"
        )
    result = import_text(
        str(path),
        path.read_text(),
        record.trace_profile or "eurotherm 6100",
        record.started_at or datetime.combine(context.today, datetime.min.time()),
        ProfileLibrary.with_built_ins(),
        ImportLog(),
        tolerance=1.0,
    )
    trace = result.trace
    if trace is None:
        raise ValidationError(f"{path} no longer reads as a trace", field="trace")

    segments = segment(recipe, trace)
    findings = evaluate(segments, trace, load_sensors_expected=recipe.load_sensors)
    decision = decide(
        findings,
        Policy(
            allow_concession=not no_concession,
            rework_limit=rework_limit,
            reworks_so_far=reworks,
        ),
    )

    click.echo(run_summary(record, findings, decision))
    click.echo("")
    click.echo(segment_table(segments).render())
    if findings:
        click.echo("")
        click.echo(deviation_table(findings).render())
    click.echo("")
    click.echo(channel_table(trace).render())
    if not decision.ships:
        raise ValidationError(str(decision), field="load")


@load_group.command("certify")
@click.argument("lot")
@click.pass_obj
def certify(context: Context, lot: str) -> None:
    """Certify a complete load."""
    shop = context.shop()
    moved = shop.loads.get(lot).certify()
    shop.loads.save(moved)
    shop.audit.record("certified", "load", str(moved.lot), detail=moved.recipe)
    click.echo(f"{moved.lot} certified")


@load_group.command("show")
@click.argument("lot")
@click.pass_obj
def show(context: Context, lot: str) -> None:
    """Print one load."""
    record = context.shop().loads.get(lot)
    click.echo(load_header(record))
    click.echo("")
    click.echo(parts_table(record).render())


def _part(text: str) -> PartLine:
    pieces = text.split(":")
    if len(pieces) < 2:
        raise click.BadParameter(f"{text!r} is not a part:quantity pair")
    try:
        quantity = int(pieces[1])
    except ValueError:
        raise click.BadParameter(f"{pieces[1]!r} is not a quantity") from None
    material = pieces[2] if len(pieces) > 2 else ""
    return PartLine(pieces[0], quantity, material)


def _moment(text: str | None, context: Context) -> datetime:
    if text is None:
        return datetime.combine(context.today, datetime.min.time())
    try:
        return datetime.fromisoformat(text.strip())
    except ValueError:
        raise ValidationError(f"{text!r} is not a time", field="at") from None
