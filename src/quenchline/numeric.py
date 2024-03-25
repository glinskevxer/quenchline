"""Interpolation and the small statistics the survey work needs.

Two shapes turn up everywhere in this codebase and both are here rather than
copied into five modules:

* a **curve** of x/y pairs that has to be read at an x between two points, which
  is how a thermocouple correction factor and a quench cooling rate are both
  stored;
* a handful of **spread** measures over a set of readings, which is what a
  uniformity survey reduces to.

Neither uses numpy. The data sets are tens of points, the dependency is not
worth it, and a pure Python answer is easier to reconcile against a survey
report someone worked out on paper.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from enum import Enum

from .errors import OutOfRangeError, ValidationError


class Extrapolation(Enum):
    """What a curve does when asked for an x outside its range."""

    REFUSE = "refuse"
    CLAMP = "clamp"
    LINEAR = "linear"


@dataclass(frozen=True)
class Curve:
    """A piecewise linear curve through a sorted set of x/y points."""

    xs: tuple[float, ...]
    ys: tuple[float, ...]
    extrapolation: Extrapolation = Extrapolation.REFUSE

    def __post_init__(self) -> None:
        if len(self.xs) != len(self.ys):
            raise ValidationError("curve needs an x for every y", field="points")
        if len(self.xs) < 2:
            raise ValidationError("curve needs at least two points", field="points")
        for left, right in zip(self.xs, self.xs[1:], strict=False):
            if right <= left:
                raise ValidationError("curve x values must strictly increase", field="xs")

    @classmethod
    def from_points(
        cls,
        points: list[tuple[float, float]],
        *,
        extrapolation: Extrapolation = Extrapolation.REFUSE,
    ) -> Curve:
        ordered = sorted(points, key=lambda p: p[0])
        return cls(
            tuple(p[0] for p in ordered),
            tuple(p[1] for p in ordered),
            extrapolation,
        )

    @property
    def low(self) -> float:
        return self.xs[0]

    @property
    def high(self) -> float:
        return self.xs[-1]

    def covers(self, x: float) -> bool:
        return self.low <= x <= self.high

    def at(self, x: float) -> float:
        if x < self.low:
            return self._outside(x, 0, 1, self.ys[0])
        if x > self.high:
            return self._outside(x, -2, -1, self.ys[-1])
        index = bisect_left(self.xs, x)
        if self.xs[index] == x:
            return self.ys[index]
        return self._between(x, index - 1, index)

    def _between(self, x: float, left: int, right: int) -> float:
        x0, x1 = self.xs[left], self.xs[right]
        y0, y1 = self.ys[left], self.ys[right]
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)

    def _outside(self, x: float, left: int, right: int, edge: float) -> float:
        if self.extrapolation is Extrapolation.REFUSE:
            raise OutOfRangeError(
                "outside the range this curve covers",
                value=x,
                low=self.low,
                high=self.high,
                field="x",
            )
        if self.extrapolation is Extrapolation.CLAMP:
            return edge
        return self._between(x, left, right)

    def shifted(self, dy: float) -> Curve:
        return Curve(self.xs, tuple(y + dy for y in self.ys), self.extrapolation)


def mean(values: list[float]) -> float:
    if not values:
        raise ValidationError("mean of no values", field="values")
    return math.fsum(values) / len(values)


def spread(values: list[float]) -> float:
    """Max minus min. The number a uniformity survey is actually judged on."""
    if not values:
        raise ValidationError("spread of no values", field="values")
    return max(values) - min(values)


def sample_stdev(values: list[float]) -> float:
    if len(values) < 2:
        raise ValidationError("standard deviation needs at least two values", field="values")
    avg = mean(values)
    total = math.fsum((v - avg) ** 2 for v in values)
    return math.sqrt(total / (len(values) - 1))


def median(values: list[float]) -> float:
    if not values:
        raise ValidationError("median of no values", field="values")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def slope(xs: list[float], ys: list[float]) -> float:
    """Least squares slope of y against x, used for drift and cooling rate."""
    if len(xs) != len(ys):
        raise ValidationError("slope needs an x for every y", field="points")
    if len(xs) < 2:
        raise ValidationError("slope needs at least two points", field="points")
    mx = mean(xs)
    my = mean(ys)
    numerator = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    denominator = math.fsum((x - mx) ** 2 for x in xs)
    if denominator == 0:
        raise ValidationError("slope is undefined when every x is the same", field="xs")
    return numerator / denominator
