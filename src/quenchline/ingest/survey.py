"""Reading a survey file.

A uniformity survey arrives as one file per set point, written by the same
loggers as everything else but meaning something different: each column is a
**position in the work zone** rather than a role on a furnace, and where the
couple sat matters as much as what it read.

So the layout is its own thing rather than a reuse of the load mapping profile.
Two of its rules are the reason:

* a survey column names a **sensor tag and a position**, and the position says
  whether it is a corner or the centre. That is what the dropout rules read.
* a survey file must contain **every** column the layout names. A load trace
  with a missing channel is a load with fewer load couples than planned; a
  survey with a missing column has lost a position, and a survey missing a
  corner is not a survey.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from io import StringIO

from ..errors import ValidationError
from ..identity import SensorTag
from ..temperature import Scale, Temperature
from ..tus.survey import Scan, SurveyPoint, SurveySetpoint
from .mapping import TimeUnit, normalise_heading
from .quarantine import Quarantine, RejectReason


@dataclass(frozen=True)
class SurveyColumn:
    """One column of a survey file."""

    heading: str
    sensor: SensorTag
    location: str
    is_corner: bool = False
    is_centre: bool = False

    def __post_init__(self) -> None:
        if not self.heading.strip():
            raise ValidationError("a survey column needs a heading", field="heading")

    @property
    def match(self) -> str:
        return normalise_heading(self.heading)

    def to_point(self) -> SurveyPoint:
        return SurveyPoint(self.sensor, self.location, self.is_corner, self.is_centre)


@dataclass(frozen=True)
class SurveyLayout:
    """Where every column of a survey file sat in the work zone."""

    name: str
    time_heading: str
    time_unit: TimeUnit
    scale: Scale
    columns: tuple[SurveyColumn, ...]
    delimiter: str = ","
    dropout_markers: tuple[str, ...] = field(
        default_factory=lambda: ("", "---", "n/a", "open", "burnout")
    )

    def __post_init__(self) -> None:
        if not self.columns:
            raise ValidationError("a survey layout needs columns", field="columns")
        tags = [str(column.sensor) for column in self.columns]
        if len(set(tags)) != len(tags):
            raise ValidationError("the same couple is placed twice", field="columns")
        matches = [column.match for column in self.columns]
        if len(set(matches)) != len(matches):
            raise ValidationError("two columns match the same heading", field="columns")
        object.__setattr__(
            self, "dropout_markers", tuple(m.strip().lower() for m in self.dropout_markers)
        )

    @property
    def points(self) -> tuple[SurveyPoint, ...]:
        return tuple(column.to_point() for column in self.columns)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(str(column.sensor) for column in self.columns)

    @property
    def corner_count(self) -> int:
        return sum(1 for column in self.columns if column.is_corner)

    def resolve(self, headings: list[str]) -> dict[int, SurveyColumn]:
        wanted = {column.match: column for column in self.columns}
        found: dict[int, SurveyColumn] = {}
        seen: set[str] = set()
        for index, heading in enumerate(headings):
            column = wanted.get(normalise_heading(heading))
            if column is None or column.match in seen:
                continue
            found[index] = column
            seen.add(column.match)
        missing = sorted(m for m in wanted if m not in seen)
        if missing:
            raise ValidationError(
                "the survey file is missing positions: " + ", ".join(missing),
                field="headings",
            )
        return found

    def time_index(self, headings: list[str]) -> int:
        wanted = normalise_heading(self.time_heading)
        for index, heading in enumerate(headings):
            if normalise_heading(heading) == wanted:
                return index
        raise ValidationError(
            f"the survey file has no {self.time_heading!r} column", field="headings"
        )

    def read_time(self, cell: str) -> float:
        text = cell.strip()
        if not text:
            raise ValidationError("empty time cell", field="time")
        if self.time_unit is TimeUnit.CLOCK:
            from ..timespan import Duration

            return Duration.parse(text).seconds
        try:
            value = float(text)
        except ValueError:
            raise ValidationError(f"{text!r} is not a number", field="time") from None
        if value < 0:
            raise ValidationError("elapsed time cannot be negative", field="time")
        if self.time_unit is TimeUnit.MINUTES:
            return value * 60.0
        if self.time_unit is TimeUnit.HOURS:
            return value * 3600.0
        return value

    def read_temperature(self, cell: str) -> Temperature | None:
        if cell.strip().lower() in self.dropout_markers:
            return None
        try:
            return Temperature(float(cell.strip()), self.scale)
        except ValueError:
            raise ValidationError(
                f"{cell.strip()!r} is not a temperature", field="reading"
            ) from None


@dataclass(frozen=True)
class SurveyReadResult:
    """One set point read out of a file."""

    data: SurveySetpoint | None
    quarantine: Quarantine

    @property
    def succeeded(self) -> bool:
        return self.data is not None

    def or_raise(self) -> SurveySetpoint:
        if self.data is None:
            raise ValidationError("the survey file produced no usable scans", field="file")
        return self.data


def read_setpoint(text: str, layout: SurveyLayout, setpoint: Temperature) -> SurveyReadResult:
    """Read one set point of a survey out of a file.

    A scan with any missing reading is kept, not rejected: a couple that dropped
    out mid survey is exactly what the dropout rules exist to judge, and
    throwing the scan away would hide it.
    """
    from ..timespan import Duration

    quarantine = Quarantine()
    reader = csv.reader(StringIO(text), delimiter=layout.delimiter)
    try:
        headings = next(reader)
    except StopIteration:
        raise ValidationError("the survey file is empty", field="file") from None

    time_index = layout.time_index(headings)
    mapped = layout.resolve(headings)
    width = max([time_index, *mapped]) + 1

    scans: list[Scan] = []
    last = -1.0
    for offset, row in enumerate(reader, start=2):
        raw = layout.delimiter.join(row)
        if not any(cell.strip() for cell in row):
            quarantine.reject(offset, RejectReason.EMPTY, "blank row", raw)
            continue
        if len(row) < width:
            quarantine.reject(
                offset, RejectReason.SHORT_ROW, f"{len(row)} cells, {width} expected", raw
            )
            continue
        try:
            seconds = layout.read_time(row[time_index])
        except ValidationError as error:
            quarantine.reject(offset, RejectReason.BAD_TIME, str(error), raw)
            continue
        if seconds < last:
            quarantine.reject(
                offset, RejectReason.OUT_OF_ORDER, "row comes after a later one", raw
            )
            continue

        values: dict[str, Temperature] = {}
        failed = False
        for index, column in mapped.items():
            try:
                reading = layout.read_temperature(row[index])
            except ValidationError as error:
                quarantine.reject(offset, RejectReason.BAD_READING, str(error), raw)
                failed = True
                break
            if reading is not None:
                values[str(column.sensor)] = reading
        if failed:
            continue

        scans.append(Scan.of(Duration(seconds), values))
        last = seconds
        quarantine.accept()

    if not scans:
        return SurveyReadResult(None, quarantine)
    return SurveyReadResult(SurveySetpoint(setpoint, tuple(scans)), quarantine)
