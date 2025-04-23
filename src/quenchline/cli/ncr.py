"""Nonconformance commands."""

from __future__ import annotations

import click

from ..loads.disposition import Disposition
from ..nonconformance.record import NcrSubject, Nonconformance
from ..nonconformance.register import NcrRegister, ageing_summary, register_table
from ..report.table import Align, Column, Table, render_kv
from .context import Context, parse_day


@click.group("ncr")
def ncr_group() -> None:
    """Raise, disposition and close nonconformance reports."""


@ncr_group.command("raise")
@click.option("--subject", type=click.Choice([s.value for s in NcrSubject]), required=True)
@click.option("--reference", required=True, help="the lot, furnace or instrument")
@click.option("--summary", required=True)
@click.option("--number", default=None, help="override the generated number")
@click.option("--on", "raised_on", default=None, help="date raised")
@click.pass_obj
def raise_report(
    context: Context,
    subject: str,
    reference: str,
    summary: str,
    number: str | None,
    raised_on: str | None,
) -> None:
    """Raise a nonconformance report."""
    shop = context.shop()
    day = parse_day(raised_on, context.today)
    report = Nonconformance(
        number=number or shop.reports.next_number(day.year),
        subject=NcrSubject(subject),
        reference=reference,
        raised_on=day,
        summary=summary,
    )
    shop.reports.insert(report)
    click.echo(f"raised {report}")


@ncr_group.command("window")
@click.argument("number")
@click.option("--from", "start", required=True, help="first date in doubt")
@click.option("--to", "end", required=True, help="last date in doubt")
@click.pass_obj
def window(context: Context, number: str, start: str, end: str) -> None:
    """Record what an equipment report throws into doubt."""
    shop = context.shop()
    report = shop.reports.get(number).with_suspect_window(
        parse_day(start, context.today), parse_day(end, context.today)
    )
    shop.reports.save(report)
    caught = shop.loads_in_doubt(report)
    click.echo(f"{report.number} covers {len(caught)} load(s)")
    for record in caught:
        click.echo(f"  {record.lot} on {record.furnace} finished {record.finished_at}")


@ncr_group.command("disposition")
@click.argument("number")
@click.option(
    "--as", "disposition", type=click.Choice([d.value for d in Disposition]), required=True
)
@click.option("--on", "given_on", default=None)
@click.pass_obj
def disposition(context: Context, number: str, disposition: str, given_on: str | None) -> None:
    """Give a report its disposition."""
    shop = context.shop()
    report = shop.reports.get(number).disposition_as(
        Disposition(disposition), parse_day(given_on, context.today)
    )
    shop.reports.save(report)
    click.echo(f"{report.number} dispositioned {disposition}")


@ncr_group.command("action")
@click.argument("number")
@click.option("--note", required=True, help="what was actually done")
@click.option("--on", "done_on", default=None)
@click.pass_obj
def action(context: Context, number: str, note: str, done_on: str | None) -> None:
    """Record that the disposition was carried out."""
    shop = context.shop()
    report = shop.reports.get(number).action(parse_day(done_on, context.today), note)
    shop.reports.save(report)
    click.echo(f"{report.number} actioned")


@ncr_group.command("close")
@click.argument("number")
@click.option("--on", "closed_on", default=None)
@click.pass_obj
def close(context: Context, number: str, closed_on: str | None) -> None:
    """Close a report that has been actioned."""
    shop = context.shop()
    report = shop.reports.get(number).close(parse_day(closed_on, context.today))
    shop.reports.save(report)
    click.echo(f"{report.number} closed")


@ncr_group.command("list")
@click.option("--open", "open_only", is_flag=True, help="only reports still open")
@click.pass_obj
def list_reports(context: Context, open_only: bool) -> None:
    """Print the nonconformance register."""
    shop = context.shop()
    register = NcrRegister()
    reports = shop.reports.open_reports() if open_only else shop.reports.all()
    for report in reports:
        register.raise_report(report)
    click.echo(ageing_summary(register, context.today))
    click.echo("")
    click.echo(register_table(register, context.today).render())


@ncr_group.command("in-doubt")
@click.pass_obj
def in_doubt(context: Context) -> None:
    """Every open report with a window, and the loads it catches."""
    shop = context.shop()
    caught = shop.all_loads_in_doubt()
    if not caught:
        click.echo("no open report throws any load into doubt")
        return
    table = Table(
        columns=[Column("report"), Column("loads", align=Align.RIGHT), Column("lots")],
        title="work in doubt",
    )
    for number, records in sorted(caught.items()):
        table.add(number, len(records), ", ".join(str(r.lot) for r in records) or None)
    click.echo(table.render())


@ncr_group.command("show")
@click.argument("number")
@click.pass_obj
def show(context: Context, number: str) -> None:
    """Print one report."""
    report = context.shop().reports.get(number)
    click.echo(
        render_kv(
            [
                ("number", report.number),
                ("subject", report.subject.value),
                ("reference", report.reference),
                ("raised", report.raised_on.isoformat()),
                ("age", report.age(context.today)),
                ("stage", report.stage.value),
                (
                    "disposition",
                    report.disposition.value if report.disposition else None,
                ),
                (
                    "in doubt from",
                    report.suspect_from.isoformat() if report.suspect_from else None,
                ),
                ("in doubt to", report.suspect_to.isoformat() if report.suspect_to else None),
                ("summary", report.summary),
            ],
            title="nonconformance",
        )
    )
