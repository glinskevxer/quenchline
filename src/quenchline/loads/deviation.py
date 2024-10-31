"""What went wrong on a run, and how badly.

The deviation engine compares a segmented trace against the cycle it claims to
follow and produces a list of findings. Two things about it are worth stating
before the code.

**A finding is not a rejection.** Most loads have at least one finding, and most
of those loads ship. The engine's job is to say what happened, with a number
attached; deciding what that costs is :mod:`quenchline.loads.disposition`.

**Severity is not a property of the kind of fault.** A soak two minutes short and
a soak two hours short are the same kind and are not the same problem. So every
finding carries a magnitude, and severity is worked out from the kind *and* the
magnitude *and* what the cycle was relying on. A short soak on a cycle that was
judged on load sensors is worse than the same shortfall judged on the control
sensor, because the load sensor version means the parts genuinely did not get
the time.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..temperature import Scale, TemperatureDelta
from ..timespan import Duration, minutes
from .segment import Segment, ordered
from .trace import Channel, ChannelRole, Trace

OVER_TEMPERATURE_MARGIN = TemperatureDelta(50.0, Scale.FAHRENHEIT)
MINOR_SOAK_SHORTFALL = minutes(5)
MAJOR_SOAK_FRACTION = 0.25


class Severity(Enum):
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return ["minor", "major", "critical"].index(self.value)

    @property
    def blocks_certification(self) -> bool:
        return self is not Severity.MINOR


class DeviationKind(Enum):
    STEP_NOT_REACHED = "step_not_reached"
    SHORT_SOAK = "short_soak"
    LONG_SOAK = "long_soak"
    RATE_TOO_FAST = "rate_too_fast"
    RATE_TOO_SLOW = "rate_too_slow"
    SENSOR_LOST = "sensor_lost"
    OVER_TEMPERATURE = "over_temperature"
    OUT_OF_ORDER = "out_of_order"
    NO_LOAD_SENSOR = "no_load_sensor"


@dataclass(frozen=True)
class Deviation:
    """One finding against one run."""

    kind: DeviationKind
    step: str
    detail: str
    severity: Severity
    shortfall: Duration | None = None
    excess: TemperatureDelta | None = None

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.step}: {self.detail}"


def soak_severity(shortfall: Duration, required: Duration, *, judged_on_load: bool) -> Severity:
    """How bad a short soak is."""
    if required.seconds <= 0:
        return Severity.MINOR
    fraction = shortfall.seconds / required.seconds
    if fraction >= MAJOR_SOAK_FRACTION:
        return Severity.CRITICAL
    if shortfall.seconds > MINOR_SOAK_SHORTFALL.seconds:
        return Severity.CRITICAL if judged_on_load else Severity.MAJOR
    return Severity.MAJOR if judged_on_load else Severity.MINOR


def _soak_findings(segment: Segment, *, judged_on_load: bool) -> list[Deviation]:
    step = segment.step
    findings: list[Deviation] = []
    if segment.window is None:
        findings.append(
            Deviation(
                DeviationKind.STEP_NOT_REACHED,
                step.name,
                "the governing channel never held inside the band",
                Severity.CRITICAL,
            )
        )
        return findings
    held = segment.window.length
    required = step.minimum_time
    if required is not None and held.seconds < required.seconds:
        shortfall = required - held
        findings.append(
            Deviation(
                DeviationKind.SHORT_SOAK,
                step.name,
                f"held {held.format()} of a required {required.format()}",
                soak_severity(shortfall, required, judged_on_load=judged_on_load),
                shortfall=shortfall,
            )
        )
    ceiling = step.maximum_time
    if ceiling is not None and held.seconds > ceiling.seconds:
        findings.append(
            Deviation(
                DeviationKind.LONG_SOAK,
                step.name,
                f"held {held.format()} against a maximum of {ceiling.format()}",
                Severity.MAJOR,
                shortfall=held - ceiling,
            )
        )
    return findings


def _rate_findings(segment: Segment, channel: Channel) -> list[Deviation]:
    step = segment.step
    limit = step.rate_limit()
    if limit.is_unlimited or segment.window is None:
        return []
    rate = channel.rate_per_hour(segment.window.start, segment.window.end)
    if rate is None or limit.allows(rate):
        return []
    kind = (
        DeviationKind.RATE_TOO_FAST
        if limit.maximum is not None and abs(rate) > limit.maximum
        else DeviationKind.RATE_TOO_SLOW
    )
    return [
        Deviation(
            kind,
            step.name,
            f"ramped at {abs(rate):.0f} F per hour",
            Severity.MAJOR,
        )
    ]


def _gap_findings(segments: tuple[Segment, ...], trace: Trace) -> list[Deviation]:
    findings: list[Deviation] = []
    for segment in segments:
        if segment.window is None:
            continue
        channel = trace.channel(segment.governing_key)
        for gap in channel.unbridgeable():
            if segment.window.contains(gap.start) or segment.window.contains(gap.end):
                findings.append(
                    Deviation(
                        DeviationKind.SENSOR_LOST,
                        segment.step.name,
                        f"{segment.governing_key} lost for {gap.length.format()}",
                        Severity.MAJOR,
                    )
                )
    return findings


def _over_temperature(segments: tuple[Segment, ...], trace: Trace) -> list[Deviation]:
    peaks = [s.step.setpoint for s in segments if s.step.setpoint is not None]
    if not peaks:
        return []
    ceiling = max(peaks, key=lambda t: t.degf) + OVER_TEMPERATURE_MARGIN
    findings: list[Deviation] = []
    for channel in trace.channels:
        if not channel.role.governs_the_cycle:
            continue
        peak = channel.peak()
        if peak is not None and peak.degf > ceiling.degf:
            findings.append(
                Deviation(
                    DeviationKind.OVER_TEMPERATURE,
                    channel.key,
                    f"reached {peak.format()} against a ceiling of {ceiling.format()}",
                    Severity.CRITICAL,
                    excess=peak.difference(ceiling),
                )
            )
    return findings


def evaluate(
    segments: tuple[Segment, ...],
    trace: Trace,
    *,
    load_sensors_expected: int = 0,
) -> tuple[Deviation, ...]:
    """Every finding against one run."""
    findings: list[Deviation] = []
    load_channels = trace.load_channels
    judged_on_load = bool(load_channels) and load_sensors_expected > 0

    if load_sensors_expected > len(load_channels):
        findings.append(
            Deviation(
                DeviationKind.NO_LOAD_SENSOR,
                "cycle",
                f"{len(load_channels)} load channels on the trace, "
                f"{load_sensors_expected} required",
                Severity.CRITICAL,
            )
        )

    for segment in segments:
        if segment.step.grades_temperature:
            findings.extend(_soak_findings(segment, judged_on_load=judged_on_load))
        else:
            channel = trace.channel(segment.governing_key)
            findings.extend(_rate_findings(segment, channel))

    findings.extend(_gap_findings(segments, trace))
    findings.extend(_over_temperature(segments, trace))

    if not ordered(segments):
        findings.append(
            Deviation(
                DeviationKind.OUT_OF_ORDER,
                "cycle",
                "the located steps do not run in the order the cycle writes them",
                Severity.CRITICAL,
            )
        )
    findings.sort(key=lambda d: (-d.severity.rank, d.step, d.kind.value))
    return tuple(findings)


def worst(findings: tuple[Deviation, ...]) -> Severity | None:
    if not findings:
        return None
    return max((d.severity for d in findings), key=lambda s: s.rank)


def blocking(findings: tuple[Deviation, ...]) -> tuple[Deviation, ...]:
    return tuple(d for d in findings if d.severity.blocks_certification)


def channel_roles_in(trace: Trace) -> set[ChannelRole]:
    return {c.role for c in trace.channels}
