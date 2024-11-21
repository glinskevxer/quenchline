"""A quench bath, and whether it is fit to take a load right now.

The bath record holds what somebody measured last time they looked, and the
readiness check compares that against what the medium demands. The interesting
part is that the check list is built from the medium rather than being fixed, so
a gas quench is never asked about its concentration and never fails for not
having one.

The load ratio check is the only one that needs the load, and it is the reason
readiness is asked per load rather than once per shift.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum

from ..calendar_rules import Interval, is_overdue
from ..errors import ValidationError
from ..measure import Mass
from ..temperature import Temperature
from .media import Agitation, Medium, load_ratio

DEFAULT_CHECK_INTERVAL = Interval.weeks(1)


class BathFault(Enum):
    TOO_COLD = "too_cold"
    TOO_HOT = "too_hot"
    FROZEN = "frozen"
    WEAK_AGITATION = "weak_agitation"
    CONCENTRATION_OUT = "concentration_out"
    OVERLOADED = "overloaded"
    CHECK_OVERDUE = "check_overdue"
    NOT_IN_SERVICE = "not_in_service"


@dataclass(frozen=True)
class Bath:
    """One quench tank as last measured."""

    identifier: str
    medium: Medium
    gallons: float
    temperature: Temperature
    agitation: Agitation = Agitation.MODERATE
    concentration: float | None = None
    last_checked: date | None = None
    check_interval: Interval = DEFAULT_CHECK_INTERVAL
    in_service: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValidationError("a bath needs an identifier", field="identifier")
        if self.gallons <= 0:
            raise ValidationError("a bath needs a volume", field="gallons")
        if self.medium.kind.has_concentration and self.concentration is None:
            raise ValidationError(
                "a polymer bath needs a measured concentration", field="concentration"
            )
        if not self.medium.kind.has_concentration and self.concentration is not None:
            raise ValidationError(
                f"a {self.medium.kind.value} bath has no concentration", field="concentration"
            )

    def ratio_for(self, weight: Mass) -> float:
        return load_ratio(weight, self.gallons)

    def capacity(self) -> Mass:
        """The heaviest load this bath may take."""
        return Mass.pounds(self.medium.max_pounds_per_gallon * self.gallons)

    def check_due(self) -> date | None:
        if self.last_checked is None:
            return None
        return self.check_interval.after(self.last_checked)

    def measured(
        self,
        on: date,
        temperature: Temperature,
        *,
        concentration: float | None = None,
        agitation: Agitation | None = None,
    ) -> Bath:
        """Record a fresh set of bath readings."""
        return replace(
            self,
            temperature=temperature,
            concentration=concentration if concentration is not None else self.concentration,
            agitation=agitation if agitation is not None else self.agitation,
            last_checked=on,
        )

    def take_out_of_service(self, reason: str) -> Bath:
        if not reason.strip():
            raise ValidationError("give a reason", field="reason")
        return replace(self, in_service=False, notes=(*self.notes, reason))

    def return_to_service(self) -> Bath:
        return replace(self, in_service=True)

    def __str__(self) -> str:
        return f"{self.identifier} {self.medium.name} at {self.temperature.format()}"


@dataclass(frozen=True)
class BathReadiness:
    """Whether a bath may take one load today."""

    bath: Bath
    faults: tuple[BathFault, ...]
    detail: tuple[str, ...]

    @property
    def is_ready(self) -> bool:
        return not self.faults

    def __str__(self) -> str:
        if self.is_ready:
            return f"{self.bath.identifier} is ready"
        return f"{self.bath.identifier} not ready: " + ", ".join(self.detail)


def readiness(bath: Bath, weight: Mass, on: date, *, grace: int = 0) -> BathReadiness:
    """Every reason this bath should not take this load."""
    faults: list[BathFault] = []
    detail: list[str] = []
    medium = bath.medium

    if not bath.in_service:
        faults.append(BathFault.NOT_IN_SERVICE)
        detail.append("bath is out of service")

    if not medium.above_melting(bath.temperature):
        faults.append(BathFault.FROZEN)
        detail.append(f"below the melting point of {medium.name}")
    elif bath.temperature.degf < medium.operating.lower.degf:
        faults.append(BathFault.TOO_COLD)
        detail.append(f"{bath.temperature.format()} is under the operating band")
    elif bath.temperature.degf > medium.operating.upper.degf:
        faults.append(BathFault.TOO_HOT)
        detail.append(f"{bath.temperature.format()} is over the operating band")

    if medium.kind.needs_agitation and not bath.agitation.at_least(medium.minimum_agitation):
        faults.append(BathFault.WEAK_AGITATION)
        detail.append(
            f"agitation {bath.agitation.name.lower()} against a required "
            f"{medium.minimum_agitation.name.lower()}"
        )

    if medium.kind.has_concentration:
        assert bath.concentration is not None
        if not medium.concentration_ok(bath.concentration):
            faults.append(BathFault.CONCENTRATION_OUT)
            detail.append(f"concentration {bath.concentration:.1f} percent is out of range")

    ratio = bath.ratio_for(weight)
    if ratio > medium.max_pounds_per_gallon + 1e-9:
        faults.append(BathFault.OVERLOADED)
        detail.append(
            f"{ratio:.2f} lb per gallon against a limit of {medium.max_pounds_per_gallon:.2f}"
        )

    due = bath.check_due()
    if due is None:
        faults.append(BathFault.CHECK_OVERDUE)
        detail.append("bath has never been checked")
    elif is_overdue(due, on, grace=grace):
        faults.append(BathFault.CHECK_OVERDUE)
        detail.append(f"bath check overdue since {due.isoformat()}")

    return BathReadiness(bath, tuple(faults), tuple(detail))
