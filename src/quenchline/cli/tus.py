"""Uniformity survey commands."""

from __future__ import annotations

from pathlib import Path

import click

from ..errors import ValidationError
from ..furnaces.zones import survey_sensor_count
from ..identity import FurnaceTag
from ..ingest.survey import load_layout, read_setpoint
from ..report.table import render_kv
from ..temperature import Scale, Temperature
from ..tus.dropout import find_dropouts
from ..tus.evaluate import evaluate
from ..tus.reporting import (
    dropout_note,
    excursion_table,
    setpoint_table,
    survey_header,
)
from ..tus.survey import Survey
from .context import Context, parse_day


@click.group("survey")
def survey_group() -> None:
    """Read and judge temperature uniformity surveys."""


@survey_group.command("layout")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
def show_layout(path: Path) -> None:
    """Print a survey layout file."""
    layout = load_layout(path)
    click.echo(
        render_kv(
            [
                ("layout", layout.name),
                ("time column", layout.time_heading),
                ("time unit", layout.time_unit.value),
                ("scale", layout.scale.symbol),
                ("positions", len(layout.columns)),
                ("corners", layout.corner_count),
                ("centre", "yes" if any(c.is_centre for c in layout.columns) else "no"),
            ],
            title="survey layout",
        )
    )
    for column in layout.columns:
        click.echo(f"  {column.sensor} {column.location} ({column.heading})")


@survey_group.command("evaluate")
@click.argument("furnace")
@click.option("--number", required=True, help="the survey number")
@click.option("--zone", required=True, help="the work zone surveyed")
@click.option(
    "--layout",
    "layout_path",
    type=click.Path(exists=True, path_type=Path),
    required=True,
)
@click.option(
    "--reading",
    "readings",
    multiple=True,
    required=True,
    help="setpoint=path pair, repeatable",
)
@click.option("--on", "performed", default=None, help="date the survey ran")
@click.option("--soak", type=float, default=30.0, help="minimum soak minutes")
@click.pass_obj
def evaluate_survey(
    context: Context,
    furnace: str,
    number: str,
    zone: str,
    layout_path: Path,
    readings: tuple[str, ...],
    performed: str | None,
    soak: float,
) -> None:
    """Judge a survey against the furnace it was run on."""
    from ..timespan import minutes

    shop = context.shop()
    record = shop.furnaces.get(furnace)
    work_zone = record.zone(zone)
    layout = load_layout(layout_path)

    setpoints = []
    for text in readings:
        value, _, path_text = text.partition("=")
        if not path_text:
            raise ValidationError(f"{text!r} is not a setpoint=path pair", field="reading")
        setpoint = Temperature.parse(value, default_scale=Scale.FAHRENHEIT)
        result = read_setpoint(Path(path_text).read_text(), layout, setpoint)
        setpoints.append(result.or_raise())

    survey = Survey(
        number=number,
        furnace=FurnaceTag.parse(furnace),
        zone=zone,
        performed=parse_day(performed, context.today),
        points=layout.points,
        setpoints=tuple(setpoints),
    )

    needed = survey_sensor_count(work_zone.volume, record.furnace_class)
    judged = evaluate(
        survey,
        record.furnace_class,
        minimum_soak=minutes(soak),
        required_sensors=needed,
    )

    click.echo(survey_header(judged))
    click.echo("")
    click.echo(f"positions required for {work_zone}: {needed}")
    click.echo("")
    click.echo(setpoint_table(judged).render())

    excursions = excursion_table(judged)
    if not excursions.is_empty:
        click.echo("")
        click.echo(excursions.render())

    for data in survey.setpoints:
        report = find_dropouts(survey, data)
        if report.dropouts or report.never_read:
            click.echo("")
            click.echo(f"at {data.setpoint.format()}")
            click.echo(dropout_note(report))

    if judged.is_pass:
        low = min(survey.temperatures, key=lambda t: t.degf)
        high = max(survey.temperatures, key=lambda t: t.degf)
        click.echo("")
        click.echo(f"passed, qualifies {record.tag} from {low.format()} to {high.format()}")
    else:
        raise ValidationError(
            f"survey {number} failed at "
            + ", ".join(s.setpoint.format() for s in judged.failed_setpoints),
            field="survey",
        )
