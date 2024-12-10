"""Hardness scales and conversion between them.

A hardness number without its scale is meaningless, and 45 is a perfectly good
number on three different scales meaning three completely different things. So a
reading carries its scale, the same way a temperature does.

Conversion is the part to be careful with. The published tables are for
**steel**, they are empirical rather than derived, and they only exist over the
range where two scales overlap. Converting a Rockwell B reading of 60 into
Rockwell C is not approximately right, it is meaningless: the C scale does not
reach that low and the diamond would not be indenting properly if it did.

So conversion here refuses outside the overlap rather than extrapolating, and
every converted value is marked as converted, because a certificate that reports
a converted number as if it were measured is a false record.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import OutOfRangeError, ValidationError
from ..numeric import Curve, Extrapolation


class HardnessScale(Enum):
    """The scales this shop reports on."""

    HRC = "HRC"
    HRB = "HRB"
    HRA = "HRA"
    HBW = "HBW"
    HV = "HV"
    HR15N = "HR15N"

    @classmethod
    def parse(cls, text: str) -> HardnessScale:
        cleaned = text.strip().upper().replace(" ", "")
        for candidate in cls:
            if candidate.value == cleaned:
                return candidate
        raise ValidationError(f"unknown hardness scale {text!r}", field="scale")

    @property
    def is_rockwell(self) -> bool:
        return self in {
            HardnessScale.HRC,
            HardnessScale.HRB,
            HardnessScale.HRA,
            HardnessScale.HR15N,
        }

    @property
    def is_superficial(self) -> bool:
        return self is HardnessScale.HR15N


_LIMITS: dict[str, tuple[float, float]] = {
    "HRC": (20.0, 70.0),
    "HRB": (20.0, 100.0),
    "HRA": (20.0, 88.0),
    "HBW": (80.0, 650.0),
    "HV": (80.0, 940.0),
    "HR15N": (68.0, 94.0),
}


@dataclass(frozen=True, order=False)
class Hardness:
    """One hardness reading on one scale."""

    value: float
    scale: HardnessScale
    converted: bool = False

    def __post_init__(self) -> None:
        low, high = _LIMITS[self.scale.value]
        if not low - 1e-9 <= self.value <= high + 1e-9:
            raise OutOfRangeError(
                f"{self.value} is outside the {self.scale.value} scale",
                value=self.value,
                low=low,
                high=high,
                field="value",
            )

    @classmethod
    def parse(cls, text: str) -> Hardness:
        cleaned = text.strip().upper().replace(" ", "")
        for scale in HardnessScale:
            if cleaned.endswith(scale.value):
                number = cleaned[: -len(scale.value)]
                try:
                    return cls(float(number), scale)
                except ValueError:
                    raise ValidationError("not a hardness", field="hardness") from None
        raise ValidationError(f"no hardness scale in {text!r}", field="hardness")

    def __lt__(self, other: Hardness) -> bool:
        _same_scale(self, other)
        return self.value < other.value

    def __le__(self, other: Hardness) -> bool:
        _same_scale(self, other)
        return self.value <= other.value

    def __gt__(self, other: Hardness) -> bool:
        _same_scale(self, other)
        return self.value > other.value

    def __ge__(self, other: Hardness) -> bool:
        _same_scale(self, other)
        return self.value >= other.value

    def format(self, places: int = 0) -> str:
        marker = " (converted)" if self.converted else ""
        return f"{self.value:.{places}f} {self.scale.value}{marker}"

    def __str__(self) -> str:
        return self.format()


def _same_scale(left: Hardness, right: Hardness) -> None:
    if left.scale is not right.scale:
        raise ValidationError(
            f"cannot compare {left.scale.value} with {right.scale.value}", field="scale"
        )


# Approximate steel conversion, anchored on Rockwell C.
_HRC_TO_HV = Curve.from_points(
    [
        (20.0, 238.0),
        (25.0, 266.0),
        (30.0, 302.0),
        (35.0, 345.0),
        (40.0, 392.0),
        (45.0, 446.0),
        (50.0, 513.0),
        (55.0, 595.0),
        (60.0, 697.0),
        (65.0, 832.0),
    ],
    extrapolation=Extrapolation.REFUSE,
)

_HRC_TO_HBW = Curve.from_points(
    [
        (20.0, 226.0),
        (25.0, 253.0),
        (30.0, 286.0),
        (35.0, 327.0),
        (40.0, 371.0),
        (45.0, 421.0),
        (50.0, 481.0),
        (55.0, 551.0),
    ],
    extrapolation=Extrapolation.REFUSE,
)

_HRB_TO_HRC = Curve.from_points(
    [(85.0, 20.0), (90.0, 24.0), (95.0, 28.0), (100.0, 32.0)],
    extrapolation=Extrapolation.REFUSE,
)

_HRC_TO_HRA = Curve.from_points(
    [(20.0, 60.5), (30.0, 65.3), (40.0, 70.4), (50.0, 75.9), (60.0, 81.2), (65.0, 84.0)],
    extrapolation=Extrapolation.REFUSE,
)


def _to_hrc(reading: Hardness) -> float:
    if reading.scale is HardnessScale.HRC:
        return reading.value
    if reading.scale is HardnessScale.HRB:
        return _lookup(_HRB_TO_HRC, reading.value, "HRB", "HRC")
    if reading.scale is HardnessScale.HV:
        return _inverse(_HRC_TO_HV, reading.value, "HV", "HRC")
    if reading.scale is HardnessScale.HBW:
        return _inverse(_HRC_TO_HBW, reading.value, "HBW", "HRC")
    if reading.scale is HardnessScale.HRA:
        return _inverse(_HRC_TO_HRA, reading.value, "HRA", "HRC")
    raise ValidationError(
        f"{reading.scale.value} has no published conversion here", field="scale"
    )


def convert(reading: Hardness, scale: HardnessScale) -> Hardness:
    """Convert a steel hardness reading onto another scale.

    Refuses rather than extrapolating outside the published overlap, and marks
    the answer as converted so it can never be reported as a measurement.
    """
    if scale is reading.scale:
        return reading
    if scale is HardnessScale.HR15N or reading.scale is HardnessScale.HR15N:
        raise ValidationError(
            "superficial Rockwell does not convert to the deep scales", field="scale"
        )
    hrc = _to_hrc(reading)
    if scale is HardnessScale.HRC:
        return Hardness(round(hrc, 1), HardnessScale.HRC, converted=True)
    if scale is HardnessScale.HV:
        return Hardness(round(_lookup(_HRC_TO_HV, hrc, "HRC", "HV")), scale, converted=True)
    if scale is HardnessScale.HBW:
        return Hardness(round(_lookup(_HRC_TO_HBW, hrc, "HRC", "HBW")), scale, converted=True)
    if scale is HardnessScale.HRA:
        return Hardness(
            round(_lookup(_HRC_TO_HRA, hrc, "HRC", "HRA"), 1), scale, converted=True
        )
    return Hardness(round(_inverse(_HRB_TO_HRC, hrc, "HRC", "HRB"), 1), scale, converted=True)


def _lookup(curve: Curve, value: float, source: str, target: str) -> float:
    try:
        return curve.at(value)
    except OutOfRangeError as error:
        raise ValidationError(
            f"{value:g} {source} is outside the published {source} to {target} overlap",
            field="value",
        ) from error


def _inverse(curve: Curve, value: float, source: str, target: str) -> float:
    reversed_curve = Curve(curve.ys, curve.xs, Extrapolation.REFUSE)
    return _lookup(reversed_curve, value, source, target)
