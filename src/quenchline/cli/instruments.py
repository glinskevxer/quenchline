"""Instrument commands."""

from __future__ import annotations

import click

from ..calendar_rules import DueRule, Interval
from ..errors import ValidationError
from ..identity import InstrumentTag
from ..instruments.calibration import CalibrationCheck, InstrumentCalibration, suspect_window
from ..instruments.record import Instrument
from ..instruments.types import (
    Accuracy,
    InstrumentClass,
    InstrumentFunction,
    Readout,
    Span,
    permitted_functions,
)
from ..report.table import Align, Column, Table, render_kv
from ..temperature import Scale, Temperature, TemperatureDelta
from .context import Context, parse_day


@click.group("instrument")
def instrument_group() -> None:
    """Register instruments and file their calibrations."""


@instrument_group.command("add")
@click.argument("tag")
@click.option(
    "--function", type=click.Choice([f.value for f in InstrumentFunction]), required=True
)
@click.option("--span-low", default="0F")
@click.option("--span-high", required=True, help="top of the measuring range")
@click.option("--accuracy", type=float, required=True, help="stated accuracy percentage")
@click.option(
    "--basis",
    type=click.Choice([c.value for c in InstrumentClass]),
    default=InstrumentClass.PERCENT_OF_READING.value,
)
@click.option("--floor", type=float, default=0.0, help="accuracy floor in degF")
@click.option("--resolution", type=float, required=True, help="display resolution, degF")
@click.option(
    "--readout", type=click.Choice([r.value for r in Readout]), default=Readout.DIGITAL.value
)
@click.option("--interval-months", type=int, default=6)
@click.option(
    "--due-rule",
    type=click.Choice([r.value for r in DueRule]),
    default=DueRule.ANNIVERSARY.value,
)
@click.option("--make", default="")
@click.option("--model", default="")
@click.option("--serial", default="")
@click.pass_obj
def add(
    context: Context,
    tag: str,
    function: str,
    span_low: str,
    span_high: str,
    accuracy: float,
    basis: str,
    floor: float,
    resolution: float,
    readout: str,
    interval_months: int,
    due_rule: str,
    make: str,
    model: str,
    serial: str,
) -> None:
    """Add an instrument to the register."""
    instrument = Instrument(
        tag=InstrumentTag.parse(tag),
        function=InstrumentFunction(function),
        span=Span(
            Temperature.parse(span_low, default_scale=Scale.FAHRENHEIT),
            Temperature.parse(span_high, default_scale=Scale.FAHRENHEIT),
        ),
        accuracy=Accuracy(accuracy, InstrumentClass(basis), floor),
        resolution=TemperatureDelta(resolution, Scale.FAHRENHEIT),
        readout=Readout(readout),
        interval=Interval.months(interval_months),
        due_rule=DueRule(due_rule),
        make=make,
        model=model,
        serial=serial,
    )
    context.shop().instruments.insert(instrument)
    click.echo(f"added {instrument}")


@instrument_group.command("calibrate")
@click.argument("tag")
@click.option("--number", required=True)
@click.option("--tolerance", type=float, required=True, help="allowed error, degF")
@click.option(
    "--point",
    "points",
    multiple=True,
    required=True,
    help="nominal:as_found[:as_left] in degF, repeatable",
)
@click.option("--on", "performed", default=None)
@click.option("--technician", default="")
@click.option("--standard", default="")
@click.pass_obj
def calibrate(
    context: Context,
    tag: str,
    number: str,
    tolerance: float,
    points: tuple[str, ...],
    performed: str | None,
    technician: str,
    standard: str,
) -> None:
    """File a calibration and say what it invalidates."""
    shop = context.shop()
    instrument = shop.instruments.get(tag)
    calibration = InstrumentCalibration(
        number=number,
        instrument=instrument.tag,
        performed=parse_day(performed, context.today),
        checks=tuple(_check(text) for text in points),
        tolerance=TemperatureDelta(tolerance, Scale.FAHRENHEIT),
        technician=technician,
        standard=standard,
    )
    previous = instrument.latest
    shop.instruments.file(calibration)

    click.echo(f"{number} on {instrument.tag}: {calibration.verdict.value}")
    window = suspect_window(calibration, previous)
    if window is not None:
        click.echo(f"work in doubt from {window[0].isoformat()} to {window[1].isoformat()}")
    if not calibration.verdict.is_usable:
        raise ValidationError(
            f"{instrument.tag} cannot be brought inside tolerance", field="calibration"
        )


@instrument_group.command("list")
@click.pass_obj
def list_instruments(context: Context) -> None:
    """Print the instrument register with its due dates."""
    shop = context.shop()
    table = Table(
        columns=[
            Column("instrument"),
            Column("function"),
            Column("accuracy", align=Align.RIGHT, places=2),
            Column("resolution", align=Align.RIGHT, places=1),
            Column("readout"),
            Column("interval"),
            Column("due"),
            Column("state"),
        ],
        title="instruments",
    )
    for entry in shop.instruments.register().schedule(context.today):
        instrument = entry.instrument
        table.add(
            str(instrument.tag),
            instrument.function.value,
            instrument.accuracy.percent,
            instrument.resolution.degf,
            instrument.readout.value,
            str(instrument.interval),
            entry.due.isoformat() if entry.due else None,
            "overdue" if entry.overdue else "in date",
        )
    click.echo(table.render())


@instrument_group.command("show")
@click.argument("tag")
@click.option("--at", "at_text", default="1550F", help="temperature to judge it at")
@click.pass_obj
def show(context: Context, tag: str, at_text: str) -> None:
    """Print one instrument and what it is good enough for."""
    instrument = context.shop().instruments.get(tag)
    at = Temperature.parse(at_text, default_scale=Scale.FAHRENHEIT)
    allowed = permitted_functions(
        instrument.accuracy, instrument.span, instrument.resolution, instrument.readout, at
    )
    click.echo(
        render_kv(
            [
                ("instrument", str(instrument.tag)),
                ("function", instrument.function.value),
                ("make", f"{instrument.make} {instrument.model}".strip() or None),
                ("serial", instrument.serial or None),
                ("span", f"{instrument.span.low.format()} to {instrument.span.high.format()}"),
                ("error at " + at.format(), instrument.error_at(at).format()),
                ("resolution", instrument.resolution.format()),
                ("calibrations", len(instrument.calibrations)),
                ("state", instrument.calibration_state(context.today)),
                ("good enough for", ", ".join(sorted(f.value for f in allowed)) or "nothing"),
            ],
            title="instrument",
        )
    )


def _check(text: str) -> CalibrationCheck:
    parts = text.split(":")
    if len(parts) < 2:
        raise click.BadParameter(f"{text!r} is not a nominal:as_found reading")
    try:
        nominal = float(parts[0])
        found = float(parts[1])
        left = float(parts[2]) if len(parts) > 2 else None
    except ValueError:
        raise click.BadParameter(f"{text!r} holds something that is not a number") from None
    return CalibrationCheck(
        Temperature.fahrenheit(nominal),
        Temperature.fahrenheit(found),
        Temperature.fahrenheit(left) if left is not None else None,
    )
