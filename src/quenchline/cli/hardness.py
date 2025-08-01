"""Hardness commands."""

from __future__ import annotations

import click

from ..errors import ValidationError
from ..hardness.sampling import Specification, judge, sample_size
from ..hardness.scales import Hardness, HardnessScale, convert
from ..report.certificate import hardness_table
from ..report.table import render_kv


@click.group("hardness")
def hardness_group() -> None:
    """Convert hardness readings and judge a lot against a specification."""


@hardness_group.command("convert")
@click.argument("reading")
@click.option("--to", "scale", required=True, help="the scale to convert onto")
def convert_reading(reading: str, scale: str) -> None:
    """Convert one steel hardness reading onto another scale."""
    source = Hardness.parse(reading)
    target = HardnessScale.parse(scale)
    converted = convert(source, target)
    click.echo(f"{source.format(1)} is about {converted.format(1)}")


@hardness_group.command("sample")
@click.option("--lot-size", type=int, required=True, help="how many pieces are in the lot")
def sample(lot_size: int) -> None:
    """How many pieces to test out of a lot."""
    required = sample_size(lot_size)
    click.echo(
        render_kv(
            [
                ("lot size", lot_size),
                ("first sample", required),
                ("retest sample", required * 2),
            ],
            title="hardness sampling",
        )
    )


@hardness_group.command("judge")
@click.option("--lot-size", type=int, required=True)
@click.option("--scale", required=True, help="the specification scale")
@click.option("--minimum", type=float, default=None)
@click.option("--maximum", type=float, default=None)
@click.option("--max-spread", type=float, default=None, help="widest allowed spread")
@click.option("--allow-converted", is_flag=True, help="the spec permits converted readings")
@click.option("--retest", is_flag=True, help="this is the retest, not the first sample")
@click.option(
    "--reading",
    "readings",
    multiple=True,
    required=True,
    help="a reading such as 42.5, repeatable",
)
@click.option(
    "--converted",
    "converted",
    multiple=True,
    help="a reading that came from a conversion, repeatable",
)
def judge_lot(
    lot_size: int,
    scale: str,
    minimum: float | None,
    maximum: float | None,
    max_spread: float | None,
    allow_converted: bool,
    retest: bool,
    readings: tuple[str, ...],
    converted: tuple[str, ...],
) -> None:
    """Judge a set of hardness readings against a specification."""
    target = HardnessScale.parse(scale)
    specification = Specification(
        scale=target,
        minimum=minimum,
        maximum=maximum,
        allow_converted=allow_converted,
        maximum_spread=max_spread,
    )
    measured = [Hardness(_number(text), target) for text in readings]
    measured.extend(Hardness(_number(text), target, converted=True) for text in converted)

    result = judge(measured, specification, lot_size, is_retest=retest)
    click.echo(
        render_kv(
            [
                ("specification", str(specification)),
                ("lot size", lot_size),
                ("readings", len(result.readings)),
                ("required sample", result.required_sample),
                ("average", round(result.average, 1) if result.average else None),
                ("failures", len(result.failures)),
                ("verdict", result.verdict.value),
                ("reason", result.reason),
            ],
            title="hardness result",
        )
    )
    click.echo("")
    click.echo(hardness_table(result, specification).render())
    if not result.is_accepted:
        raise ValidationError(str(result), field="hardness")


def _number(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise click.BadParameter(f"{text!r} is not a hardness reading") from None
