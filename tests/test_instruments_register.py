from __future__ import annotations

from datetime import date

import pytest

from quenchline.calendar_rules import Interval
from quenchline.errors import ConflictError, NotFoundError
from quenchline.identity import InstrumentTag
from quenchline.instruments.calibration import CalibrationCheck, InstrumentCalibration
from quenchline.instruments.record import Instrument, InstrumentStatus
from quenchline.instruments.register import build_register
from quenchline.instruments.types import (
    Accuracy,
    InstrumentClass,
    InstrumentFunction,
    Readout,
    Span,
)
from quenchline.temperature import Scale, Temperature, TemperatureDelta

SPAN = Span(Temperature.fahrenheit(0), Temperature.fahrenheit(2400))
TOLERANCE = TemperatureDelta(2.0, Scale.FAHRENHEIT)
WHOLE = TemperatureDelta(1.0, Scale.FAHRENHEIT)
TODAY = date(2024, 9, 1)
WORKING = Temperature.fahrenheit(1550)


def cal(
    number: str, tag: str, performed: date, found: float, left: float | None = None
) -> InstrumentCalibration:
    check = CalibrationCheck(
        Temperature.fahrenheit(1550.0),
        Temperature.fahrenheit(found),
        None if left is None else Temperature.fahrenheit(left),
    )
    return InstrumentCalibration(
        number, InstrumentTag.parse(tag), performed, (check,), TOLERANCE
    )


def instrument(tag: str, **changes: object) -> Instrument:
    base: dict[str, object] = {
        "tag": InstrumentTag.parse(tag),
        "function": InstrumentFunction.CONTROLLING,
        "span": SPAN,
        "accuracy": Accuracy(0.1, InstrumentClass.PERCENT_OF_READING),
        "resolution": WHOLE,
        "readout": Readout.DIGITAL,
        "interval": Interval.months(6),
    }
    base.update(changes)
    return Instrument(**base)  # type: ignore[arg-type]


def test_add_get_and_conflict() -> None:
    register = build_register([instrument("IC-04")])
    assert len(register) == 1
    assert "IC-04" in register
    assert register.get("IC-04").tag.serial == 4
    with pytest.raises(ConflictError):
        register.add(instrument("IC-04"))
    with pytest.raises(NotFoundError):
        register.get("IC-09")
    with pytest.raises(NotFoundError):
        register.replace(instrument("IC-09"))


def test_filing_a_calibration_updates_the_register() -> None:
    register = build_register([instrument("IC-04")])
    updated = register.file_calibration(cal("CAL-1", "IC-04", date(2024, 6, 10), 1550.5))
    assert updated.latest is not None
    assert register.get("IC-04").due_on() == date(2024, 12, 10)


def test_filing_a_calibration_for_an_unknown_instrument_is_refused() -> None:
    register = build_register([instrument("IC-04")])
    with pytest.raises(NotFoundError):
        register.file_calibration(cal("CAL-1", "IC-09", date(2024, 6, 10), 1550.5))


def test_listing_helpers() -> None:
    register = build_register(
        [
            instrument("IC-04"),
            instrument("FT-01", function=InstrumentFunction.FIELD_TEST),
            instrument("IC-09", status=InstrumentStatus.OUT_OF_SERVICE),
        ]
    )
    assert [str(i.tag) for i in register.all()] == ["FT-01", "IC-04", "IC-09"]
    assert [str(i.tag) for i in register.in_service()] == ["FT-01", "IC-04"]
    assert [str(i.tag) for i in register.with_function(InstrumentFunction.FIELD_TEST)] == [
        "FT-01"
    ]


def test_a_never_calibrated_instrument_sorts_first_and_counts_as_overdue() -> None:
    register = build_register([instrument("IC-04"), instrument("IC-09")])
    register.file_calibration(cal("CAL-1", "IC-09", date(2024, 6, 10), 1550.5))
    schedule = register.schedule(TODAY)
    assert schedule[0].never_calibrated
    assert str(schedule[0].instrument.tag) == "IC-04"
    assert schedule[0].overdue
    assert not schedule[1].overdue


def test_retired_instruments_drop_off_the_schedule() -> None:
    register = build_register([instrument("IC-04", status=InstrumentStatus.RETIRED)])
    assert register.schedule(TODAY) == []


def test_overdue_respects_grace() -> None:
    register = build_register([instrument("IC-04")])
    register.file_calibration(cal("CAL-1", "IC-04", date(2024, 1, 10), 1550.5))
    assert len(register.overdue(TODAY)) == 1
    assert register.overdue(TODAY, grace=60) == []


def test_due_within_looks_forward_only() -> None:
    register = build_register([instrument("IC-04")])
    register.file_calibration(cal("CAL-1", "IC-04", date(2024, 6, 10), 1550.5))
    assert register.due_within(TODAY, 120) != []
    assert register.due_within(TODAY, 30) == []
    assert register.due_within(date(2025, 1, 1), 30) == []


def test_days_left_is_signed() -> None:
    register = build_register([instrument("IC-04")])
    register.file_calibration(cal("CAL-1", "IC-04", date(2024, 6, 10), 1550.5))
    entry = register.schedule(TODAY)[0]
    assert entry.days_left == 100
    late = register.schedule(date(2025, 1, 1))[0]
    assert late.days_left is not None
    assert late.days_left < 0


def test_usable_needs_service_calibration_and_capability() -> None:
    register = build_register(
        [
            instrument("IC-04"),
            instrument("IC-05", resolution=TemperatureDelta(5.0, Scale.FAHRENHEIT)),
            instrument("IC-06", status=InstrumentStatus.OUT_OF_SERVICE),
        ]
    )
    for tag in ("IC-04", "IC-05", "IC-06"):
        register.file_calibration(cal(f"CAL-{tag}", tag, date(2024, 6, 10), 1550.5))
    usable = register.usable(InstrumentFunction.CONTROLLING, WORKING, TODAY)
    assert [str(i.tag) for i in usable] == ["IC-04"]


def test_an_uncalibrated_instrument_is_never_usable() -> None:
    register = build_register([instrument("IC-04")])
    assert register.usable(InstrumentFunction.CONTROLLING, WORKING, TODAY) == []


def test_suspect_work_lists_only_the_bad_calibrations() -> None:
    register = build_register([instrument("IC-04")])
    register.file_calibration(cal("CAL-1", "IC-04", date(2023, 12, 1), 1550.5))
    register.file_calibration(cal("CAL-2", "IC-04", date(2024, 6, 10), 1556.0, 1550.2))
    windows = register.suspect_work("IC-04")
    assert windows == [("CAL-2", date(2023, 12, 1), date(2024, 6, 10))]


def test_suspect_work_is_empty_for_a_clean_history() -> None:
    register = build_register([instrument("IC-04")])
    register.file_calibration(cal("CAL-1", "IC-04", date(2024, 6, 10), 1550.5))
    assert register.suspect_work("IC-04") == []
