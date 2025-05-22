"""Furnace commands."""

from __future__ import annotations

import click

from ..errors import ValidationError
from ..furnaces.classes import FurnaceClass, InstrumentationType, sat_interval, tus_interval
from ..furnaces.record import Furnace
from ..furnaces.register import FurnaceRegister
from ..furnaces.reporting import capability_summary, deficiency_table, furnace_table
from ..furnaces.zones import QualifiedRange, WorkZone, survey_sensor_count
from ..identity import FurnaceTag, require_sensor_tag
from ..measure import Volume
from ..report.table import render_kv
from ..sensors.record import SensorRole
from ..temperature import Scale, Temperature
from .context import Context


@click.group("furnace")
def furnace_group() -> None:
    """Add, list and inspect furnaces."""


@furnace_group.command("add")
@click.argument("tag")
@click.option("--class", "furnace_class", required=True, help="furnace class, 1 to 6")
@click.option("--instrumentation", required=True, help="instrumentation type, A to E")
@click.option("--description", default="", help="free text")
@click.pass_obj
def add(
    context: Context,
    tag: str,
    furnace_class: str,
    instrumentation: str,
    description: str,
) -> None:
    """Add a furnace to the register."""
    furnace = Furnace(
        tag=FurnaceTag.parse(tag),
        furnace_class=FurnaceClass.parse(furnace_class),
        instrumentation=InstrumentationType.parse(instrumentation),
        description=description,
    )
    context.shop().furnaces.insert(furnace)
    click.echo(f"added {furnace}")


@furnace_group.command("zone")
@click.argument("tag")
@click.argument("name")
@click.option("--cubic-feet", type=float, required=True, help="work zone volume")
@click.option("--low", required=True, help="lowest usable temperature, such as 1000F")
@click.option("--high", required=True, help="highest usable temperature")
@click.pass_obj
def add_zone(
    context: Context, tag: str, name: str, cubic_feet: float, low: str, high: str
) -> None:
    """Add a work zone to a furnace."""
    shop = context.shop()
    furnace = shop.furnaces.get(tag)
    zone = WorkZone(
        name,
        Volume(cubic_feet),
        Temperature.parse(low, default_scale=Scale.FAHRENHEIT),
        Temperature.parse(high, default_scale=Scale.FAHRENHEIT),
    )
    shop.furnaces.save(furnace.add_zone(zone))
    needed = survey_sensor_count(zone.volume, furnace.furnace_class)
    click.echo(f"added zone {zone} to {furnace.tag}, survey needs {needed} sensors")


@furnace_group.command("wire")
@click.argument("tag")
@click.argument("sensor")
@click.option("--role", type=click.Choice([r.value for r in SensorRole]), required=True)
@click.pass_obj
def wire(context: Context, tag: str, sensor: str, role: str) -> None:
    """Wire a thermocouple to a furnace."""
    shop = context.shop()
    furnace = shop.furnaces.get(tag)
    sensor_tag = require_sensor_tag(sensor)
    holder = shop.furnaces.wired_to(sensor_tag)
    if holder is not None and holder != str(furnace.tag):
        raise ValidationError(f"{sensor_tag} is already wired to {holder}", field="sensor")
    updated = furnace.wire(SensorRole(role), sensor_tag)
    shop.furnaces.save(updated)
    shortfall = updated.deficiencies()
    click.echo(
        f"{sensor_tag} wired to {furnace.tag} as {role}, "
        + ("no shortfall" if not shortfall else ", ".join(d.value for d in shortfall))
    )


@furnace_group.command("unwire")
@click.argument("tag")
@click.argument("sensor")
@click.pass_obj
def unwire(context: Context, tag: str, sensor: str) -> None:
    """Take a thermocouple off a furnace."""
    shop = context.shop()
    furnace = shop.furnaces.get(tag)
    sensor_tag = require_sensor_tag(sensor)
    shop.furnaces.save(furnace.unwire(sensor_tag))
    click.echo(f"{sensor_tag} removed from {furnace.tag}")


@furnace_group.command("qualify")
@click.argument("tag")
@click.option("--low", required=True, help="lowest surveyed temperature")
@click.option("--high", required=True, help="highest surveyed temperature")
@click.pass_obj
def qualify(context: Context, tag: str, low: str, high: str) -> None:
    """Set the qualified operating range from a survey."""
    shop = context.shop()
    furnace = shop.furnaces.get(tag)
    qualified = QualifiedRange(
        Temperature.parse(low, default_scale=Scale.FAHRENHEIT),
        Temperature.parse(high, default_scale=Scale.FAHRENHEIT),
    )
    shop.furnaces.save(furnace.qualify(qualified))
    click.echo(f"{furnace.tag} qualified {qualified}")


@furnace_group.command("list")
@click.pass_obj
def list_furnaces(context: Context) -> None:
    """Print the furnace register."""
    click.echo(furnace_table(_register(context)).render())


@furnace_group.command("show")
@click.argument("tag")
@click.pass_obj
def show(context: Context, tag: str) -> None:
    """Print one furnace and the intervals it earns."""
    furnace = context.shop().furnaces.get(tag)
    rows: list[tuple[str, object]] = [
        ("furnace", str(furnace.tag)),
        ("class", furnace.furnace_class.value),
        ("uniformity band", furnace.tolerance.format()),
        ("instrumentation", furnace.instrumentation.value),
        ("status", furnace.status.value),
        ("qualified", str(furnace.qualified) if furnace.qualified else None),
        ("sat interval", str(sat_interval(furnace.instrumentation))),
        (
            "survey interval",
            str(tus_interval(furnace.furnace_class, furnace.instrumentation)),
        ),
        ("work zones", len(furnace.zones)),
        ("sensors wired", len(furnace.sensors)),
        ("deficiencies", ", ".join(d.value for d in furnace.deficiencies()) or None),
    ]
    click.echo(render_kv(rows, title=f"furnace {furnace.tag}"))


@furnace_group.command("capability")
@click.option("--at", "at_text", required=True, help="the temperature a job needs")
@click.pass_obj
def capability(context: Context, at_text: str) -> None:
    """Which furnaces could take a job at one temperature."""
    at = Temperature.parse(at_text, default_scale=Scale.FAHRENHEIT)
    register = _register(context)
    click.echo(capability_summary(register, at))
    able = register.able_to_run(at)
    if not able:
        raise ValidationError(f"no furnace is qualified at {at.format()}", field="at")
    click.echo("")
    click.echo("\n".join(str(f.tag) for f in able))


@furnace_group.command("deficiencies")
@click.pass_obj
def deficiencies(context: Context) -> None:
    """Furnaces that do not carry what their type claims."""
    click.echo(deficiency_table(_register(context)).render())


def _register(context: Context) -> FurnaceRegister:
    register = FurnaceRegister()
    for furnace in context.shop().furnaces.all():
        register.add(furnace)
    return register
