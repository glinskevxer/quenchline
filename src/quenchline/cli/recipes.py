"""Recipe commands."""

from __future__ import annotations

import click

from ..errors import ValidationError
from ..recipes.cycle import Recipe
from ..recipes.register import RecipeRevision, RecipeState
from ..recipes.steps import RampLimit, Step, StepKind
from ..report.certificate import cycle_table
from ..report.table import Align, Column, Table, render_kv
from ..temperature import Scale, Temperature, TemperatureDelta
from ..timespan import Duration
from .context import Context, parse_day


@click.group("recipe")
def recipe_group() -> None:
    """Write, release and read thermal cycles."""


@recipe_group.command("add")
@click.argument("code")
@click.option("--revision", required=True)
@click.option("--title", required=True)
@click.option("--material", default="")
@click.option("--load-sensors", type=int, default=0)
@click.option("--author", default="")
@click.option(
    "--step",
    "steps",
    multiple=True,
    required=True,
    help="a step written as kind:name:key=value pairs, repeatable",
)
@click.pass_obj
def add(
    context: Context,
    code: str,
    revision: str,
    title: str,
    material: str,
    load_sensors: int,
    author: str,
    steps: tuple[str, ...],
) -> None:
    """Write a new recipe revision as a draft."""
    recipe = Recipe(
        code=code,
        revision=revision,
        title=title,
        steps=tuple(_step(text) for text in steps),
        load_sensors=load_sensors,
        material=material,
    )
    context.shop().recipes.insert(RecipeRevision(recipe, author=author))
    click.echo(f"added {recipe.identifier} as a draft with {len(recipe.steps)} step(s)")


@recipe_group.command("release")
@click.argument("code")
@click.option("--revision", required=True)
@click.option("--on", "released_on", default=None)
@click.pass_obj
def release(context: Context, code: str, revision: str, released_on: str | None) -> None:
    """Release a draft, superseding whatever was released before it."""
    shop = context.shop()
    register = shop.recipes.register()
    previous = register.released(code)
    register.release(code, revision, parse_day(released_on, context.today))
    shop.recipes.save_register(register)
    message = f"{code} rev {revision} released"
    if previous is not None:
        message += f", rev {previous.revision} superseded"
    click.echo(message)


@recipe_group.command("withdraw")
@click.argument("code")
@click.option("--revision", required=True)
@click.pass_obj
def withdraw(context: Context, code: str, revision: str) -> None:
    """Withdraw a revision so nothing can be run to it."""
    shop = context.shop()
    register = shop.recipes.register()
    register.withdraw(code, revision)
    shop.recipes.save_register(register)
    click.echo(f"{code} rev {revision} withdrawn")


@recipe_group.command("list")
@click.option("--code", default=None, help="only one recipe code")
@click.pass_obj
def list_recipes(context: Context, code: str | None) -> None:
    """Print every revision on file."""
    shop = context.shop()
    revisions = shop.recipes.revisions_of(code) if code else shop.recipes.all()
    table = Table(
        columns=[
            Column("code"),
            Column("rev", align=Align.CENTRE),
            Column("title"),
            Column("material"),
            Column("steps", align=Align.RIGHT),
            Column("state"),
            Column("released"),
        ],
        title="recipes",
    )
    for revision in revisions:
        table.add(
            revision.code,
            revision.revision,
            revision.recipe.title,
            revision.recipe.material or None,
            len(revision.recipe.steps),
            revision.state.value,
            revision.released_on.isoformat() if revision.released_on else None,
        )
    click.echo(table.render())


@recipe_group.command("show")
@click.argument("code")
@click.option("--revision", default=None, help="defaults to the released one")
@click.pass_obj
def show(context: Context, code: str, revision: str | None) -> None:
    """Print one recipe and the cycle it writes."""
    shop = context.shop()
    if revision is None:
        current = shop.recipes.released(code)
        if current is None:
            raise ValidationError(f"no released revision of {code}", field="code")
    else:
        current = shop.recipes.get(code, revision)
    recipe = current.recipe
    peak = recipe.peak()
    click.echo(
        render_kv(
            [
                ("recipe", recipe.identifier),
                ("title", recipe.title),
                ("material", recipe.material or None),
                ("state", current.state.value),
                ("steps", len(recipe.steps)),
                ("graded soaks", len(recipe.graded_steps)),
                ("load sensors", recipe.load_sensors),
                ("peak", peak.format() if peak is not None else None),
                ("minimum soak time", recipe.minimum_time().format()),
                ("has a quench", "yes" if recipe.has_quench else "no"),
            ],
            title="recipe",
        )
    )
    click.echo("")
    click.echo(cycle_table(recipe).render())


@recipe_group.command("runnable")
@click.pass_obj
def runnable(context: Context) -> None:
    """Which recipes a load may be booked to today."""
    released = [
        revision
        for revision in context.shop().recipes.all()
        if revision.state is RecipeState.RELEASED
    ]
    if not released:
        click.echo("nothing is released")
        return
    for revision in released:
        click.echo(f"{revision.recipe.identifier} {revision.recipe.title}")


def _step(text: str) -> Step:
    """Read ``soak:austenitise:setpoint=1550F,band=25,minimum=1h``."""
    parts = text.split(":")
    if len(parts) < 2:
        raise click.BadParameter(f"{text!r} is not a kind:name step")
    kind_text, name = parts[0], parts[1]
    try:
        kind = StepKind(kind_text.strip().lower())
    except ValueError:
        raise click.BadParameter(f"{kind_text!r} is not a step kind") from None

    options = _options(parts[2] if len(parts) > 2 else "")
    setpoint = (
        Temperature.parse(options["setpoint"], default_scale=Scale.FAHRENHEIT)
        if "setpoint" in options
        else None
    )
    tolerance = (
        TemperatureDelta(float(options["band"]), Scale.FAHRENHEIT)
        if "band" in options
        else None
    )
    ramp = None
    if "max_rate" in options or "min_rate" in options:
        ramp = RampLimit(
            float(options["max_rate"]) if "max_rate" in options else None,
            float(options["min_rate"]) if "min_rate" in options else None,
        )
    return Step(
        kind=kind,
        name=name,
        setpoint=setpoint,
        tolerance=tolerance,
        minimum_time=Duration.parse(options["minimum"]) if "minimum" in options else None,
        maximum_time=Duration.parse(options["maximum"]) if "maximum" in options else None,
        ramp=ramp,
        quench_delay=Duration.parse(options["delay"]) if "delay" in options else None,
        medium=options.get("medium", ""),
    )


def _options(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for chunk in text.split(","):
        if not chunk.strip():
            continue
        key, _, value = chunk.partition("=")
        if not value:
            raise click.BadParameter(f"{chunk!r} is not a key=value pair")
        found[key.strip().lower()] = value.strip()
    return found
