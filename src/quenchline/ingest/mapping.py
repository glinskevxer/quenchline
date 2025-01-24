"""Turning somebody else's column headings into ours.

Every datalogger in the shop writes a different file. One writes elapsed seconds
and Fahrenheit, another writes a wall clock and Celsius, a third writes the
channel names the installer typed in 2009 and has spelled two ways since. None
of them are going to change, so the mapping is data rather than code: a profile
per vendor, held in one place, applied by one function.

The rules that stop a profile from being a foot gun:

* a profile **states its units** rather than guessing them. A column of numbers
  around 850 is either a Celsius reading or a badly scaled Fahrenheit one and
  nothing in the file says which.
* a column named in a profile that is **missing from the file** is an error, not
  a silently absent channel. A survey missing its centre couple should stop the
  ingest, not produce a survey with eight couples that nobody notices.
* heading matching is **case and whitespace insensitive but not fuzzy**. Close
  enough is how ``TC1`` gets read as ``TC11``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from ..errors import ValidationError
from ..loads.trace import ChannelRole
from ..temperature import Scale, Temperature
from ..timespan import Duration


class TimeUnit(Enum):
    """How the file writes its time column."""

    SECONDS = "seconds"
    MINUTES = "minutes"
    HOURS = "hours"
    CLOCK = "clock"

    @property
    def is_elapsed(self) -> bool:
        return self is not TimeUnit.CLOCK


def normalise_heading(text: str) -> str:
    """Lower case, strip, and squeeze internal whitespace to one space."""
    return re.sub(r"\s+", " ", text.strip().lower())


@dataclass(frozen=True)
class ColumnMap:
    """One column of the file, and what it means to us."""

    heading: str
    key: str
    role: ChannelRole

    def __post_init__(self) -> None:
        if not self.heading.strip():
            raise ValidationError("a column map needs a heading", field="heading")
        if not self.key.strip():
            raise ValidationError("a column map needs a key", field="key")

    @property
    def match(self) -> str:
        return normalise_heading(self.heading)


@dataclass(frozen=True)
class MappingProfile:
    """Everything needed to read one vendor's file."""

    name: str
    time_heading: str
    time_unit: TimeUnit
    scale: Scale
    columns: tuple[ColumnMap, ...]
    dropout_markers: tuple[str, ...] = field(
        default_factory=lambda: ("", "---", "n/a", "na", "open", "burnout", "####")
    )
    delimiter: str = ","

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("a profile needs a name", field="name")
        if not self.time_heading.strip():
            raise ValidationError("a profile needs a time column", field="time_heading")
        if not self.columns:
            raise ValidationError("a profile needs at least one channel", field="columns")
        keys = [c.key for c in self.columns]
        if len(set(keys)) != len(keys):
            raise ValidationError("two columns map to the same key", field="columns")
        matches = [c.match for c in self.columns]
        if len(set(matches)) != len(matches):
            raise ValidationError("two columns match the same heading", field="columns")

    @property
    def time_match(self) -> str:
        return normalise_heading(self.time_heading)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(c.key for c in self.columns)

    def column_for(self, heading: str) -> ColumnMap | None:
        wanted = normalise_heading(heading)
        for column in self.columns:
            if column.match == wanted:
                return column
        return None

    def resolve(self, headings: list[str]) -> dict[int, ColumnMap]:
        """Which file column index carries which mapped channel."""
        found: dict[int, ColumnMap] = {}
        seen: set[str] = set()
        for index, heading in enumerate(headings):
            column = self.column_for(heading)
            if column is None:
                continue
            if column.key in seen:
                raise ValidationError(
                    f"heading {heading!r} maps to {column.key} twice", field="headings"
                )
            found[index] = column
            seen.add(column.key)
        missing = [c.key for c in self.columns if c.key not in seen]
        if missing:
            raise ValidationError(
                "the file is missing mapped columns: " + ", ".join(sorted(missing)),
                field="headings",
            )
        return found

    def time_index(self, headings: list[str]) -> int:
        for index, heading in enumerate(headings):
            if normalise_heading(heading) == self.time_match:
                return index
        raise ValidationError(f"the file has no {self.time_heading!r} column", field="headings")

    def is_dropout(self, cell: str) -> bool:
        return cell.strip().lower() in self.dropout_markers

    def read_time(self, cell: str) -> Duration:
        text = cell.strip()
        if not text:
            raise ValidationError("empty time cell", field="time")
        if self.time_unit is TimeUnit.CLOCK:
            return Duration.parse(text)
        try:
            value = float(text)
        except ValueError:
            raise ValidationError(f"{text!r} is not a number", field="time") from None
        if value < 0:
            raise ValidationError("elapsed time cannot be negative", field="time")
        if self.time_unit is TimeUnit.SECONDS:
            return Duration(value)
        if self.time_unit is TimeUnit.MINUTES:
            return Duration.of(minutes=value)
        return Duration.of(hours=value)

    def read_temperature(self, cell: str) -> Temperature | None:
        if self.is_dropout(cell):
            return None
        try:
            return Temperature(float(cell.strip()), self.scale)
        except ValueError:
            raise ValidationError(
                f"{cell.strip()!r} is not a temperature", field="reading"
            ) from None
