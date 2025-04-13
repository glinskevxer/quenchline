"""Thermocouple commands."""

from __future__ import annotations

from datetime import date

import click

from ..identity import require_sensor_tag
from ..report.table import render_kv
from ..sensors.calibration import Certificate, Convention
from ..sensors.record import Construction, SensorRole, SensorStatus, Thermocouple
from ..sensors.register import SensorRegister, calibration_interval
from ..sensors.reporting import eligibility_table, register_summary, register_table
from ..sensors.types import ThermocoupleType, ToleranceClass, initial_tolerance
from ..sensors.usage import UsageEvent, assess
from ..temperature import Scale, Temperature
from ..timespan import Duration
from .context import Context, parse_day


@click.group("sensor")
def sensor_group() -> None:
    """Add, calibrate and check thermocouples."""


@sensor_group.command("add")
@click.argument("tag")
@click.option("--type", "kind", required=True, help="thermocouple type letter")
@click.option(
    "--construction",
    type=click.Choice([c.value for c in Construction]),
    default=Construction.NONEXPENDABLE.value,
)
@click.option("--role", type=click.Choice([r.value for r in SensorRole]), required=True)
@click.option(
    "--grade", type=click.Choice([g.value for g in ToleranceClass]), default="standard"
)
@click.pass_obj
def add(
    context: Context, tag: str, kind: str, construction: str, role: str, grade: str
) -> None:
    """Add a thermocouple to the register."""
    couple = Thermocouple(
        tag=require_sensor_tag(tag),
        kind=ThermocoupleType.parse(kind),
        construction=Construction(construction),
        role=SensorRole(role),
        grade=ToleranceClass(grade),
    )
    context.shop().sensors.insert(couple)
    click.echo(f"added {couple}")


@sensor_group.command("calibrate")
@click.argument("tag")
@click.option("--number", required=True, help="certificate number")
@click.option("--issued", required=True, help="issue date, YYYY-MM-DD")
@click.option(
    "--point",
    "points",
    multiple=True,
    required=True,
    help="nominal:correction pair in degF, repeatable",
)
@click.option(
    "--convention",
    type=click.Choice([c.value for c in Convention]),
    required=True,
    help="whether the numbers are corrections or deviations",
)
@click.option("--laboratory", default="")
@click.pass_obj
def calibrate(
    context: Context,
    tag: str,
    number: str,
    issued: str,
    points: tuple[str, ...],
    convention: str,
    laboratory: str,
) -> None:
    """Attach a calibration certificate to a thermocouple."""
    shop = context.shop()
    couple = shop.sensors.get(tag)
    readings = [_point(text) for text in points]
    certificate = Certificate.of(
        number,
        parse_day(issued, context.today),
        readings,
        convention=Convention(convention),
        laboratory=laboratory,
    )
    updated = couple.with_certificate(certificate)
    shop.sensors.save(updated)
    expires = certificate.expires(calibration_interval(updated))
    click.echo(f"{couple.tag} calibrated on {certificate.number}, due {expires.isoformat()}")


@sensor_group.command("use")
@click.argument("tag")
@click.option("--on", "used_on", required=True, help="date of the run")
@click.option("--peak", required=True, help="hottest reading, such as 1550F")
@click.option("--hours", type=float, required=True, help="time at temperature")
@click.option("--reference", default="", help="the load or survey it was used on")
@click.pass_obj
def record_use(
    context: Context, tag: str, used_on: str, peak: str, hours: float, reference: str
) -> None:
    """Book a run against a thermocouple's life."""
    shop = context.shop()
    couple = shop.sensors.get(tag)
    shop.sensors.record_use(
        couple.tag,
        UsageEvent(
            parse_day(used_on, context.today),
            Temperature.parse(peak, default_scale=Scale.FAHRENHEIT),
            Duration.of(hours=hours),
            couple.role,
            reference,
        ),
    )
    life = assess(
        couple.kind, couple.construction, couple.role, shop.sensors.ledger(couple.tag)
    )
    click.echo(f"{couple.tag}: {life.reason}")


@sensor_group.command("list")
@click.pass_obj
def list_sensors(context: Context) -> None:
    """Print the thermocouple register."""
    register = _register(context)
    click.echo(register_summary(register, context.today))
    click.echo("")
    click.echo(register_table(register, context.today).render())


@sensor_group.command("eligible")
@click.option("--role", type=click.Choice([r.value for r in SensorRole]), required=True)
@click.option("--at", "at_text", required=True, help="the working temperature")
@click.pass_obj
def eligible(context: Context, role: str, at_text: str) -> None:
    """Which couples may take one job today, and why the rest may not."""
    at = Temperature.parse(at_text, default_scale=Scale.FAHRENHEIT)
    table = eligibility_table(_register(context), SensorRole(role), at, context.today)
    click.echo(table.render())


@sensor_group.command("show")
@click.argument("tag")
@click.pass_obj
def show(context: Context, tag: str) -> None:
    """Print one thermocouple, its life and its tolerance."""
    shop = context.shop()
    couple = shop.sensors.get(tag)
    ledger = shop.sensors.ledger(couple.tag)
    life = assess(couple.kind, couple.construction, couple.role, ledger)
    hottest = ledger.hottest()
    rows: list[tuple[str, object]] = [
        ("tag", str(couple.tag)),
        ("type", couple.kind.value),
        ("construction", couple.construction.value),
        ("role", couple.role.value),
        ("grade", couple.grade.value),
        ("status", couple.status.value),
        ("uses", life.uses),
        ("life", life.reason),
        ("hottest run", hottest.format() if hottest is not None else None),
        (
            "certificate",
            couple.certificate.number if couple.certificate is not None else None,
        ),
    ]
    if couple.kind.covers(Temperature.fahrenheit(1550)):
        rows.append(
            (
                "tolerance at 1550 F",
                initial_tolerance(
                    couple.kind, Temperature.fahrenheit(1550), couple.grade
                ).format(),
            )
        )
    click.echo(render_kv(rows, title=f"thermocouple {couple.tag}"))


@sensor_group.command("scrap")
@click.argument("tag")
@click.option("--reason", required=True)
@click.pass_obj
def scrap(context: Context, tag: str, reason: str) -> None:
    """Take a thermocouple out of service for good."""
    shop = context.shop()
    couple = shop.sensors.get(tag)
    shop.sensors.save(couple.scrap(reason))
    click.echo(f"{couple.tag} scrapped: {reason}")


def _point(text: str) -> tuple[float, float]:
    nominal, _, correction = text.partition(":")
    try:
        return (float(nominal), float(correction))
    except ValueError:
        raise click.BadParameter(f"{text!r} is not a nominal:correction pair") from None


def _register(context: Context) -> SensorRegister:
    register = SensorRegister()
    shop = context.shop()
    for couple in shop.sensors.all():
        register.add(couple)
        register.ledgers[str(couple.tag)] = shop.sensors.ledger(couple.tag)
    return register


def _usable(couple: Thermocouple) -> bool:
    return couple.status is not SensorStatus.SCRAPPED


def next_due(couple: Thermocouple) -> date | None:
    if couple.certificate is None:
        return None
    return couple.certificate.expires(calibration_interval(couple))
