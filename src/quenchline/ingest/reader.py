"""Reading a datalogger file into a trace.

The reader does one pass over the text and produces two things: a
:class:`~quenchline.loads.trace.Trace` built from the rows it could use, and a
:class:`~quenchline.ingest.quarantine.Quarantine` holding the rows it could not,
each with a reason.

It never gives up on a file because one row is bad, and it never quietly drops
one either. Whether the result is good enough is the caller's call, and the
quarantine carries the numbers that call needs.

One decision worth naming: a **repeated timestamp** is a rejection rather than
an overwrite. Two rows claiming the same moment mean somebody merged two files,
and picking either one of them is guessing.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from io import StringIO

from ..errors import ValidationError
from ..loads.trace import Channel, Sample, Trace
from ..temperature import Temperature
from ..timespan import Duration
from .mapping import MappingProfile
from .quarantine import Quarantine, RejectReason, normalised_hash


@dataclass(frozen=True)
class ReadResult:
    """What one pass over a file produced."""

    trace: Trace | None
    quarantine: Quarantine
    digest: str
    rows: int

    @property
    def succeeded(self) -> bool:
        return self.trace is not None

    def trace_or_raise(self) -> Trace:
        if self.trace is None:
            raise ValidationError("the file produced no usable rows", field="file")
        return self.trace


def read_text(
    text: str,
    profile: MappingProfile,
    started: datetime,
    *,
    source: str = "",
) -> ReadResult:
    """Read one datalogger file into a trace."""
    digest = normalised_hash(text)
    quarantine = Quarantine()
    reader = csv.reader(StringIO(text), delimiter=profile.delimiter)

    try:
        headings = next(reader)
    except StopIteration:
        raise ValidationError("the file is empty", field="file") from None

    time_index = profile.time_index(headings)
    mapped = profile.resolve(headings)
    width = max([time_index, *mapped]) + 1

    collected: dict[str, list[Sample]] = {column.key: [] for column in mapped.values()}
    seen_times: set[float] = set()
    last_time = -1.0

    for offset, row in enumerate(reader, start=2):
        raw = profile.delimiter.join(row)
        if not any(cell.strip() for cell in row):
            quarantine.reject(offset, RejectReason.EMPTY, "blank row", raw)
            continue
        if len(row) < width:
            quarantine.reject(
                offset,
                RejectReason.SHORT_ROW,
                f"{len(row)} cells, {width} expected",
                raw,
            )
            continue
        try:
            elapsed = profile.read_time(row[time_index])
        except ValidationError as error:
            quarantine.reject(offset, RejectReason.BAD_TIME, str(error), raw)
            continue
        if elapsed.seconds in seen_times:
            quarantine.reject(
                offset,
                RejectReason.DUPLICATE_TIME,
                f"{elapsed.format()} appears twice",
                raw,
            )
            continue
        if elapsed.seconds < last_time:
            quarantine.reject(
                offset,
                RejectReason.OUT_OF_ORDER,
                f"{elapsed.format()} comes after a later row",
                raw,
            )
            continue

        values: dict[str, Temperature | None] = {}
        failed = False
        for index, column in mapped.items():
            try:
                values[column.key] = profile.read_temperature(row[index])
            except ValidationError as error:
                quarantine.reject(offset, RejectReason.BAD_READING, str(error), raw)
                failed = True
                break
        if failed:
            continue

        for key, value in values.items():
            collected[key].append(Sample(elapsed, value))
        seen_times.add(elapsed.seconds)
        last_time = elapsed.seconds
        quarantine.accept()

    channels = _build_channels(profile, collected)
    trace = None if channels is None else Trace(started, channels, source)
    return ReadResult(trace, quarantine, digest, quarantine.seen)


def _build_channels(
    profile: MappingProfile, collected: dict[str, list[Sample]]
) -> tuple[Channel, ...] | None:
    built: list[Channel] = []
    for column in profile.columns:
        samples = collected.get(column.key, [])
        if not samples:
            return None
        built.append(Channel(column.key, column.role, tuple(samples)))
    return tuple(built)


def elapsed_span(result: ReadResult) -> Duration:
    """How much time the usable rows cover."""
    if result.trace is None:
        return Duration(0.0)
    return result.trace.duration
