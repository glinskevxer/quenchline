"""The chart the datalogger wrote while a load ran.

A trace is a handful of channels sampled every few seconds for several hours.
Most of what this module does is deal with the fact that real traces have holes
in them, and that the holes mean different things:

* a **short gap** is a sample the logger dropped, a network blip, a scan the
  chart missed. Bridging it by drawing a straight line between the readings
  either side is honest, because nothing can have happened in twenty seconds
  that the two ends do not already show.
* a **long gap** is the couple falling off, the logger losing power, or somebody
  unplugging something. Bridging that is inventing data, and the answer has to
  be that the trace does not cover that interval.

Where the line sits between the two is a policy, not a fact, so it is an
argument with a stated default rather than a constant buried in a function.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..errors import NotFoundError, ValidationError
from ..temperature import Temperature
from ..timespan import Duration, minutes

DEFAULT_BRIDGE = minutes(1)


class ChannelRole(Enum):
    """What a trace channel was measuring."""

    CONTROL = "control"
    RECORD = "record"
    LOAD = "load"
    OVER_TEMPERATURE = "over_temperature"
    AMBIENT = "ambient"

    @property
    def is_load(self) -> bool:
        return self is ChannelRole.LOAD

    @property
    def governs_the_cycle(self) -> bool:
        """Whether this channel's readings are graded against the recipe."""
        return self in {ChannelRole.CONTROL, ChannelRole.LOAD}


@dataclass(frozen=True)
class Sample:
    """One reading on one channel."""

    elapsed: Duration
    value: Temperature | None

    @property
    def is_reading(self) -> bool:
        return self.value is not None

    def temperature(self) -> Temperature:
        if self.value is None:
            raise ValidationError("this sample is a dropout", field="value")
        return self.value


@dataclass(frozen=True)
class Gap:
    """An interval with no readings on a channel."""

    start: Duration
    end: Duration

    @property
    def length(self) -> Duration:
        return self.end - self.start

    def bridgeable(self, limit: Duration) -> bool:
        return self.length.seconds <= limit.seconds

    def contains(self, elapsed: Duration) -> bool:
        return self.start.seconds < elapsed.seconds < self.end.seconds


@dataclass(frozen=True)
class Channel:
    """One channel of a trace."""

    key: str
    role: ChannelRole
    samples: tuple[Sample, ...]

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValidationError("a channel needs a key", field="key")
        if not self.samples:
            raise ValidationError("a channel needs samples", field="samples")
        times = [s.elapsed.seconds for s in self.samples]
        if times != sorted(times):
            raise ValidationError("samples must be in time order", field="samples")

    @classmethod
    def of(
        cls,
        key: str,
        role: ChannelRole,
        readings: list[tuple[Duration, float | None]],
    ) -> Channel:
        samples = tuple(
            Sample(elapsed, None if value is None else Temperature.fahrenheit(value))
            for elapsed, value in readings
        )
        return cls(key, role, samples)

    @property
    def readings(self) -> tuple[Sample, ...]:
        return tuple(s for s in self.samples if s.is_reading)

    @property
    def start(self) -> Duration:
        return self.samples[0].elapsed

    @property
    def end(self) -> Duration:
        return self.samples[-1].elapsed

    @property
    def duration(self) -> Duration:
        return self.end - self.start

    @property
    def has_data(self) -> bool:
        return bool(self.readings)

    def gaps(self) -> tuple[Gap, ...]:
        """Every interval between consecutive readings that has no data in it."""
        found: list[Gap] = []
        previous: Sample | None = None
        for sample in self.samples:
            if not sample.is_reading:
                continue
            if previous is not None:
                missing = [
                    s
                    for s in self.samples
                    if previous.elapsed.seconds < s.elapsed.seconds < sample.elapsed.seconds
                    and not s.is_reading
                ]
                if missing:
                    found.append(Gap(previous.elapsed, sample.elapsed))
            previous = sample
        return tuple(found)

    def unbridgeable(self, limit: Duration = DEFAULT_BRIDGE) -> tuple[Gap, ...]:
        return tuple(g for g in self.gaps() if not g.bridgeable(limit))

    def at(self, elapsed: Duration, *, bridge: Duration = DEFAULT_BRIDGE) -> Temperature | None:
        """The reading at one moment, interpolated across a bridgeable gap."""
        readings = self.readings
        if not readings:
            return None
        if elapsed.seconds < readings[0].elapsed.seconds:
            return None
        if elapsed.seconds > readings[-1].elapsed.seconds:
            return None
        previous = readings[0]
        for sample in readings:
            if abs(sample.elapsed.seconds - elapsed.seconds) < 1e-9:
                return sample.temperature()
            if sample.elapsed.seconds > elapsed.seconds:
                gap = Gap(previous.elapsed, sample.elapsed)
                if not gap.bridgeable(bridge) and self._is_a_hole(gap):
                    return None
                return _interpolate(previous, sample, elapsed)
            previous = sample
        return previous.temperature()

    def _is_a_hole(self, gap: Gap) -> bool:
        return any(g.start == gap.start and g.end == gap.end for g in self.gaps())

    def peak(self) -> Temperature | None:
        readings = self.readings
        if not readings:
            return None
        return max((s.temperature() for s in readings), key=lambda t: t.degf)

    def trough(self) -> Temperature | None:
        readings = self.readings
        if not readings:
            return None
        return min((s.temperature() for s in readings), key=lambda t: t.degf)

    def rate_per_hour(self, start: Duration, end: Duration) -> float | None:
        """Average degrees per hour between two moments."""
        if end.seconds <= start.seconds:
            raise ValidationError("the interval must run forward", field="interval")
        first = self.at(start)
        last = self.at(end)
        if first is None or last is None:
            return None
        hours = (end - start).hours
        return (last.degf - first.degf) / hours

    def between(self, start: Duration, end: Duration) -> tuple[Sample, ...]:
        return tuple(
            s
            for s in self.readings
            if start.seconds - 1e-9 <= s.elapsed.seconds <= end.seconds + 1e-9
        )


def _interpolate(left: Sample, right: Sample, elapsed: Duration) -> Temperature:
    span = right.elapsed.seconds - left.elapsed.seconds
    if span <= 0:
        return left.temperature()
    fraction = (elapsed.seconds - left.elapsed.seconds) / span
    low = left.temperature().degf
    high = right.temperature().degf
    return Temperature.fahrenheit(low + (high - low) * fraction)


@dataclass(frozen=True)
class Trace:
    """Every channel the logger wrote for one load."""

    started: datetime
    channels: tuple[Channel, ...]
    source: str = ""

    def __post_init__(self) -> None:
        if not self.channels:
            raise ValidationError("a trace needs at least one channel", field="channels")
        keys = [c.key for c in self.channels]
        if len(set(keys)) != len(keys):
            raise ValidationError("two channels share a key", field="channels")

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(c.key for c in self.channels)

    def channel(self, key: str) -> Channel:
        for candidate in self.channels:
            if candidate.key == key:
                return candidate
        raise NotFoundError("trace channel", key)

    def in_role(self, role: ChannelRole) -> tuple[Channel, ...]:
        return tuple(c for c in self.channels if c.role is role)

    @property
    def load_channels(self) -> tuple[Channel, ...]:
        return self.in_role(ChannelRole.LOAD)

    @property
    def duration(self) -> Duration:
        return Duration(max(c.end.seconds for c in self.channels))

    def coldest_at(self, elapsed: Duration, role: ChannelRole) -> Temperature | None:
        """The lowest reading across one role at one moment."""
        values = [c.at(elapsed) for c in self.in_role(role)]
        present = [v for v in values if v is not None]
        if not present:
            return None
        return min(present, key=lambda t: t.degf)

    def hottest_at(self, elapsed: Duration, role: ChannelRole) -> Temperature | None:
        values = [c.at(elapsed) for c in self.in_role(role)]
        present = [v for v in values if v is not None]
        if not present:
            return None
        return max(present, key=lambda t: t.degf)
