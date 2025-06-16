"""Reporting commands."""

from __future__ import annotations

from datetime import date

import click

from ..errors import ValidationError
from ..report.compliance import assess, summary_header, summary_table
from ..report.kpi import Period, comparison_table, rollup, rollup_block
from ..sat.schedule import SatHistory
from ..schedule.board import Board, board_summary, board_table
from ..sensors.register import SensorRegister
from .context import Context, parse_day


@click.group("report")
def report_group() -> None:
    """Compliance, performance and schedule reports."""


@report_group.command("schedule")
@click.option("--grace", type=int, default=0, help="days of grace before overdue")
@click.option("--attention", "attention_only", is_flag=True, help="only what is late")
@click.pass_obj
def schedule(context: Context, grace: int, attention_only: bool) -> None:
    """What the shop owes, worst first."""
    board = _board(context, grace)
    click.echo(board_summary(board, context.today))
    click.echo("")
    if attention_only:
        board = Board(board.needing_attention())
    click.echo(board_table(board, context.today).render())


@report_group.command("compliance")
@click.option("--grace", type=int, default=0)
@click.option("--ncr-age-limit", type=int, default=90, help="days before a report is stale")
@click.pass_obj
def compliance(context: Context, grace: int, ncr_age_limit: int) -> None:
    """The answers an audit asks for."""
    shop = context.shop()
    summary = assess(
        _board(context, grace),
        shop.reports.all(),
        context.today,
        ncr_age_limit=ncr_age_limit,
    )
    click.echo(summary_header(summary))
    click.echo("")
    click.echo(summary_table(summary).render())


@report_group.command("performance")
@click.option("--from", "start", required=True, help="first day of the period")
@click.option("--to", "end", required=True, help="last day of the period")
@click.option("--against", "previous_start", default=None, help="start of a period to compare")
@click.pass_obj
def performance(context: Context, start: str, end: str, previous_start: str | None) -> None:
    """The four numbers over a period."""
    shop = context.shop()
    period = Period(parse_day(start, context.today), parse_day(end, context.today))
    loads = shop.loads.all()
    current = rollup(loads, period, furnace_count=shop.furnaces.count())
    click.echo(rollup_block(current))
    if previous_start is None:
        return
    span = (period.end - period.start).days
    previous_from = parse_day(previous_start, context.today)
    previous = rollup(
        loads,
        Period(previous_from, _plus(previous_from, span)),
        furnace_count=shop.furnaces.count(),
    )
    click.echo("")
    click.echo(comparison_table(current, previous).render())


@report_group.command("throughput")
@click.option("--from", "start", required=True)
@click.option("--to", "end", required=True)
@click.pass_obj
def throughput(context: Context, start: str, end: str) -> None:
    """Certified loads inside a window."""
    shop = context.shop()
    first = parse_day(start, context.today)
    last = parse_day(end, context.today)
    if last < first:
        raise ValidationError("the period runs backwards", field="to")
    certified = shop.certified_between(first, last)
    click.echo(f"{len(certified)} certified load(s) between {first} and {last}")
    for record in certified:
        click.echo(f"  {record.lot} on {record.furnace} to {record.recipe}")


@report_group.command("open-work")
@click.pass_obj
def open_work(context: Context) -> None:
    """Loads that are not finished with, and reports that are still open."""
    shop = context.shop()
    floor = shop.on_the_floor()
    waiting = shop.awaiting_disposition()
    reports = shop.reports.open_reports()
    click.echo(f"on the floor: {len(floor)}")
    click.echo(f"awaiting disposition: {len(waiting)}")
    click.echo(f"open nonconformances: {len(reports)}")
    for record in floor + waiting:
        click.echo(f"  {record.lot} {record.state.value}")
    for report in reports:
        click.echo(f"  {report.number} {report.stage.value} against {report.reference}")


def _board(context: Context, grace: int) -> Board:
    """Everything due, gathered from the registers that actually hold the dates."""
    shop = context.shop()
    register = SensorRegister()
    for couple in shop.sensors.all():
        register.add(couple)
        register.ledgers[str(couple.tag)] = shop.sensors.ledger(couple.tag)
    return Board.build(
        context.today,
        sensors=register,
        sat=_sat_histories(context),
        grace=grace,
    )


def _sat_histories(context: Context) -> list[SatHistory]:
    """A judged system accuracy history per furnace on the register."""
    shop = context.shop()
    return [
        shop.sat.history(furnace.tag, furnace.furnace_class, furnace.instrumentation)
        for furnace in shop.furnaces.all()
    ]


def _plus(day: date, days: int) -> date:
    return date.fromordinal(day.toordinal() + days)
