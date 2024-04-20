"""Calibration certificates for thermocouples.

A certificate is a short table: at each of a few nominal temperatures, what the
couple read against a reference. Everything downstream needs one number out of
it, the **correction**, and there is exactly one thing to get right.

A certificate states one of two quantities and they are opposite in sign:

``CORRECTION``
    add this to the indicated reading to get the true temperature.

``DEVIATION``
    the indicated reading minus the true temperature. Subtract it.

Labs use both, the word is often missing from the certificate, and applying a
deviation as if it were a correction doubles the error instead of removing it.
So the convention is stored on the certificate and there is no default.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from ..calendar_rules import Interval
from ..errors import OutOfRangeError, ValidationError
from ..numeric import Curve, Extrapolation
from ..temperature import Scale, Temperature, TemperatureDelta


class Convention(Enum):
    """Which way round the certificate states its numbers."""

    CORRECTION = "correction"
    DEVIATION = "deviation"

    @property
    def sign(self) -> float:
        return 1.0 if self is Convention.CORRECTION else -1.0


@dataclass(frozen=True)
class CalibrationPoint:
    """One row of a certificate."""

    nominal: Temperature
    value: TemperatureDelta

    @property
    def nominal_f(self) -> float:
        return self.nominal.degf


@dataclass(frozen=True)
class Certificate:
    """A calibration certificate for one sensor."""

    number: str
    issued: date
    points: tuple[CalibrationPoint, ...]
    convention: Convention
    laboratory: str = ""
    accredited: bool = True

    def __post_init__(self) -> None:
        if not self.number.strip():
            raise ValidationError("certificate number is blank", field="number")
        if not self.points:
            raise ValidationError("a certificate needs at least one point", field="points")
        seen = {round(p.nominal_f, 6) for p in self.points}
        if len(seen) != len(self.points):
            raise ValidationError("two points at the same temperature", field="points")

    @classmethod
    def of(
        cls,
        number: str,
        issued: date,
        readings: list[tuple[float, float]],
        *,
        convention: Convention,
        scale: Scale = Scale.FAHRENHEIT,
        laboratory: str = "",
        accredited: bool = True,
    ) -> Certificate:
        """Build from raw ``(nominal, value)`` pairs on one scale."""
        points = tuple(
            CalibrationPoint(Temperature(nominal, scale), TemperatureDelta(value, scale))
            for nominal, value in readings
        )
        return cls(number, issued, points, convention, laboratory, accredited)

    @property
    def sorted_points(self) -> tuple[CalibrationPoint, ...]:
        return tuple(sorted(self.points, key=lambda p: p.nominal_f))

    @property
    def low(self) -> Temperature:
        return self.sorted_points[0].nominal

    @property
    def high(self) -> Temperature:
        return self.sorted_points[-1].nominal

    @property
    def is_single_point(self) -> bool:
        return len(self.points) == 1

    def covers(self, reading: Temperature) -> bool:
        return self.low.degf <= reading.degf <= self.high.degf

    def _curve(self) -> Curve:
        ordered = self.sorted_points
        return Curve(
            tuple(p.nominal_f for p in ordered),
            tuple(p.value.degf for p in ordered),
            Extrapolation.REFUSE,
        )

    def correction_at(self, reading: Temperature) -> TemperatureDelta:
        """The correction to add to an indicated reading, in Fahrenheit degrees.

        A single point certificate applies its one correction everywhere, which
        is what the shop does with an expendable couple. A multi point
        certificate interpolates and refuses outside its range, because
        extrapolating a correction curve past the last calibrated point is a
        guess dressed up as a measurement.
        """
        if self.is_single_point:
            raw = self.points[0].value.degf
        else:
            if not self.covers(reading):
                raise OutOfRangeError(
                    f"certificate {self.number} does not cover this temperature",
                    value=reading.degf,
                    low=self.low.degf,
                    high=self.high.degf,
                    field="reading",
                )
            raw = self._curve().at(reading.degf)
        return TemperatureDelta(raw * self.convention.sign, Scale.FAHRENHEIT)

    def apply(self, indicated: Temperature) -> Temperature:
        """The true temperature behind an indicated reading."""
        return indicated + self.correction_at(indicated)

    def largest_correction(self) -> TemperatureDelta:
        magnitudes = [abs(p.value.degf) for p in self.points]
        return TemperatureDelta(max(magnitudes), Scale.FAHRENHEIT)

    def expires(self, interval: Interval) -> date:
        return interval.after(self.issued)

    def is_expired(self, on: date, interval: Interval) -> bool:
        return on > self.expires(interval)
