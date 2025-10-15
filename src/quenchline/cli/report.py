"""Reporting commands."""

from __future__ import annotations

from datetime import date

import click

from ..errors import ValidationError
from ..report.certificate import CertificateHeader, certificate_text
from ..report.compliance import assess, summary_header, summary_table
from ..report.kpi import Period, comparison_table, rollup, rollup_block
from ..report.table import Align, Column, Table, render_kv
from ..schedule.board import Board, board_summary, board_table
from .context import Context, parse_day
from .registers import board as build_board


@click.group("report")
def report_group() -> None:
    """Compliance, performance and schedule reports."""


@report_group.command("schedule")
@click.option("--grace", type=int, default=0, help="days of grace before overdue")
@click.option("--attention", "attention_only", is_flag=True, help="only what is late")
@click.pass_obj
def schedule(context: Context, grace: int, attention_only: bool) -> None:
    """What the shop owes, worst first."""
    board = build_board(context, grace)
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
        build_board(context, grace),
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


@report_group.command("deviations")
@click.option("--furnace", "by_furnace", is_flag=True, help="group by furnace instead")
@click.pass_obj
def deviations(context: Context, by_furnace: bool) -> None:
    """What the shop keeps getting wrong, commonest first."""
    shop = context.shop()
    counts = shop.grading.counts_by_furnace() if by_furnace else shop.grading.counts_by_kind()
    waiting = shop.grading.ungraded()
    click.echo(
        render_kv(
            [
                ("graded runs", shop.grading.count()),
                ("findings", shop.grading.finding_count()),
                ("awaiting grading", len(waiting)),
            ],
            title="deviations",
        )
    )
    if not counts:
        click.echo("")
        click.echo("nothing has been graded yet")
        return
    table = Table(
        columns=[
            Column("furnace" if by_furnace else "deviation"),
            Column("count", align=Align.RIGHT),
        ],
        title="findings by furnace" if by_furnace else "findings by kind",
    )
    for name, count in counts.items():
        table.add(name, count)
    click.echo("")
    click.echo(table.render())
    if waiting:
        click.echo("")
        click.echo("awaiting grading: " + ", ".join(waiting))


@report_group.command("certificate")
@click.argument("lot")
@click.option("--number", default=None, help="override the generated certificate number")
@click.option("--customer", default="")
@click.option("--customer-order", default="")
@click.option("--specification", default="")
@click.option("--signatory", default="")
@click.pass_obj
def certificate(
    context: Context,
    lot: str,
    number: str | None,
    customer: str,
    customer_order: str,
    specification: str,
    signatory: str,
) -> None:
    """Print the certificate of conformance for a certified load."""
    shop = context.shop()
    record = shop.loads.get(lot)
    recipe = shop.recipes.get(record.recipe_code, record.recipe_revision).recipe
    header = CertificateHeader(
        number=number or _certificate_number(context, record.lot),
        issued_on=context.today,
        shop_name=context.settings.shop_name,
        customer=customer,
        customer_order=customer_order,
        specification=specification,
        signatory=signatory,
    )
    click.echo(certificate_text(header, record, recipe))


def _certificate_number(context: Context, lot: object) -> str:
    """The shop's own certificate numbering, prefix plus the lot it covers."""
    return f"{context.settings.certificate_prefix}-{lot}"


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


def _plus(day: date, days: int) -> date:
    return date.fromordinal(day.toordinal() + days)
