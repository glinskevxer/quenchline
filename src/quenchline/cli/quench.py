"""Quench bath commands."""

from __future__ import annotations

import click

from ..calendar_rules import Interval
from ..errors import ValidationError
from ..measure import Mass, MassUnit
from ..quench.bath import Bath, readiness
from ..quench.media import Agitation, Medium, MediumKind
from ..report.table import Align, Column, Table, render_kv
from ..temperature import Scale, Temperature, TemperatureDelta
from ..tolerance import Band
from .context import Context, parse_day


@click.group("bath")
def bath_group() -> None:
    """Register quench baths and check they are fit to take a load."""


@bath_group.command("add")
@click.argument("identifier")
@click.option("--medium", required=True, help="the medium's trade name")
@click.option("--kind", type=click.Choice([k.value for k in MediumKind]), required=True)
@click.option("--setpoint", required=True, help="the bath operating temperature")
@click.option("--band", type=float, required=True, help="plus or minus, degF")
@click.option("--gallons", type=float, required=True)
@click.option(
    "--agitation",
    type=click.Choice([a.name.lower() for a in Agitation]),
    default="moderate",
    help="the agitation the medium needs",
)
@click.option("--concentration-low", type=float, default=None)
@click.option("--concentration-high", type=float, default=None)
@click.option("--melting-point", default=None, help="for a salt bath")
@click.option("--check-days", type=int, default=7, help="how often it is checked")
@click.pass_obj
def add(
    context: Context,
    identifier: str,
    medium: str,
    kind: str,
    setpoint: str,
    band: float,
    gallons: float,
    agitation: str,
    concentration_low: float | None,
    concentration_high: float | None,
    melting_point: str | None,
    check_days: int,
) -> None:
    """Add a quench bath to the register."""
    if band <= 0:
        raise ValidationError("the band must be positive", field="band")
    medium_kind = MediumKind(kind)
    built = Medium(
        name=medium,
        kind=medium_kind,
        operating=Band.symmetric(
            Temperature.parse(setpoint, default_scale=Scale.FAHRENHEIT),
            TemperatureDelta(band, Scale.FAHRENHEIT),
        ),
        minimum_agitation=Agitation[agitation.upper()],
        concentration_low=concentration_low,
        concentration_high=concentration_high,
        melting_point=(
            Temperature.parse(melting_point, default_scale=Scale.FAHRENHEIT)
            if melting_point
            else None
        ),
    )
    bath = Bath(
        identifier=identifier,
        medium=built,
        gallons=gallons,
        temperature=built.operating.setpoint,
        agitation=built.minimum_agitation,
        concentration=(concentration_low if medium_kind.has_concentration else None),
        check_interval=Interval.days(check_days),
    )
    context.shop().baths.insert(bath)
    click.echo(f"added {bath}, capacity {bath.capacity()}")


@bath_group.command("check")
@click.argument("identifier")
@click.option("--temperature", required=True, help="what the bath measured at")
@click.option(
    "--agitation", type=click.Choice([a.name.lower() for a in Agitation]), default=None
)
@click.option("--concentration", type=float, default=None)
@click.option("--on", "checked_on", default=None)
@click.pass_obj
def check(
    context: Context,
    identifier: str,
    temperature: str,
    agitation: str | None,
    concentration: float | None,
    checked_on: str | None,
) -> None:
    """Record a bath check."""
    shop = context.shop()
    bath = shop.baths.get(identifier)
    updated = bath.measured(
        parse_day(checked_on, context.today),
        Temperature.parse(temperature, default_scale=Scale.FAHRENHEIT),
        concentration=concentration,
        agitation=Agitation[agitation.upper()] if agitation else None,
    )
    shop.baths.save(updated)
    due = updated.check_due()
    click.echo(
        f"{updated.identifier} checked at {updated.temperature.format()}, "
        f"next due {due.isoformat() if due else 'unknown'}"
    )


@bath_group.command("ready")
@click.argument("identifier")
@click.option("--weight", required=True, help="the load weight, such as 1450lb")
@click.option("--grace", type=int, default=0)
@click.pass_obj
def ready(context: Context, identifier: str, weight: str, grace: int) -> None:
    """Whether a bath may take one load right now."""
    bath = context.shop().baths.get(identifier)
    mass = Mass.parse(weight, default_unit=MassUnit.POUND)
    result = readiness(bath, mass, context.today, grace=grace)
    click.echo(
        render_kv(
            [
                ("bath", bath.identifier),
                ("medium", str(bath.medium)),
                ("temperature", bath.temperature.format()),
                ("operating band", bath.medium.operating.format()),
                ("load", str(mass)),
                ("ratio", f"{bath.ratio_for(mass):.2f} lb per gallon"),
                ("capacity", str(bath.capacity())),
                ("verdict", "ready" if result.is_ready else "not ready"),
            ],
            title="bath readiness",
        )
    )
    if not result.is_ready:
        for detail in result.detail:
            click.echo(f"  {detail}")
        raise ValidationError(str(result), field="bath")


@bath_group.command("list")
@click.pass_obj
def list_baths(context: Context) -> None:
    """Print the bath register."""
    table = Table(
        columns=[
            Column("bath"),
            Column("medium"),
            Column("kind"),
            Column("gallons", align=Align.RIGHT, places=0),
            Column("temperature", align=Align.RIGHT, places=0),
            Column("agitation"),
            Column("percent", align=Align.RIGHT, places=1),
            Column("checked"),
            Column("due"),
            Column("state"),
        ],
        title="quench baths",
    )
    for bath in context.shop().baths.all():
        due = bath.check_due()
        table.add(
            bath.identifier,
            bath.medium.name,
            bath.medium.kind.value,
            bath.gallons,
            bath.temperature.degf,
            bath.agitation.name.lower(),
            bath.concentration,
            bath.last_checked.isoformat() if bath.last_checked else None,
            due.isoformat() if due else None,
            "in service" if bath.in_service else "out of service",
        )
    click.echo(table.render())
