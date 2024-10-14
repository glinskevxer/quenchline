"""The thermal cycle: an ordered list of steps with rules between them.

A step on its own can be perfectly legal and still be wrong where it sits. Those
are the rules that live here rather than in :mod:`quenchline.recipes.steps`,
because none of them can be checked without knowing what came before:

* a **temper cannot come before a quench**. Tempering is what you do to
  martensite you have already made, and a cycle that tempers first and quenches
  afterwards has the metallurgy backwards.
* a cycle **cannot open with a quench or a temper**, for the same reason.
* a cycle **cannot end on a ramp**, because a ramp is a way of getting
  somewhere and a cycle that ends on one never says what it was getting to.
* **step names are unique**, because a deviation report has to name the step it
  is about and "soak" three times is not a name.

The cycle also carries what the *load* has to do rather than what the furnace
has to do: how many load sensors it needs, and where they go.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..errors import NotFoundError, ValidationError
from ..temperature import Temperature
from ..timespan import Duration, total
from .steps import Step, StepKind


@dataclass(frozen=True)
class Recipe:
    """One written thermal cycle."""

    code: str
    revision: str
    title: str
    steps: tuple[Step, ...]
    load_sensors: int = 0
    material: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValidationError("a recipe needs a code", field="code")
        if not self.revision.strip():
            raise ValidationError("a recipe needs a revision", field="revision")
        if not self.steps:
            raise ValidationError("a recipe needs at least one step", field="steps")
        if self.load_sensors < 0:
            raise ValidationError("load sensor count cannot be negative", field="load_sensors")

        names = [s.name for s in self.steps]
        if len(set(names)) != len(names):
            raise ValidationError("two steps share a name", field="steps")

        first = self.steps[0]
        if first.kind in {StepKind.QUENCH, StepKind.TEMPER}:
            raise ValidationError(
                f"a cycle cannot open with a {first.kind.value} step", field="steps"
            )
        if self.steps[-1].kind is StepKind.RAMP:
            raise ValidationError("a cycle cannot end on a ramp", field="steps")

        seen_quench = False
        for step in self.steps:
            if step.kind is StepKind.QUENCH:
                seen_quench = True
            elif step.kind is StepKind.TEMPER and not seen_quench:
                raise ValidationError(
                    f"step {step.name!r} tempers before anything has been quenched",
                    field="steps",
                )

    @property
    def identifier(self) -> str:
        return f"{self.code} rev {self.revision}"

    def step(self, name: str) -> Step:
        for candidate in self.steps:
            if candidate.name == name:
                return candidate
        raise NotFoundError("recipe step", name)

    def index_of(self, name: str) -> int:
        for index, candidate in enumerate(self.steps):
            if candidate.name == name:
                return index
        raise NotFoundError("recipe step", name)

    def of_kind(self, kind: StepKind) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if s.kind is kind)

    @property
    def graded_steps(self) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if s.grades_temperature)

    @property
    def has_quench(self) -> bool:
        return any(s.kind is StepKind.QUENCH for s in self.steps)

    @property
    def setpoints(self) -> tuple[Temperature, ...]:
        return tuple(s.setpoint for s in self.steps if s.setpoint is not None)

    def peak(self) -> Temperature | None:
        points = self.setpoints
        if not points:
            return None
        return max(points, key=lambda t: t.degf)

    def minimum_time(self) -> Duration:
        """The soak time alone. Ramps and quenches take as long as they take."""
        return total([s.minimum_time for s in self.steps if s.minimum_time is not None])

    def requires_load_sensors(self) -> bool:
        return self.load_sensors > 0

    def fits(self, low: Temperature, high: Temperature) -> bool:
        """Whether every set point in the cycle falls inside a qualified range."""
        return all(low.degf <= point.degf <= high.degf for point in self.setpoints)

    def revised(self, revision: str, steps: tuple[Step, ...] | None = None) -> Recipe:
        """A new revision of the same recipe."""
        if revision.strip() == self.revision:
            raise ValidationError("a revision must change the revision", field="revision")
        return replace(self, revision=revision.strip(), steps=steps or self.steps)

    def __str__(self) -> str:
        return f"{self.identifier} {self.title}"
