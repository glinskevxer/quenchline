"""How many pieces to test, and whether the lot passed.

Two rules, and the interesting one is the second.

**How many.** Sample size comes off the lot size in steps, with a floor of
three, because two readings cannot tell a spread from a bad indent. Small lots
get tested completely.

**Whether it passed.** Every reading has to sit inside the specified range, but
a single low or high reading is not automatically a rejection. It buys a
**retest** on a doubled sample, and the lot is judged on that. A second failure
ends it. This is the rule people implement as "if any reading fails, reject",
which throws away good work, or as "average the readings", which ships bad work.
It is neither.

A **converted** reading cannot be used for acceptance unless the specification
says so in as many words. Converting a Brinell reading to Rockwell C to argue
that a part met a Rockwell C requirement is exactly the sort of thing a
specification exists to stop.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from ..errors import ValidationError
from ..numeric import mean, spread
from .scales import Hardness, HardnessScale

MINIMUM_SAMPLE = 3


class LotVerdict(Enum):
    ACCEPTED = "accepted"
    RETEST = "retest"
    REJECTED = "rejected"

    @property
    def is_final(self) -> bool:
        return self is not LotVerdict.RETEST


def sample_size(lot_size: int) -> int:
    """How many pieces to test out of a lot."""
    if lot_size < 1:
        raise ValidationError("a lot needs at least one piece", field="lot_size")
    if lot_size <= MINIMUM_SAMPLE:
        return lot_size
    suggested = int(math.ceil(math.sqrt(lot_size)))
    return max(MINIMUM_SAMPLE, min(suggested, lot_size))


@dataclass(frozen=True)
class Specification:
    """The hardness a part is required to come out at."""

    scale: HardnessScale
    minimum: float | None = None
    maximum: float | None = None
    allow_converted: bool = False
    maximum_spread: float | None = None

    def __post_init__(self) -> None:
        if self.minimum is None and self.maximum is None:
            raise ValidationError("a specification needs a limit", field="specification")
        inverted = (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        )
        if inverted:
            raise ValidationError("the limits are inverted", field="specification")
        if self.maximum_spread is not None and self.maximum_spread <= 0:
            raise ValidationError("a spread limit must be positive", field="maximum_spread")

    def contains(self, reading: Hardness) -> bool:
        if reading.scale is not self.scale:
            raise ValidationError(
                f"reading is on {reading.scale.value}, specification is on {self.scale.value}",
                field="scale",
            )
        if self.minimum is not None and reading.value < self.minimum - 1e-9:
            return False
        return not (self.maximum is not None and reading.value > self.maximum + 1e-9)

    def __str__(self) -> str:
        if self.minimum is not None and self.maximum is not None:
            return f"{self.minimum:g} to {self.maximum:g} {self.scale.value}"
        if self.minimum is not None:
            return f"{self.minimum:g} {self.scale.value} minimum"
        return f"{self.maximum:g} {self.scale.value} maximum"


@dataclass(frozen=True)
class LotResult:
    """The verdict on one round of testing."""

    verdict: LotVerdict
    readings: tuple[Hardness, ...]
    failures: tuple[Hardness, ...]
    required_sample: int
    reason: str

    @property
    def is_accepted(self) -> bool:
        return self.verdict is LotVerdict.ACCEPTED

    @property
    def average(self) -> float | None:
        if not self.readings:
            return None
        return mean([r.value for r in self.readings])

    def __str__(self) -> str:
        return f"{self.verdict.value}: {self.reason}"


def judge(
    readings: list[Hardness],
    specification: Specification,
    lot_size: int,
    *,
    is_retest: bool = False,
) -> LotResult:
    """Judge one round of hardness testing on a lot."""
    required = sample_size(lot_size)
    if is_retest:
        required *= 2

    if not readings:
        raise ValidationError("no readings to judge", field="readings")

    converted = [r for r in readings if r.converted]
    if converted and not specification.allow_converted:
        return LotResult(
            LotVerdict.REJECTED,
            tuple(readings),
            tuple(converted),
            required,
            "converted readings cannot be used for acceptance",
        )

    if len(readings) < required:
        return LotResult(
            LotVerdict.REJECTED,
            tuple(readings),
            (),
            required,
            f"{len(readings)} readings against a required sample of {required}",
        )

    failures = tuple(r for r in readings if not specification.contains(r))

    if specification.maximum_spread is not None:
        actual = spread([r.value for r in readings])
        if actual > specification.maximum_spread + 1e-9:
            return LotResult(
                LotVerdict.REJECTED,
                tuple(readings),
                failures,
                required,
                f"spread of {actual:g} against a limit of {specification.maximum_spread:g}",
            )

    if not failures:
        return LotResult(
            LotVerdict.ACCEPTED,
            tuple(readings),
            (),
            required,
            f"{len(readings)} readings, all inside {specification}",
        )

    if len(failures) == 1 and not is_retest:
        return LotResult(
            LotVerdict.RETEST,
            tuple(readings),
            failures,
            required,
            f"one reading at {failures[0].format()} buys a retest on {required * 2} pieces",
        )

    return LotResult(
        LotVerdict.REJECTED,
        tuple(readings),
        failures,
        required,
        f"{len(failures)} readings outside {specification}",
    )
