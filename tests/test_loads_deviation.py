from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pytest

from quenchline.loads.deviation import (
    DeviationKind,
    Severity,
    blocking,
    channel_roles_in,
    evaluate,
    soak_severity,
    worst,
)
from quenchline.loads.segment import Segment, segment
from quenchline.loads.trace import Channel, ChannelRole, Trace
from quenchline.recipes.cycle import Recipe
from quenchline.recipes.steps import Step, StepKind, ramp, soak
from quenchline.temperature import Temperature, degf
from quenchline.timespan import minutes

STARTED = datetime(2024, 11, 12, 7, 0)
HEAT = ramp("heat", Temperature.fahrenheit(1550), maximum_per_hour=800.0)
AUSTENITISE = soak("austenitise", Temperature.fahrenheit(1550), degf(25), minutes(60))


Readings = Sequence[tuple[float, float | None]]


def channel(
    key: str,
    readings: Readings,
    role: ChannelRole = ChannelRole.CONTROL,
) -> Channel:
    return Channel.of(key, role, [(minutes(m), v) for m, v in readings])


def run(
    readings: Readings,
    *,
    load_sensors: int = 0,
    extra: tuple[Channel, ...] = (),
    steps: tuple[Step, ...] = (HEAT, AUSTENITISE),
) -> tuple[tuple[Segment, ...], Trace, int]:
    recipe = Recipe("HT-4140-Q", "C", "4140 harden", steps, load_sensors)
    channels = (channel("C1", readings), *extra)
    trace = Trace(STARTED, channels)
    return segment(recipe, trace), trace, load_sensors


GOOD: Readings = [(0.0, 100.0), (30.0, 1545.0), (95.0, 1552.0)]


def test_severity_ranking() -> None:
    assert Severity.CRITICAL.rank > Severity.MAJOR.rank > Severity.MINOR.rank
    assert Severity.CRITICAL.blocks_certification
    assert Severity.MAJOR.blocks_certification
    assert not Severity.MINOR.blocks_certification


def test_a_clean_run_has_no_findings() -> None:
    segments, trace, expected = run(GOOD)
    findings = evaluate(segments, trace, load_sensors_expected=expected)
    assert findings == ()
    assert worst(findings) is None
    assert blocking(findings) == ()


def test_a_soak_that_never_happened_is_critical() -> None:
    segments, trace, expected = run([(0.0, 100.0), (60.0, 1200.0)])
    findings = evaluate(segments, trace, load_sensors_expected=expected)
    assert findings[0].kind is DeviationKind.STEP_NOT_REACHED
    assert findings[0].severity is Severity.CRITICAL


def test_a_soak_a_couple_of_minutes_short_is_minor_on_the_control_sensor() -> None:
    segments, trace, expected = run([(0.0, 100.0), (30.0, 1545.0), (87.0, 1552.0)])
    findings = evaluate(segments, trace, load_sensors_expected=expected)
    assert findings[0].kind is DeviationKind.SHORT_SOAK
    assert findings[0].severity is Severity.MINOR
    assert findings[0].shortfall == minutes(3)


def test_the_same_shortfall_is_worse_when_the_load_was_being_judged() -> None:
    load = channel("L1", [(0.0, 90.0), (30.0, 1545.0), (87.0, 1552.0)], ChannelRole.LOAD)
    segments, trace, expected = run(GOOD, load_sensors=1, extra=(load,))
    findings = evaluate(segments, trace, load_sensors_expected=expected)
    assert findings[0].severity is Severity.MAJOR


def test_a_quarter_of_the_soak_missing_is_critical() -> None:
    segments, trace, expected = run([(0.0, 100.0), (30.0, 1545.0), (70.0, 1552.0)])
    findings = evaluate(segments, trace, load_sensors_expected=expected)
    assert findings[0].severity is Severity.CRITICAL


def test_soak_severity_direct() -> None:
    assert soak_severity(minutes(2), minutes(60), judged_on_load=False) is Severity.MINOR
    assert soak_severity(minutes(2), minutes(60), judged_on_load=True) is Severity.MAJOR
    assert soak_severity(minutes(10), minutes(60), judged_on_load=False) is Severity.MAJOR
    assert soak_severity(minutes(10), minutes(60), judged_on_load=True) is Severity.CRITICAL
    assert soak_severity(minutes(30), minutes(60), judged_on_load=False) is Severity.CRITICAL


def test_a_soak_held_too_long_is_flagged() -> None:
    long_step = Step(
        StepKind.SOAK,
        "austenitise",
        setpoint=Temperature.fahrenheit(1550),
        tolerance=degf(25),
        minimum_time=minutes(60),
        maximum_time=minutes(90),
    )
    segments, trace, expected = run(
        [(0.0, 100.0), (30.0, 1545.0), (150.0, 1552.0)], steps=(HEAT, long_step)
    )
    findings = evaluate(segments, trace, load_sensors_expected=expected)
    kinds = {f.kind for f in findings}
    assert DeviationKind.LONG_SOAK in kinds


def test_a_missing_load_sensor_is_critical() -> None:
    segments, trace, _ = run(GOOD)
    findings = evaluate(segments, trace, load_sensors_expected=2)
    kinds = {f.kind for f in findings}
    assert DeviationKind.NO_LOAD_SENSOR in kinds


def test_an_over_temperature_excursion_is_critical() -> None:
    segments, trace, expected = run(
        [(0.0, 100.0), (30.0, 1545.0), (60.0, 1650.0), (95.0, 1552.0)]
    )
    findings = evaluate(segments, trace, load_sensors_expected=expected)
    over = [f for f in findings if f.kind is DeviationKind.OVER_TEMPERATURE]
    assert over
    assert over[0].excess is not None
    assert over[0].excess.degf == pytest.approx(50.0)


def test_a_peak_inside_the_margin_is_not_an_over_temperature() -> None:
    segments, trace, expected = run(
        [(0.0, 100.0), (30.0, 1545.0), (60.0, 1595.0), (95.0, 1552.0)]
    )
    findings = evaluate(segments, trace, load_sensors_expected=expected)
    assert not [f for f in findings if f.kind is DeviationKind.OVER_TEMPERATURE]


def test_a_lost_sensor_during_a_soak_is_reported() -> None:
    segments, trace, expected = run(
        [(0.0, 100.0), (30.0, 1545.0), (50.0, None), (70.0, 1548.0), (140.0, 1552.0)]
    )
    findings = evaluate(segments, trace, load_sensors_expected=expected)
    lost = [f for f in findings if f.kind is DeviationKind.SENSOR_LOST]
    assert lost
    assert lost[0].severity is Severity.MAJOR


def test_findings_come_back_worst_first() -> None:
    segments, trace, _ = run([(0.0, 100.0), (30.0, 1545.0), (87.0, 1552.0)])
    findings = evaluate(segments, trace, load_sensors_expected=2)
    assert findings[0].severity is Severity.CRITICAL
    assert worst(findings) is Severity.CRITICAL
    assert len(blocking(findings)) == 1


def test_finding_text() -> None:
    segments, trace, expected = run([(0.0, 100.0), (60.0, 1200.0)])
    findings = evaluate(segments, trace, load_sensors_expected=expected)
    assert str(findings[0]).startswith("[critical] austenitise:")


def test_channel_roles_in_a_trace() -> None:
    load = channel("L1", [(0.0, 90.0), (95.0, 1545.0)], ChannelRole.LOAD)
    _, trace, _ = run(GOOD, load_sensors=1, extra=(load,))
    assert channel_roles_in(trace) == {ChannelRole.CONTROL, ChannelRole.LOAD}
