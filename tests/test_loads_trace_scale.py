"""A trace the size a real one is.

A twelve hour cycle logged every five seconds is nearly nine thousand samples
per channel, and the deviation engine asks each channel for a reading at several
points per step. The first version of this module rescanned the whole channel on
every one of those, which was invisible on a four sample fixture and unusable on
a real run. These tests hold the shape that made it slow.
"""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from quenchline.loads.trace import Channel, ChannelRole, Sample, Trace
from quenchline.temperature import Temperature
from quenchline.timespan import Duration, minutes

STARTED = datetime(2025, 9, 22, 6, 0)
SAMPLES = 8640
STEP = 5.0


def long_channel(dropouts: set[int] | None = None) -> Channel:
    dropouts = dropouts or set()
    samples: list[Sample] = []
    for index in range(SAMPLES):
        elapsed = Duration(index * STEP)
        if index in dropouts:
            samples.append(Sample(elapsed, None))
            continue
        value = 95.0 + min(1455.0, index * 0.5)
        samples.append(Sample(elapsed, Temperature.fahrenheit(value)))
    return Channel("C1", ChannelRole.CONTROL, tuple(samples))


def test_a_long_channel_reads_at_any_point() -> None:
    channel = long_channel()
    middle = channel.at(Duration(SAMPLES * STEP / 2))
    assert middle is not None
    assert middle.degf > 1000.0


def test_reading_a_long_channel_many_times_stays_quick() -> None:
    channel = long_channel()
    started = time.perf_counter()
    for index in range(0, SAMPLES, 17):
        channel.at(Duration(index * STEP + 1.0))
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0


def test_the_readings_view_is_computed_once() -> None:
    channel = long_channel()
    assert channel.readings is channel.readings


def test_gaps_are_found_in_one_pass() -> None:
    channel = long_channel(dropouts={100, 101, 5000})
    started = time.perf_counter()
    gaps = channel.gaps()
    elapsed = time.perf_counter() - started
    assert len(gaps) == 2
    assert elapsed < 2.0


def test_a_run_of_dropouts_is_one_gap_not_several() -> None:
    channel = long_channel(dropouts={200, 201, 202, 203})
    gaps = channel.gaps()
    assert len(gaps) == 1
    assert gaps[0].length.seconds == pytest.approx(STEP * 5)


def test_a_dropout_at_the_very_start_is_not_a_gap() -> None:
    channel = long_channel(dropouts={0, 1})
    assert channel.gaps() == ()


def test_a_dropout_at_the_very_end_is_not_a_gap() -> None:
    channel = long_channel(dropouts={SAMPLES - 1})
    assert channel.gaps() == ()


def test_a_short_gap_is_still_bridged_on_a_long_channel() -> None:
    channel = long_channel(dropouts={4000})
    value = channel.at(Duration(4000 * STEP))
    assert value is not None


def test_a_long_gap_is_still_a_hole_on_a_long_channel() -> None:
    channel = long_channel(dropouts=set(range(4000, 4030)))
    assert channel.at(Duration(4010 * STEP)) is None


def test_peak_and_rate_work_on_a_long_channel() -> None:
    channel = long_channel()
    peak = channel.peak()
    assert peak is not None
    assert peak.degf == pytest.approx(1550.0)
    rate = channel.rate_per_hour(minutes(0), minutes(30))
    assert rate is not None
    assert rate > 0


def test_a_whole_trace_of_long_channels_reports_its_bounds() -> None:
    trace = Trace(
        STARTED,
        (
            long_channel(),
            Channel(
                "L1",
                ChannelRole.LOAD,
                tuple(
                    Sample(Duration(index * STEP), Temperature.fahrenheit(90.0 + index * 0.5))
                    for index in range(SAMPLES)
                ),
            ),
        ),
    )
    assert trace.duration.seconds == pytest.approx((SAMPLES - 1) * STEP)
    coldest = trace.coldest_at(Duration(1000.0), ChannelRole.CONTROL)
    assert coldest is not None
