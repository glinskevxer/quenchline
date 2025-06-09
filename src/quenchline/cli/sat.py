"""System accuracy test commands."""

from __future__ import annotations

import click

from ..errors import ValidationError
from ..identity import FurnaceTag, InstrumentTag, SensorTag
from ..sat.model import SatMethod, SatReading, SatTest
from ..sat.reporting import due_board, failure_notice, history_summary, result_table
from ..sat.schedule import SatHistory
from ..temperature import Scale, Temperature, TemperatureDelta
from .context import Context, parse_day


@click.group("sat")
def sat_group() -> None:
    """Record and judge system accuracy tests."""


@sat_group.command("record")
@click.argument("furnace")
@click.option("--number", required=True, help="the test number")
@click.option("--setpoint", required=True, help="the temperature it was run at")
@click.option("--system", type=float, required=True, help="what the furnace displayed")
@click.option("--probe", type=float, required=True, help="what the test instrument read")
@click.option("--system-sensor", default=None, help="the furnace control couple")
@click.option("--test-sensor", default=None, help="the test couple")
@click.option("--system-instrument", default=None)
@click.option("--test-instrument", default=None)
@click.option(
    "--system-correction", type=float, default=0.0, help="control couple correction, degF"
)
@click.option("--test-correction", type=float, default=0.0, help="test couple correction")
@click.option("--system-instrument-correction", type=float, default=0.0)
@click.option("--test-instrument-correction", type=float, default=0.0)
@click.option(
    "--method", type=click.Choice([m.value for m in SatMethod]), default=SatMethod.PROBE.value
)
@click.option("--raw", is_flag=True, help="corrections were not applied")
@click.option("--on", "performed", default=None, help="date the test was run")
@click.option("--technician", default="")
@click.pass_obj
def record(
    context: Context,
    furnace: str,
    number: str,
    setpoint: str,
    system: float,
    probe: float,
    system_sensor: str | None,
    test_sensor: str | None,
    system_instrument: str | None,
    test_instrument: str | None,
    system_correction: float,
    test_correction: float,
    system_instrument_correction: float,
    test_instrument_correction: float,
    method: str,
    raw: bool,
    performed: str | None,
    technician: str,
) -> None:
    """Record a system accuracy test and say whether it passed."""
    shop = context.shop()
    record_furnace = shop.furnaces.get(furnace)
    test = SatTest(
        number=number,
        furnace=FurnaceTag.parse(furnace),
        performed=parse_day(performed, context.today),
        setpoint=Temperature.parse(setpoint, default_scale=Scale.FAHRENHEIT),
        system=SatReading(
            Temperature.fahrenheit(system),
            TemperatureDelta(system_correction, Scale.FAHRENHEIT),
            TemperatureDelta(system_instrument_correction, Scale.FAHRENHEIT),
            SensorTag.parse(system_sensor) if system_sensor else None,
            InstrumentTag.parse(system_instrument) if system_instrument else None,
        ),
        test=SatReading(
            Temperature.fahrenheit(probe),
            TemperatureDelta(test_correction, Scale.FAHRENHEIT),
            TemperatureDelta(test_instrument_correction, Scale.FAHRENHEIT),
            SensorTag.parse(test_sensor) if test_sensor else None,
            InstrumentTag.parse(test_instrument) if test_instrument else None,
        ),
        method=SatMethod(method),
        technician=technician,
        apply_corrections=not raw,
    )
    history = _history(context, record_furnace.tag)
    judged = history.file(test)
    shop.sat.insert(test)
    click.echo(str(judged))
    for note in judged.notes:
        click.echo(f"  note: {note}")
    if not judged.is_pass:
        click.echo("")
        click.echo(failure_notice(history, judged))
        raise ValidationError(f"{number} failed on {record_furnace.tag}", field="test")


@sat_group.command("history")
@click.argument("furnace")
@click.pass_obj
def history(context: Context, furnace: str) -> None:
    """Every system accuracy test on one furnace."""
    tag = context.shop().furnaces.get(furnace).tag
    record_history = _history(context, tag)
    click.echo(history_summary(record_history, context.today))
    click.echo("")
    click.echo(result_table(record_history).render())


@sat_group.command("due")
@click.option("--grace", type=int, default=0)
@click.pass_obj
def due(context: Context, grace: int) -> None:
    """When every furnace's next test is due."""
    shop = context.shop()
    histories = [_history(context, furnace.tag) for furnace in shop.furnaces.all()]
    if not histories:
        click.echo("no furnaces on the register")
        return
    click.echo(due_board(histories, context.today, grace=grace).render())


def _history(context: Context, furnace: FurnaceTag) -> SatHistory:
    shop = context.shop()
    record = shop.furnaces.get(furnace)
    return shop.sat.history(record.tag, record.furnace_class, record.instrumentation)
