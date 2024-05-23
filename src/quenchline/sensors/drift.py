"""Drift between successive calibrations.

Two certificates for the same couple, a year apart, are the only honest evidence
the shop has that a sensor is going bad. The question is never "is the
correction big", because a couple can sit at a steady minus four degrees for
years and be perfectly usable. The question is "is the correction *moving*", and
if it is, when does it cross the limit.

Only the nominal points the two certificates have in common are compared. A lab
that dropped the 600 degF point from the second certificate has not proved the
couple got better at 600 degF.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from ..errors import ValidationError
from ..temperature import Scale, Temperature, TemperatureDelta
from .calibration import Certificate
from .types import ThermocoupleType, ToleranceClass, initial_tolerance

DAYS_PER_YEAR = 365.25


class DriftVerdict(Enum):
    STABLE = "stable"
    DRIFTING = "drifting"
    OUT_OF_TOLERANCE = "out_of_tolerance"

    @property
    def needs_action(self) -> bool:
        return self is not DriftVerdict.STABLE


@dataclass(frozen=True)
class PointDrift:
    """How one nominal point moved between two certificates."""

    nominal: Temperature
    earlier: TemperatureDelta
    later: TemperatureDelta
    span_days: int

    @property
    def change(self) -> TemperatureDelta:
        return TemperatureDelta(self.later.degf - self.earlier.degf, Scale.FAHRENHEIT)

    @property
    def per_year(self) -> TemperatureDelta:
        if self.span_days <= 0:
            return TemperatureDelta(0.0, Scale.FAHRENHEIT)
        rate = self.change.degf * DAYS_PER_YEAR / self.span_days
        return TemperatureDelta(rate, Scale.FAHRENHEIT)


@dataclass(frozen=True)
class DriftReport:
    """The comparison of two certificates for one couple."""

    earlier_number: str
    later_number: str
    points: tuple[PointDrift, ...]
    verdict: DriftVerdict
    worst: PointDrift | None
    limit: TemperatureDelta

    @property
    def is_clean(self) -> bool:
        return self.verdict is DriftVerdict.STABLE


def compare(
    earlier: Certificate,
    later: Certificate,
    kind: ThermocoupleType,
    *,
    grade: ToleranceClass = ToleranceClass.STANDARD,
    drift_fraction: float = 0.5,
) -> DriftReport:
    """Compare two certificates for the same couple.

    ``drift_fraction`` is the share of the couple's initial tolerance that a
    single interval of drift is allowed to eat. Half is the shop default: a
    couple that used half its allowance in one year will not survive the next.
    """
    if later.issued < earlier.issued:
        raise ValidationError("the later certificate is older", field="issued")
    if not 0 < drift_fraction <= 1:
        raise ValidationError(
            "drift fraction runs from just above 0 to 1", field="drift_fraction"
        )

    span = (later.issued - earlier.issued).days
    early_by_nominal = {round(p.nominal_f, 6): p for p in earlier.points}
    shared: list[PointDrift] = []
    for point in later.sorted_points:
        key = round(point.nominal_f, 6)
        if key not in early_by_nominal:
            continue
        shared.append(
            PointDrift(
                nominal=point.nominal,
                earlier=earlier.correction_at(point.nominal),
                later=later.correction_at(point.nominal),
                span_days=span,
            )
        )
    if not shared:
        raise ValidationError(
            "the two certificates share no calibration points", field="points"
        )

    worst = max(shared, key=lambda d: abs(d.change.degf))
    tolerance = initial_tolerance(kind, worst.nominal, grade)
    total_correction = abs(worst.later.degf)
    if total_correction > abs(tolerance.degf):
        verdict = DriftVerdict.OUT_OF_TOLERANCE
    elif abs(worst.change.degf) > abs(tolerance.degf) * drift_fraction:
        verdict = DriftVerdict.DRIFTING
    else:
        verdict = DriftVerdict.STABLE
    return DriftReport(earlier.number, later.number, tuple(shared), verdict, worst, tolerance)


def project_out_of_tolerance(report: DriftReport, from_day: date) -> date | None:
    """When the worst point is expected to cross the tolerance, if ever.

    Returns ``None`` when the drift is flat or moving back toward zero, which is
    common and is not a fault. A couple whose correction is shrinking is not on
    its way out of tolerance.
    """
    worst = report.worst
    if worst is None:
        return None
    rate = worst.per_year.degf
    if rate == 0:
        return None
    current = worst.later.degf
    limit = abs(report.limit.degf)
    if current >= 0 and rate > 0:
        headroom = limit - current
    elif current <= 0 and rate < 0:
        headroom = -limit - current
    else:
        return None
    if headroom <= 0:
        return from_day
    years = headroom / rate
    if years <= 0:
        return None
    return from_day.fromordinal(from_day.toordinal() + int(years * DAYS_PER_YEAR))
