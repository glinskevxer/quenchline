"""Judging a uniformity survey.

A survey passes at one set point when three separate things all hold, and they
fail in different ways:

* the furnace **got there**, which is the stabilisation clock starting at all;
* it **stayed there** long enough to prove it, which is the soak time;
* and **every sensor** stayed inside the band for the whole of that soak, which
  is the uniformity itself.

The third one is judged sensor by sensor and scan by scan, never on an average.
An average across nine sensors will happily sit dead on set point while two
corners are twenty degrees apart, and that furnace is not uniform, it is
symmetrically bad.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import ValidationError
from ..furnaces.classes import FurnaceClass, uniformity_tolerance
from ..numeric import spread
from ..temperature import Scale, Temperature, TemperatureDelta
from ..timespan import Duration, minutes
from ..tolerance import Band
from .stabilization import OvershootPolicy, Stabilization, analyse, band_for, policy_for
from .survey import Survey, SurveySetpoint

MINIMUM_SOAK = minutes(30)


class SurveyVerdict(Enum):
    PASSED = "passed"
    FAILED = "failed"

    @property
    def is_pass(self) -> bool:
        return self is SurveyVerdict.PASSED


class FailureReason(Enum):
    NEVER_STABILISED = "never_stabilised"
    SHORT_SOAK = "short_soak"
    OVERSHOOT = "overshoot"
    OUT_OF_BAND = "out_of_band"
    TOO_FEW_SENSORS = "too_few_sensors"


@dataclass(frozen=True)
class Excursion:
    """One sensor outside the band during the soak."""

    elapsed: Duration
    sensor: str
    reading: Temperature
    deviation: TemperatureDelta


@dataclass(frozen=True)
class SetpointResult:
    """The verdict at one set point."""

    setpoint: Temperature
    band: Band
    stabilization: Stabilization
    excursions: tuple[Excursion, ...]
    worst_high: TemperatureDelta
    worst_low: TemperatureDelta
    widest_spread: TemperatureDelta
    verdict: SurveyVerdict
    reasons: tuple[FailureReason, ...]

    @property
    def is_pass(self) -> bool:
        return self.verdict.is_pass

    @property
    def soak_time(self) -> Duration:
        """Time with the whole zone inside the band."""
        return self.stabilization.uniform_soak

    def __str__(self) -> str:
        return (
            f"{self.setpoint.format()} {self.verdict.value} "
            f"(+{self.worst_high.magnitude:.1f}/{self.worst_low.magnitude:.1f} F)"
        )


@dataclass(frozen=True)
class SurveyResult:
    """The verdict on the whole survey."""

    survey: Survey
    setpoints: tuple[SetpointResult, ...]
    verdict: SurveyVerdict

    @property
    def is_pass(self) -> bool:
        return self.verdict.is_pass

    @property
    def failed_setpoints(self) -> tuple[SetpointResult, ...]:
        return tuple(s for s in self.setpoints if not s.is_pass)

    def at(self, setpoint: Temperature) -> SetpointResult:
        for candidate in self.setpoints:
            if abs(candidate.setpoint.degf - setpoint.degf) < 1e-9:
                return candidate
        raise ValidationError(
            f"the survey has no set point at {setpoint.format()}", field="setpoint"
        )


def evaluate_setpoint(
    data: SurveySetpoint,
    tolerance: TemperatureDelta,
    *,
    policy: OvershootPolicy = OvershootPolicy.STRICT,
    minimum_soak: Duration = MINIMUM_SOAK,
    required_sensors: int = 0,
) -> SetpointResult:
    """Judge one set point of a survey."""
    band = band_for(data.setpoint, tolerance)
    stabilization = analyse(data, tolerance, policy=policy)
    reasons: list[FailureReason] = []
    excursions: list[Excursion] = []
    highs: list[float] = [0.0]
    lows: list[float] = [0.0]
    spreads: list[float] = [0.0]

    if required_sensors and len(data.sensor_keys) < required_sensors:
        reasons.append(FailureReason.TOO_FEW_SENSORS)

    if not stabilization.started or not stabilization.all_in:
        reasons.append(FailureReason.NEVER_STABILISED)
    else:
        started = stabilization.all_in_at
        assert started is not None
        for scan in data.scans_after(started):
            values = [value.degf for _, value in scan.values]
            if values:
                spreads.append(spread(values))
            for key, value in scan.values:
                deviation = band.deviation(value)
                highs.append(max(0.0, deviation.degf))
                lows.append(min(0.0, deviation.degf))
                if not band.contains(value):
                    excursions.append(Excursion(scan.elapsed, key, value, deviation))
        if stabilization.uniform_soak.seconds < minimum_soak.seconds:
            reasons.append(FailureReason.SHORT_SOAK)
        if stabilization.overshoots and not stabilization.recovered:
            reasons.append(FailureReason.OVERSHOOT)
        below_band = [e for e in excursions if e.deviation.degf < 0]
        unexplained = bool(excursions) and not stabilization.overshoots
        if below_band or unexplained:
            reasons.append(FailureReason.OUT_OF_BAND)

    verdict = SurveyVerdict.FAILED if reasons else SurveyVerdict.PASSED
    return SetpointResult(
        data.setpoint,
        band,
        stabilization,
        tuple(excursions),
        TemperatureDelta(max(highs), Scale.FAHRENHEIT),
        TemperatureDelta(min(lows), Scale.FAHRENHEIT),
        TemperatureDelta(max(spreads), Scale.FAHRENHEIT),
        verdict,
        tuple(reasons),
    )


def evaluate(
    survey: Survey,
    furnace_class: FurnaceClass,
    *,
    minimum_soak: Duration = MINIMUM_SOAK,
    required_sensors: int = 0,
) -> SurveyResult:
    """Judge every set point of a survey against the furnace class."""
    tolerance = uniformity_tolerance(furnace_class)
    policy = policy_for(furnace_class)
    results = tuple(
        evaluate_setpoint(
            data,
            tolerance,
            policy=policy,
            minimum_soak=minimum_soak,
            required_sensors=required_sensors,
        )
        for data in survey.setpoints
    )
    passed = all(result.is_pass for result in results)
    return SurveyResult(
        survey, results, SurveyVerdict.PASSED if passed else SurveyVerdict.FAILED
    )
