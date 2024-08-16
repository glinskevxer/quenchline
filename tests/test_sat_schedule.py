from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import ValidationError
from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.identity import FurnaceTag, SensorTag
from quenchline.sat.model import SatReading, SatTest
from quenchline.sat.schedule import SatHistory
from quenchline.temperature import Scale, Temperature, TemperatureDelta

FURNACE = FurnaceTag.parse("HT-04")
SETPOINT = Temperature.fahrenheit(1550)
ZERO = TemperatureDelta(0.0, Scale.FAHRENHEIT)


def side(indicated: float, tag: str) -> SatReading:
    return SatReading(Temperature.fahrenheit(indicated), ZERO, ZERO, SensorTag.parse(tag))


def sat(number: str, performed: date, system: float, furnace: FurnaceTag = FURNACE) -> SatTest:
    return SatTest(
        number,
        furnace,
        performed,
        SETPOINT,
        side(system, "TC-01"),
        side(1550.0, "TC-99"),
    )


def history(instrumentation: InstrumentationType = InstrumentationType.D) -> SatHistory:
    return SatHistory(FURNACE, FurnaceClass.CLASS_3, instrumentation)


def test_an_empty_history_is_never_in_date() -> None:
    h = history()
    assert h.is_empty
    assert h.latest() is None
    assert h.latest_pass() is None
    assert not h.in_date(date(2024, 8, 1))
    due = h.due(date(2024, 8, 1))
    assert due.never_tested
    assert due.overdue


def test_a_test_for_another_furnace_is_refused() -> None:
    h = history()
    with pytest.raises(ValidationError):
        h.file(sat("SAT-1", date(2024, 7, 1), 1550.0, FurnaceTag.parse("HT-09")))


def test_the_same_test_cannot_be_filed_twice() -> None:
    h = history()
    h.file(sat("SAT-1", date(2024, 7, 1), 1550.0))
    with pytest.raises(ValidationError):
        h.file(sat("SAT-1", date(2024, 8, 1), 1550.0))


def test_filing_keeps_the_history_in_date_order() -> None:
    h = history()
    h.file(sat("SAT-2", date(2024, 8, 1), 1550.0))
    h.file(sat("SAT-1", date(2024, 7, 1), 1550.0))
    assert [r.test.number for r in h.results] == ["SAT-1", "SAT-2"]


def test_a_passing_test_puts_the_furnace_in_date() -> None:
    h = history()
    h.file(sat("SAT-1", date(2024, 7, 1), 1550.0))
    assert h.in_date(date(2024, 7, 20))
    assert not h.in_date(date(2024, 9, 1))


def test_the_due_date_follows_the_instrumentation_interval() -> None:
    fast = history(InstrumentationType.E)
    fast.file(sat("SAT-1", date(2024, 7, 1), 1550.0))
    slow = history(InstrumentationType.A)
    slow.file(sat("SAT-1", date(2024, 7, 1), 1550.0))
    assert fast.due(date(2024, 7, 5)).due == date(2024, 8, 1)
    assert slow.due(date(2024, 7, 5)).due == date(2024, 10, 1)


def test_a_failure_takes_the_furnace_out_of_date_immediately() -> None:
    h = history()
    h.file(sat("SAT-1", date(2024, 7, 1), 1550.0))
    h.file(sat("SAT-2", date(2024, 7, 20), 1570.0))
    assert not h.in_date(date(2024, 7, 21))


def test_the_due_date_still_hangs_off_the_last_pass() -> None:
    h = history()
    h.file(sat("SAT-1", date(2024, 7, 1), 1550.0))
    h.file(sat("SAT-2", date(2024, 7, 20), 1570.0))
    assert h.due(date(2024, 7, 21)).last_passed == date(2024, 7, 1)


def test_consecutive_passes_reset_on_a_failure() -> None:
    h = history()
    for index in range(3):
        h.file(sat(f"SAT-{index}", date(2024, 1 + index, 1), 1550.0))
    assert h.consecutive_passes() == 3
    h.file(sat("SAT-bad", date(2024, 5, 1), 1570.0))
    assert h.consecutive_passes() == 0


def test_a_run_of_clean_tests_stretches_the_interval() -> None:
    h = history(InstrumentationType.D)
    assert h.interval().count == 1
    for index in range(4):
        h.file(sat(f"SAT-{index}", date(2024, 1 + index, 1), 1550.0))
    assert h.interval().count == 2


def test_the_stretch_is_capped() -> None:
    h = history(InstrumentationType.A)
    for index in range(8):
        h.file(sat(f"SAT-{index}", date(2024, 1 + index, 1), 1550.0))
    assert h.interval().count == 6


def test_grace_delays_the_overdue_flag() -> None:
    h = history()
    h.file(sat("SAT-1", date(2024, 7, 1), 1550.0))
    assert h.due(date(2024, 8, 5)).overdue
    assert not h.due(date(2024, 8, 5), grace=10).overdue
    assert h.in_date(date(2024, 8, 5), grace=10)


def test_days_left_is_signed() -> None:
    h = history()
    h.file(sat("SAT-1", date(2024, 7, 1), 1550.0))
    assert h.due(date(2024, 7, 20)).days_left == 12
    late = h.due(date(2024, 9, 1)).days_left
    assert late is not None
    assert late < 0


def test_a_passing_test_throws_nothing_into_doubt() -> None:
    h = history()
    good = h.file(sat("SAT-1", date(2024, 7, 1), 1550.0))
    assert h.failure_window(good) is None


def test_a_failure_reaches_back_to_the_last_pass() -> None:
    h = history()
    h.file(sat("SAT-1", date(2024, 5, 1), 1550.0))
    bad = h.file(sat("SAT-2", date(2024, 7, 1), 1570.0))
    assert h.failure_window(bad) == (date(2024, 5, 1), date(2024, 7, 1))


def test_a_failure_reaches_past_intervening_failures() -> None:
    h = history()
    h.file(sat("SAT-1", date(2024, 5, 1), 1550.0))
    h.file(sat("SAT-2", date(2024, 6, 1), 1570.0))
    bad = h.file(sat("SAT-3", date(2024, 7, 1), 1580.0))
    assert h.failure_window(bad) == (date(2024, 5, 1), date(2024, 7, 1))


def test_a_first_ever_failure_claims_only_its_own_day() -> None:
    h = history()
    bad = h.file(sat("SAT-1", date(2024, 7, 1), 1570.0))
    assert h.failure_window(bad) == (date(2024, 7, 1), date(2024, 7, 1))


def test_open_failures_are_the_ones_since_the_last_pass() -> None:
    h = history()
    h.file(sat("SAT-1", date(2024, 5, 1), 1550.0))
    h.file(sat("SAT-2", date(2024, 6, 1), 1570.0))
    h.file(sat("SAT-3", date(2024, 7, 1), 1580.0))
    assert [r.test.number for r in h.open_failures()] == ["SAT-2", "SAT-3"]


def test_a_later_pass_closes_them() -> None:
    h = history()
    h.file(sat("SAT-1", date(2024, 6, 1), 1570.0))
    h.file(sat("SAT-2", date(2024, 7, 1), 1550.0))
    assert h.open_failures() == []
