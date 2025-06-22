"""Reading and writing recipes and their revisions.

Steps are stored by **position** rather than by name, because the order of a
cycle is the cycle. Two recipes can both have a step called "temper" and a
recipe read back with its steps in alphabetical order is a different instruction
from the one that was written.

The release state lives on the same row as the recipe, so the register can be
rebuilt in one query rather than by walking a separate history table. Only one
revision of a code is ever in the released state, and that is enforced by the
register on the way in rather than by a constraint here, because SQLite cannot
express "at most one row per code with this value" without a trigger.
"""

from __future__ import annotations

from datetime import date

from ..errors import ConflictError, NotFoundError
from ..recipes.cycle import Recipe
from ..recipes.register import RecipeRegister, RecipeRevision, RecipeState
from ..recipes.steps import RampLimit, Step, StepKind
from ..temperature import Scale, Temperature, TemperatureDelta
from ..timespan import Duration
from .database import Database


class RecipeRepository:
    """Every revision of every recipe."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def insert(self, revision: RecipeRevision) -> None:
        if self.exists(revision.code, revision.revision):
            raise ConflictError("recipe revision", f"{revision.code} rev {revision.revision}")
        self.save(revision)

    def save(self, revision: RecipeRevision) -> None:
        recipe = revision.recipe
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO recipe (code, revision, title, material, "
                "load_sensors, state, released_on, superseded_on, author) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    recipe.code,
                    recipe.revision,
                    recipe.title,
                    recipe.material,
                    recipe.load_sensors,
                    revision.state.value,
                    revision.released_on.isoformat() if revision.released_on else None,
                    revision.superseded_on.isoformat() if revision.superseded_on else None,
                    revision.author,
                ),
            )
            connection.execute(
                "DELETE FROM recipe_step WHERE code = ? AND revision = ?",
                (recipe.code, recipe.revision),
            )
            for position, step in enumerate(recipe.steps):
                connection.execute(
                    "INSERT INTO recipe_step (code, revision, position, kind, name, "
                    "setpoint_f, tolerance_f, minimum_seconds, maximum_seconds, "
                    "ramp_maximum, ramp_minimum, quench_delay_seconds, medium) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    _step_row(recipe.code, recipe.revision, position, step),
                )

    def exists(self, code: str, revision: str) -> bool:
        return (
            self.database.one(
                "SELECT code FROM recipe WHERE code = ? AND revision = ?", (code, revision)
            )
            is not None
        )

    def get(self, code: str, revision: str) -> RecipeRevision:
        row = self.database.one(
            "SELECT * FROM recipe WHERE code = ? AND revision = ?", (code, revision)
        )
        if row is None:
            raise NotFoundError("recipe revision", f"{code} rev {revision}")
        return self._build(row)

    def codes(self) -> list[str]:
        rows = self.database.query("SELECT DISTINCT code FROM recipe ORDER BY code")
        return [row["code"] for row in rows]

    def revisions_of(self, code: str) -> list[RecipeRevision]:
        rows = self.database.query(
            "SELECT * FROM recipe WHERE code = ? ORDER BY revision", (code,)
        )
        return [self._build(row) for row in rows]

    def all(self) -> list[RecipeRevision]:
        rows = self.database.query("SELECT * FROM recipe ORDER BY code, revision")
        return [self._build(row) for row in rows]

    def released(self, code: str) -> RecipeRevision | None:
        row = self.database.one(
            "SELECT * FROM recipe WHERE code = ? AND state = ?",
            (code, RecipeState.RELEASED.value),
        )
        return self._build(row) if row is not None else None

    def register(self) -> RecipeRegister:
        """Rebuild the whole register in one pass."""
        register = RecipeRegister()
        for revision in self.all():
            register.revisions[revision.key] = revision
        return register

    def save_register(self, register: RecipeRegister) -> None:
        for revision in register.all():
            self.save(revision)

    def delete(self, code: str, revision: str) -> None:
        if not self.exists(code, revision):
            raise NotFoundError("recipe revision", f"{code} rev {revision}")
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM recipe_step WHERE code = ? AND revision = ?", (code, revision)
            )
            connection.execute(
                "DELETE FROM recipe WHERE code = ? AND revision = ?", (code, revision)
            )

    def count(self) -> int:
        row = self.database.one("SELECT COUNT(*) AS n FROM recipe")
        return int(row["n"]) if row is not None else 0

    def _steps(self, code: str, revision: str) -> tuple[Step, ...]:
        rows = self.database.query(
            "SELECT * FROM recipe_step WHERE code = ? AND revision = ? ORDER BY position",
            (code, revision),
        )
        return tuple(_build_step(dict(row)) for row in rows)

    def _build(self, row: object) -> RecipeRevision:
        mapping = dict(row)  # type: ignore[call-overload]
        recipe = Recipe(
            code=mapping["code"],
            revision=mapping["revision"],
            title=mapping["title"],
            steps=self._steps(mapping["code"], mapping["revision"]),
            load_sensors=mapping["load_sensors"],
            material=mapping["material"],
        )
        return RecipeRevision(
            recipe=recipe,
            state=RecipeState(mapping["state"]),
            released_on=(
                date.fromisoformat(mapping["released_on"]) if mapping["released_on"] else None
            ),
            superseded_on=(
                date.fromisoformat(mapping["superseded_on"])
                if mapping["superseded_on"]
                else None
            ),
            author=mapping["author"],
        )


def _step_row(code: str, revision: str, position: int, step: Step) -> tuple[object, ...]:
    ramp = step.ramp
    return (
        code,
        revision,
        position,
        step.kind.value,
        step.name,
        step.setpoint.degf if step.setpoint is not None else None,
        step.tolerance.degf if step.tolerance is not None else None,
        step.minimum_time.seconds if step.minimum_time is not None else None,
        step.maximum_time.seconds if step.maximum_time is not None else None,
        ramp.maximum if ramp is not None else None,
        ramp.minimum if ramp is not None else None,
        step.quench_delay.seconds if step.quench_delay is not None else None,
        step.medium,
    )


def _build_step(row: dict[str, object]) -> Step:
    ramp = None
    if row["ramp_maximum"] is not None or row["ramp_minimum"] is not None:
        ramp = RampLimit(
            float(row["ramp_maximum"]) if row["ramp_maximum"] is not None else None,  # type: ignore[arg-type]
            float(row["ramp_minimum"]) if row["ramp_minimum"] is not None else None,  # type: ignore[arg-type]
        )
    return Step(
        kind=StepKind(row["kind"]),
        name=str(row["name"]),
        setpoint=(
            Temperature.fahrenheit(float(row["setpoint_f"]))  # type: ignore[arg-type]
            if row["setpoint_f"] is not None
            else None
        ),
        tolerance=(
            TemperatureDelta(float(row["tolerance_f"]), Scale.FAHRENHEIT)  # type: ignore[arg-type]
            if row["tolerance_f"] is not None
            else None
        ),
        minimum_time=(
            Duration(float(row["minimum_seconds"]))  # type: ignore[arg-type]
            if row["minimum_seconds"] is not None
            else None
        ),
        maximum_time=(
            Duration(float(row["maximum_seconds"]))  # type: ignore[arg-type]
            if row["maximum_seconds"] is not None
            else None
        ),
        ramp=ramp,
        quench_delay=(
            Duration(float(row["quench_delay_seconds"]))  # type: ignore[arg-type]
            if row["quench_delay_seconds"] is not None
            else None
        ),
        medium=str(row["medium"]),
    )
