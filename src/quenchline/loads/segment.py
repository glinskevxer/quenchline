"""Cutting a trace into the steps of the cycle it was run to.

Nothing in a trace says where one step ended and the next began. The logger
wrote temperatures, not intentions. Working out which part of the chart is the
austenitising soak is a judgement, and this module makes it in one place so the
deviation engine downstream never has to.

**Which channel decides** is the first question and it is not always the same
one. A cycle that calls for load sensors is judged on the load, and on the
*coldest* load sensor at that, because the last part to get to temperature is
the one the soak time has to be counted from. A cycle with no load sensors is
judged on the control sensor, because that is all there is.

**Where the soak starts** is the second. It starts when the governing channel
first enters the band and it ends when the channel leaves it, and the window
that counts is the longest such run rather than the first. A furnace that dips
out of band for one scan an hour in has not restarted its soak, but it has ended
the run that was in progress, and taking the first run instead of the longest
would quietly shorten every soak in the shop.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import ValidationError
from ..recipes.cycle import Recipe
from ..recipes.steps import Step, StepKind
from ..timespan import Duration
from ..tolerance import Band
from .trace import Channel, ChannelRole, Trace


@dataclass(frozen=True)
class Window:
    """A stretch of the trace."""

    start: Duration
    end: Duration

    def __post_init__(self) -> None:
        if self.end.seconds < self.start.seconds:
            raise ValidationError("a window must run forward", field="window")

    @property
    def length(self) -> Duration:
        return self.end - self.start

    @property
    def is_empty(self) -> bool:
        return self.length.seconds <= 0

    def contains(self, elapsed: Duration) -> bool:
        return self.start.seconds <= elapsed.seconds <= self.end.seconds


@dataclass(frozen=True)
class Segment:
    """One step of the cycle, located on the trace."""

    step: Step
    window: Window | None
    governing_key: str

    @property
    def found(self) -> bool:
        return self.window is not None

    @property
    def length(self) -> Duration:
        return self.window.length if self.window is not None else Duration(0.0)

    def __str__(self) -> str:
        if self.window is None:
            return f"{self.step.name}: not found on the trace"
        return f"{self.step.name}: {self.window.start.format()} to {self.window.end.format()}"


def governing_channel(recipe: Recipe, trace: Trace) -> Channel:
    """The channel the cycle is judged on.

    Coldest load sensor when the cycle calls for load sensors, control sensor
    otherwise. A cycle that calls for load sensors and has none on the trace is
    an error rather than a fallback, because silently judging it on the control
    sensor is exactly the shortcut the requirement exists to stop.
    """
    if recipe.requires_load_sensors():
        load = trace.load_channels
        if not load:
            raise ValidationError(
                f"{recipe.identifier} needs load sensors and the trace has none",
                field="trace",
            )
        return min(load, key=lambda c: _channel_floor(c))
    control = trace.in_role(ChannelRole.CONTROL)
    if not control:
        raise ValidationError("the trace has no control channel", field="trace")
    return control[0]


def _channel_floor(channel: Channel) -> float:
    """A channel's peak, used to pick the coldest of several load sensors."""
    peak = channel.peak()
    return peak.degf if peak is not None else float("inf")


def longest_run_in_band(channel: Channel, band: Band) -> Window | None:
    """The longest unbroken stretch with the channel inside the band."""
    best: Window | None = None
    start: Duration | None = None
    previous: Duration | None = None
    for sample in channel.samples:
        inside = sample.is_reading and band.contains(sample.temperature())
        if inside:
            if start is None:
                start = sample.elapsed
            previous = sample.elapsed
        elif start is not None and previous is not None:
            candidate = Window(start, previous)
            if best is None or candidate.length.seconds > best.length.seconds:
                best = candidate
            start = None
            previous = None
    if start is not None and previous is not None:
        candidate = Window(start, previous)
        if best is None or candidate.length.seconds > best.length.seconds:
            best = candidate
    return best


def segment(recipe: Recipe, trace: Trace) -> tuple[Segment, ...]:
    """Locate every graded step of the cycle on the trace.

    Steps that grade nothing get a segment with no window. They are still in the
    list, in order, because a deviation report that silently omits the quench is
    worse than one that says it could not find it.
    """
    channel = governing_channel(recipe, trace)
    segments: list[Segment] = []
    for step in recipe.steps:
        band = step.band
        if not step.grades_temperature or band is None:
            segments.append(Segment(step, None, channel.key))
            continue
        segments.append(Segment(step, longest_run_in_band(channel, band), channel.key))
    return tuple(segments)


def ordered(segments: tuple[Segment, ...]) -> bool:
    """Whether the located windows run in the order the cycle wrote them."""
    found = [s.window for s in segments if s.window is not None]
    for left, right in zip(found, found[1:], strict=False):
        if right.start.seconds < left.start.seconds:
            return False
    return True


def missing(segments: tuple[Segment, ...]) -> tuple[Step, ...]:
    """Graded steps that could not be located at all."""
    return tuple(s.step for s in segments if s.step.grades_temperature and s.window is None)


def unlocatable_kinds() -> frozenset[StepKind]:
    """The step kinds this module never tries to locate."""
    return frozenset({StepKind.QUENCH, StepKind.HOLD, StepKind.RAMP})
