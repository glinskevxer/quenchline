from __future__ import annotations

from datetime import datetime

import pytest

from quenchline.errors import NotFoundError, ValidationError
from quenchline.loads.trace import Channel, ChannelRole, Gap, Sample, Trace
from quenchline.temperature import Temperature
from quenchline.timespan import minutes

STARTED = datetime(2024, 11, 4, 6, 30)


def channel(
    key: str,
    readings: list[tuple[float, float | None]],
    role: ChannelRole = ChannelRole.LOAD,
) -> Channel:
    return Channel.of(key, role, [(minutes(m), v) for m, v in readings])


def test_channel_roles() -> None:
    assert ChannelRole.LOAD.is_load
    assert not ChannelRole.CONTROL.is_load
    assert ChannelRole.CONTROL.governs_the_cycle
    assert ChannelRole.LOAD.governs_the_cycle
    assert not ChannelRole.AMBIENT.governs_the_cycle


def test_a_sample_knows_whether_it_read() -> None:
    good = Sample(minutes(1), Temperature.fahrenheit(1550))
    bad = Sample(minutes(2), None)
    assert good.is_reading
    assert good.temperature().degf == pytest.approx(1550.0)
    assert not bad.is_reading
    with pytest.raises(ValidationError):
        bad.temperature()


def test_channel_validation() -> None:
    with pytest.raises(ValidationError):
        Channel.of("  ", ChannelRole.LOAD, [(minutes(0), 100.0)])
    with pytest.raises(ValidationError):
        Channel.of("A", ChannelRole.LOAD, [])
    with pytest.raises(ValidationError):
        Channel(
            "A",
            ChannelRole.LOAD,
            (
                Sample(minutes(10), Temperature.fahrenheit(100)),
                Sample(minutes(1), Temperature.fahrenheit(100)),
            ),
        )


def test_channel_bounds() -> None:
    c = channel("A", [(0, 100.0), (30, 1550.0), (60, 1550.0)])
    assert c.start == minutes(0)
    assert c.end == minutes(60)
    assert c.duration == minutes(60)
    assert c.has_data


def test_reading_exactly_on_a_sample() -> None:
    c = channel("A", [(0, 100.0), (30, 1550.0)])
    value = c.at(minutes(30))
    assert value is not None
    assert value.degf == pytest.approx(1550.0)


def test_reading_between_samples_interpolates() -> None:
    c = channel("A", [(0, 100.0), (30, 1600.0)])
    value = c.at(minutes(15))
    assert value is not None
    assert value.degf == pytest.approx(850.0)


def test_reading_outside_the_channel_is_nothing() -> None:
    c = channel("A", [(10, 100.0), (30, 1600.0)])
    assert c.at(minutes(5)) is None
    assert c.at(minutes(40)) is None


def test_a_short_gap_is_bridged() -> None:
    c = channel("A", [(0, 1500.0), (0.5, None), (1, 1600.0)])
    assert len(c.gaps()) == 1
    assert c.unbridgeable() == ()
    value = c.at(minutes(0.5))
    assert value is not None
    assert value.degf == pytest.approx(1550.0)


def test_a_long_gap_is_not_bridged() -> None:
    c = channel("A", [(0, 1500.0), (10, None), (20, 1600.0)])
    assert len(c.unbridgeable()) == 1
    assert c.at(minutes(10)) is None


def test_the_bridge_limit_can_be_widened() -> None:
    c = channel("A", [(0, 1500.0), (10, None), (20, 1600.0)])
    assert c.at(minutes(10), bridge=minutes(30)) is not None


def test_a_gap_reports_its_length_and_span() -> None:
    gap = Gap(minutes(10), minutes(25))
    assert gap.length == minutes(15)
    assert gap.contains(minutes(15))
    assert not gap.contains(minutes(10))
    assert gap.bridgeable(minutes(20))
    assert not gap.bridgeable(minutes(5))


def test_consecutive_readings_are_not_a_gap() -> None:
    c = channel("A", [(0, 1500.0), (10, 1550.0), (20, 1600.0)])
    assert c.gaps() == ()


def test_peak_and_trough() -> None:
    c = channel("A", [(0, 100.0), (30, 1600.0), (60, 800.0)])
    peak = c.peak()
    trough = c.trough()
    assert peak is not None and peak.degf == pytest.approx(1600.0)
    assert trough is not None and trough.degf == pytest.approx(100.0)


def test_a_channel_of_nothing_but_dropouts_reports_no_data() -> None:
    c = channel("A", [(0, None), (10, None)])
    assert not c.has_data
    assert c.peak() is None
    assert c.trough() is None
    assert c.at(minutes(5)) is None


def test_rate_per_hour() -> None:
    c = channel("A", [(0, 100.0), (60, 700.0)])
    assert c.rate_per_hour(minutes(0), minutes(60)) == pytest.approx(600.0)
    assert c.rate_per_hour(minutes(0), minutes(30)) == pytest.approx(600.0)


def test_rate_over_a_hole_is_unknown() -> None:
    c = channel("A", [(0, 100.0), (10, None), (60, 700.0)])
    assert c.rate_per_hour(minutes(5), minutes(30)) is None


def test_a_backwards_interval_is_refused() -> None:
    c = channel("A", [(0, 100.0), (60, 700.0)])
    with pytest.raises(ValidationError):
        c.rate_per_hour(minutes(60), minutes(0))


def test_between_selects_readings_inclusively() -> None:
    c = channel("A", [(0, 100.0), (10, 200.0), (20, 300.0), (30, 400.0)])
    picked = c.between(minutes(10), minutes(20))
    assert [s.elapsed for s in picked] == [minutes(10), minutes(20)]


def test_trace_validation() -> None:
    with pytest.raises(ValidationError):
        Trace(STARTED, ())
    with pytest.raises(ValidationError):
        Trace(STARTED, (channel("A", [(0, 100.0)]), channel("A", [(0, 100.0)])))


def test_trace_lookup_and_roles() -> None:
    trace = Trace(
        STARTED,
        (
            channel("C1", [(0, 100.0), (60, 1550.0)], ChannelRole.CONTROL),
            channel("L1", [(0, 90.0), (60, 1540.0)]),
            channel("L2", [(0, 95.0), (60, 1545.0)]),
        ),
    )
    assert trace.keys == ("C1", "L1", "L2")
    assert trace.channel("L1").role is ChannelRole.LOAD
    assert len(trace.load_channels) == 2
    assert trace.duration == minutes(60)
    with pytest.raises(NotFoundError):
        trace.channel("nope")


def test_coldest_and_hottest_across_a_role() -> None:
    trace = Trace(
        STARTED,
        (
            channel("L1", [(0, 90.0), (60, 1540.0)]),
            channel("L2", [(0, 95.0), (60, 1560.0)]),
        ),
    )
    coldest = trace.coldest_at(minutes(60), ChannelRole.LOAD)
    hottest = trace.hottest_at(minutes(60), ChannelRole.LOAD)
    assert coldest is not None and coldest.degf == pytest.approx(1540.0)
    assert hottest is not None and hottest.degf == pytest.approx(1560.0)


def test_a_role_with_no_readings_gives_nothing() -> None:
    trace = Trace(STARTED, (channel("L1", [(0, 90.0), (60, 1540.0)]),))
    assert trace.coldest_at(minutes(60), ChannelRole.CONTROL) is None
    assert trace.hottest_at(minutes(60), ChannelRole.CONTROL) is None
