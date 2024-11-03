"""Turning findings into a decision about the metal.

The deviation engine says what happened. This says what to do about it, and the
mapping is not one to one, because two things decide it that have nothing to do
with the trace:

**Whether the fault can be undone.** A short soak can be undone: put the load
back in and run it again. Grain growth from an over temperature excursion cannot
be, and no amount of rerunning fixes it, so the same severity leads to rework in
one case and scrap in the other.

**What the customer's specification allows.** A shop working to a specification
that forbids concessions cannot accept a major finding, however sensible it
looks. That is a property of the order, not of the load, and it is passed in.

There is also a limit on rerunning. Every trip through the cycle is more time at
temperature, and a part that has been round three times is a different part
metallurgically from the one on the drawing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import ValidationError
from .deviation import Deviation, DeviationKind, Severity, worst


class Disposition(Enum):
    ACCEPT = "accept"
    ACCEPT_AS_IS = "accept_as_is"
    REWORK = "rework"
    REVIEW = "review"
    SCRAP = "scrap"

    @property
    def ships(self) -> bool:
        return self in {Disposition.ACCEPT, Disposition.ACCEPT_AS_IS}

    @property
    def needs_a_signature(self) -> bool:
        return self in {Disposition.ACCEPT_AS_IS, Disposition.SCRAP}


IRREVERSIBLE = frozenset(
    {
        DeviationKind.OVER_TEMPERATURE,
    }
)

REWORKABLE = frozenset(
    {
        DeviationKind.SHORT_SOAK,
        DeviationKind.STEP_NOT_REACHED,
        DeviationKind.RATE_TOO_SLOW,
        DeviationKind.RATE_TOO_FAST,
    }
)


@dataclass(frozen=True)
class Policy:
    """What the order and the material allow."""

    allow_concession: bool = True
    rework_limit: int = 2
    reworks_so_far: int = 0
    material_allows_rerun: bool = True

    def __post_init__(self) -> None:
        if self.rework_limit < 0:
            raise ValidationError("rework limit cannot be negative", field="rework_limit")
        if self.reworks_so_far < 0:
            raise ValidationError("rework count cannot be negative", field="reworks_so_far")

    @property
    def may_rework(self) -> bool:
        return self.material_allows_rerun and self.reworks_so_far < self.rework_limit


DEFAULT_POLICY = Policy()


@dataclass(frozen=True)
class Decision:
    """What to do with the load, and why."""

    disposition: Disposition
    reason: str
    driving: Deviation | None = None

    @property
    def ships(self) -> bool:
        return self.disposition.ships

    def __str__(self) -> str:
        return f"{self.disposition.value}: {self.reason}"


def decide(findings: tuple[Deviation, ...], policy: Policy = DEFAULT_POLICY) -> Decision:
    """The disposition one run earns."""
    if not findings:
        return Decision(Disposition.ACCEPT, "no deviations")

    irreversible = [f for f in findings if f.kind in IRREVERSIBLE]
    if irreversible:
        driving = irreversible[0]
        return Decision(
            Disposition.SCRAP,
            f"{driving.kind.value} cannot be undone by rerunning",
            driving,
        )

    highest = worst(findings)
    if highest is Severity.MINOR:
        return Decision(
            Disposition.ACCEPT,
            f"{len(findings)} minor deviation(s), none blocking",
            findings[0],
        )

    blocking = [f for f in findings if f.severity.blocks_certification]
    driving = max(blocking, key=lambda f: f.severity.rank)

    if driving.kind in REWORKABLE and policy.may_rework:
        return Decision(
            Disposition.REWORK,
            f"{driving.kind.value} can be put right by running the cycle again",
            driving,
        )

    if highest is Severity.MAJOR and policy.allow_concession:
        return Decision(
            Disposition.ACCEPT_AS_IS,
            f"{driving.kind.value} accepted under concession",
            driving,
        )

    return Decision(
        Disposition.REVIEW,
        f"{driving.kind.value} needs a metallurgical review",
        driving,
    )


def summarise(findings: tuple[Deviation, ...]) -> dict[str, int]:
    """A count of findings by severity, for a report header."""
    counts = dict.fromkeys((s.value for s in Severity), 0)
    for finding in findings:
        counts[finding.severity.value] += 1
    return counts
