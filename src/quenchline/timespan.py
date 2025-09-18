"""Durations, and the arithmetic the cycle sheets do with them.

Soak time is written on a cycle sheet as ``1h30``, ``90m`` or ``0:45``, and the
furnace log writes seconds. Everything in this package carries a
:class:`Duration` so nothing has to guess which of those a number is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from .errors import ParseError, ValidationError
from .numeric import require_finite

_CLOCK_RE: Final = re.compile(r"^(?P<h>\d+):(?P<m>[0-5]?\d)(?::(?P<s>[0-5]?\d))?$")
_COMPOUND_RE: Final = re.compile(
    r"^(?:(?P<h>\d+(?:\.\d+)?)\s*h)?\s*(?:(?P<m>\d+(?:\.\d+)?)\s*m(?:in)?)?"
    r"\s*(?:(?P<s>\d+(?:\.\d+)?)\s*s)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True, order=True)
class Duration:
    """A length of time, held in seconds."""

    seconds: float

    def __post_init__(self) -> None:
        require_finite(self.seconds, "seconds")
        if self.seconds < 0:
            raise ValidationError("duration cannot be negative", field="seconds")

    @classmethod
    def of(cls, *, hours: float = 0, minutes: float = 0, seconds: float = 0) -> Duration:
        return cls(hours * 3600.0 + minutes * 60.0 + seconds)

    @classmethod
    def from_timedelta(cls, delta: timedelta) -> Duration:
        return cls(delta.total_seconds())

    @classmethod
    def parse(cls, text: str) -> Duration:
        """Read ``1:30``, ``1h30m``, ``90m``, ``45s`` or a bare minute count."""
        cleaned = text.strip()
        if not cleaned:
            raise ParseError("empty duration", text=text, field="duration")
        clock = _CLOCK_RE.match(cleaned)
        if clock is not None:
            return cls.of(
                hours=float(clock.group("h")),
                minutes=float(clock.group("m")),
                seconds=float(clock.group("s") or 0),
            )
        compound = _COMPOUND_RE.match(cleaned)
        if compound is not None and any(compound.group(k) for k in ("h", "m", "s")):
            return cls.of(
                hours=float(compound.group("h") or 0),
                minutes=float(compound.group("m") or 0),
                seconds=float(compound.group("s") or 0),
            )
        try:
            return cls.of(minutes=float(cleaned))
        except ValueError:
            raise ParseError("not a duration", text=text, field="duration") from None

    @property
    def minutes(self) -> float:
        return self.seconds / 60.0

    @property
    def hours(self) -> float:
        return self.seconds / 3600.0

    def as_timedelta(self) -> timedelta:
        return timedelta(seconds=self.seconds)

    def __add__(self, other: Duration) -> Duration:
        return Duration(self.seconds + other.seconds)

    def __sub__(self, other: Duration) -> Duration:
        return Duration(max(0.0, self.seconds - other.seconds))

    def __mul__(self, factor: float) -> Duration:
        if factor < 0:
            raise ValidationError("cannot scale a duration by a negative", field="factor")
        return Duration(self.seconds * factor)

    def __bool__(self) -> bool:
        return self.seconds > 0

    def format(self) -> str:
        """The way it is written on a cycle sheet: ``1:30`` or ``0:45:20``."""
        total = int(round(self.seconds))
        hours, rest = divmod(total, 3600)
        minutes, seconds = divmod(rest, 60)
        if seconds:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{hours}:{minutes:02d}"

    def __str__(self) -> str:
        return self.format()


ZERO = Duration(0.0)


def minutes(count: float) -> Duration:
    return Duration.of(minutes=count)


def hours(count: float) -> Duration:
    return Duration.of(hours=count)


def total(durations: list[Duration]) -> Duration:
    return Duration(sum(d.seconds for d in durations))
