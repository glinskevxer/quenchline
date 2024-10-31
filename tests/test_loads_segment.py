from __future__ import annotations

from datetime import datetime

import pytest

from quenchline.errors import ValidationError
from quenchline.loads.segment import (
    Window,
    governing_channel,
    longest_run_in_band,
    missing,
    ordered,
    segment,
    unlocatable_kinds,
)
from quenchline.loads.trace import Channel, ChannelRole, Trace
from quenchline.recipes.cycle import Recipe
from quenchline.recipes.steps import StepKind, quench, ramp, soak, temper
from quenchline.temperature import Temperature, degf
from quenchline.timespan import minutes
from quenchline.tolerance import Band

STARTED = datetime(2024, 11, 4, 7, 0)
BAND = Band.symmetric(Temperature.fahrenheit(1550), degf(25))

HEAT = ramp("heat", Temperature.fahrenheit(1550), maximum_per_hour=800.0)
AUSTENITISE = soak("austenitise", Temperature.fahrenheit(1550), degf(25), minutes(60))
OIL = quench("oil quench", "AAA fast oil", minutes(0.5))
TEMPERING = temper("temper", Temperature.fahrenheit(400), degf(15), minutes(120))


def channel(
    key: str,
    readings: list[tuple[float, float | None]],
    role: ChannelRole = ChannelRole.CONTROL,
) -> Channel:
    return Channel.of(key, role, [(minutes(m), v) for m, v in readings])


def trace(*channels: Channel) -> Trace:
    return Trace(STARTED, channels)


def recipe(load_sensors: int = 0) -> Recipe:
    return Recipe(
        "HT-4140-Q", "C", "4140 harden", (HEAT, AUSTENITISE, OIL, TEMPERING), load_sensors
    )


def test_window_validation_and_arithmetic() -> None:
    window = Window(minutes(10), minutes(70))
    assert window.length == minutes(60)
    assert window.contains(minutes(40))
    assert not window.contains(minutes(80))
    assert not window.is_empty
    with pytest.raises(ValidationError):
        Window(minutes(70), minutes(10))


def test_a_zero_length_window_is_empty() -> None:
    assert Window(minutes(10), minutes(10)).is_empty


def test_the_control_channel_governs_when_there_are_no_load_sensors() -> None:
    t = trace(channel("C1", [(0, 100.0), (60, 1550.0)]))
    assert governing_channel(recipe(), t).key == "C1"


def test_a_trace_with_no_control_channel_is_refused() -> None:
    t = trace(channel("L1", [(0, 100.0)], ChannelRole.LOAD))
    with pytest.raises(ValidationError):
        governing_channel(recipe(), t)


def test_the_coldest_load_sensor_governs_when_the_cycle_calls_for_them() -> None:
    t = trace(
        channel("C1", [(0, 100.0), (60, 1560.0)]),
        channel("L1", [(0, 90.0), (60, 1555.0)], ChannelRole.LOAD),
        channel("L2", [(0, 95.0), (60, 1540.0)], ChannelRole.LOAD),
    )
    assert governing_channel(recipe(load_sensors=2), t).key == "L2"


def test_a_cycle_needing_load_sensors_refuses_a_trace_without_them() -> None:
    t = trace(channel("C1", [(0, 100.0), (60, 1550.0)]))
    with pytest.raises(ValidationError):
        governing_channel(recipe(load_sensors=2), t)


def test_the_longest_run_in_band_is_found() -> None:
    c = channel(
        "C1",
        [(0, 100.0), (10, 1540.0), (20, 1400.0), (30, 1545.0), (90, 1552.0), (100, 1400.0)],
    )
    window = longest_run_in_band(c, BAND)
    assert window is not None
    assert window.start == minutes(30)
    assert window.end == minutes(90)


def test_the_first_run_is_not_taken_when_a_longer_one_follows() -> None:
    c = channel("C1", [(0, 1545.0), (5, 1400.0), (10, 1545.0), (70, 1550.0), (80, 1400.0)])
    window = longest_run_in_band(c, BAND)
    assert window is not None
    assert window.start == minutes(10)


def test_a_run_that_reaches_the_end_of_the_trace_still_counts() -> None:
    c = channel("C1", [(0, 100.0), (10, 1545.0), (90, 1552.0)])
    window = longest_run_in_band(c, BAND)
    assert window is not None
    assert window.end == minutes(90)


def test_a_channel_that_never_reached_the_band_has_no_run() -> None:
    c = channel("C1", [(0, 100.0), (60, 1200.0)])
    assert longest_run_in_band(c, BAND) is None


def test_a_dropout_breaks_a_run() -> None:
    c = channel("C1", [(0, 1545.0), (10, None), (20, 1550.0), (30, 1552.0)])
    window = longest_run_in_band(c, BAND)
    assert window is not None
    assert window.start == minutes(20)


def test_segmenting_locates_the_graded_steps_only() -> None:
    c = channel(
        "C1",
        [
            (0, 100.0),
            (30, 1545.0),
            (120, 1552.0),
            (130, 700.0),
            (140, 402.0),
            (300, 398.0),
        ],
    )
    segments = segment(recipe(), trace(c))
    assert [s.step.name for s in segments] == [
        "heat",
        "austenitise",
        "oil quench",
        "temper",
    ]
    assert not segments[0].found
    assert segments[1].found
    assert not segments[2].found
    assert segments[3].found


def test_a_located_segment_reports_its_window() -> None:
    c = channel("C1", [(0, 100.0), (30, 1545.0), (120, 1552.0)])
    segments = segment(recipe(), trace(c))
    austenitise = segments[1]
    assert austenitise.length == minutes(90)
    assert "austenitise: 0:30 to 2:00" in str(austenitise)


def test_an_unlocated_segment_says_so() -> None:
    c = channel("C1", [(0, 100.0), (60, 1200.0)])
    segments = segment(recipe(), trace(c))
    assert "not found on the trace" in str(segments[1])
    assert [s.name for s in missing(segments)] == ["austenitise", "temper"]


def test_segments_carry_the_channel_they_were_judged_on() -> None:
    t = trace(
        channel("C1", [(0, 100.0), (60, 1550.0)]),
        channel("L1", [(0, 90.0), (60, 1540.0)], ChannelRole.LOAD),
    )
    segments = segment(recipe(load_sensors=1), t)
    assert all(s.governing_key == "L1" for s in segments)


def test_ordered_accepts_a_normal_cycle() -> None:
    c = channel(
        "C1",
        [(0, 100.0), (30, 1545.0), (120, 1552.0), (130, 700.0), (140, 402.0), (300, 398.0)],
    )
    assert ordered(segment(recipe(), trace(c)))


def test_ordered_rejects_a_trace_run_backwards() -> None:
    c = channel(
        "C1",
        [(0, 402.0), (100, 398.0), (110, 700.0), (120, 1545.0), (240, 1552.0)],
    )
    assert not ordered(segment(recipe(), trace(c)))


def test_the_kinds_that_are_never_located() -> None:
    kinds = unlocatable_kinds()
    assert StepKind.QUENCH in kinds
    assert StepKind.SOAK not in kinds
