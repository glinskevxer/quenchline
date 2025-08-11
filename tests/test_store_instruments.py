from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest

from quenchline.calendar_rules import DueRule, Interval
from quenchline.errors import ConflictError, NotFoundError
from quenchline.identity import InstrumentTag
from quenchline.instruments.calibration import (
    CalibrationCheck,
    CalibrationVerdict,
    InstrumentCalibration,
)
from quenchline.instruments.record import Instrument, InstrumentStatus
from quenchline.instruments.types import (
    Accuracy,
    InstrumentClass,
    InstrumentFunction,
    Readout,
    Span,
)
from quenchline.store.database import Database
from quenchline.store.instruments import InstrumentRepository
from quenchline.temperature import Scale, Temperature, TemperatureDelta

SPAN = Span(Temperature.fahrenheit(0), Temperature.fahrenheit(2400))
TOLERANCE = TemperatureDelta(2.0, Scale.FAHRENHEIT)


@pytest.fixture()
def repo() -> Iterator[InstrumentRepository]:
    with Database.in_memory() as database:
        yield InstrumentRepository(database)


def instrument(tag: str = "IC-04", **changes: object) -> Instrument:
    base: dict[str, object] = {
        "tag": InstrumentTag.parse(tag),
        "function": InstrumentFunction.CONTROLLING,
        "span": SPAN,
        "accuracy": Accuracy(0.1, InstrumentClass.PERCENT_OF_READING, floor_f=0.5),
        "resolution": TemperatureDelta(1.0, Scale.FAHRENHEIT),
        "readout": Readout.DIGITAL,
        "interval": Interval.months(6),
        "make": "Eurotherm",
        "model": "3216",
        "serial": "A9912",
    }
    base.update(changes)
    return Instrument(**base)  # type: ignore[arg-type]


def calibration(
    number: str = "CAL-25-001",
    tag: str = "IC-04",
    performed: date = date(2025, 3, 1),
    found: float = 1550.5,
    left: float | None = None,
) -> InstrumentCalibration:
    return InstrumentCalibration(
        number,
        InstrumentTag.parse(tag),
        performed,
        (
            CalibrationCheck(
                Temperature.fahrenheit(1550),
                Temperature.fahrenheit(found),
                Temperature.fahrenheit(left) if left is not None else None,
            ),
        ),
        TOLERANCE,
        technician="dt",
        standard="FT-01",
    )


def test_an_instrument_round_trips(repo: InstrumentRepository) -> None:
    repo.insert(instrument())
    loaded = repo.get("IC-04")
    assert loaded.function is InstrumentFunction.CONTROLLING
    assert loaded.readout is Readout.DIGITAL
    assert loaded.make == "Eurotherm"
    assert loaded.serial == "A9912"
    assert loaded.status is InstrumentStatus.IN_SERVICE


def test_the_accuracy_and_span_survive(repo: InstrumentRepository) -> None:
    repo.insert(instrument())
    loaded = repo.get("IC-04")
    assert loaded.accuracy.percent == pytest.approx(0.1)
    assert loaded.accuracy.basis is InstrumentClass.PERCENT_OF_READING
    assert loaded.accuracy.floor_f == pytest.approx(0.5)
    assert loaded.span.high.degf == pytest.approx(2400.0)
    assert loaded.error_at(Temperature.fahrenheit(1550)).degf == pytest.approx(1.55)


def test_the_interval_and_rule_survive(repo: InstrumentRepository) -> None:
    repo.insert(instrument(interval=Interval.years(1), due_rule=DueRule.END_OF_MONTH))
    loaded = repo.get("IC-04")
    assert loaded.interval == Interval.years(1)
    assert loaded.due_rule is DueRule.END_OF_MONTH


def test_a_calibration_round_trips(repo: InstrumentRepository) -> None:
    repo.insert(instrument())
    repo.file(calibration())
    loaded = repo.get("IC-04")
    assert len(loaded.calibrations) == 1
    latest = loaded.latest
    assert latest is not None
    assert latest.number == "CAL-25-001"
    assert latest.technician == "dt"
    assert latest.standard == "FT-01"
    assert latest.verdict is CalibrationVerdict.PASSED
    assert loaded.due_on() == date(2025, 9, 1)


def test_an_adjusted_calibration_keeps_both_readings(repo: InstrumentRepository) -> None:
    repo.insert(instrument())
    repo.file(calibration(found=1556.0, left=1550.2))
    latest = repo.get("IC-04").latest
    assert latest is not None
    assert latest.verdict is CalibrationVerdict.ADJUSTED
    assert latest.worst_found.found_error.degf == pytest.approx(6.0)


def test_calibrations_come_back_in_date_order(repo: InstrumentRepository) -> None:
    repo.insert(instrument())
    repo.file(calibration("CAL-25-002", performed=date(2025, 9, 1)))
    repo.file(calibration("CAL-25-001", performed=date(2025, 3, 1)))
    numbers = [c.number for c in repo.get("IC-04").history]
    assert numbers == ["CAL-25-001", "CAL-25-002"]


def test_the_verdict_moves_when_the_tolerance_does(repo: InstrumentRepository) -> None:
    repo.insert(instrument())
    repo.file(calibration(found=1551.5))
    assert repo.get("IC-04").latest is not None
    tightened = InstrumentCalibration(
        "CAL-25-001",
        InstrumentTag.parse("IC-04"),
        date(2025, 3, 1),
        (CalibrationCheck(Temperature.fahrenheit(1550), Temperature.fahrenheit(1551.5)),),
        TemperatureDelta(1.0, Scale.FAHRENHEIT),
    )
    repo.file(tightened)
    latest = repo.get("IC-04").latest
    assert latest is not None
    assert latest.verdict is CalibrationVerdict.FAILED


def test_saving_an_instrument_saves_its_calibrations(repo: InstrumentRepository) -> None:
    repo.insert(instrument().with_calibration(calibration()))
    assert len(repo.get("IC-04").calibrations) == 1


def test_inserting_twice_conflicts(repo: InstrumentRepository) -> None:
    repo.insert(instrument())
    with pytest.raises(ConflictError):
        repo.insert(instrument())


def test_an_unknown_instrument_is_not_found(repo: InstrumentRepository) -> None:
    with pytest.raises(NotFoundError):
        repo.get("IC-09")
    with pytest.raises(NotFoundError):
        repo.delete("IC-09")


def test_a_short_tag_finds_the_same_instrument(repo: InstrumentRepository) -> None:
    repo.insert(instrument("IC-04"))
    assert repo.exists("IC-4")


def test_listing_helpers(repo: InstrumentRepository) -> None:
    repo.insert(instrument("IC-04"))
    repo.insert(instrument("FT-01", function=InstrumentFunction.FIELD_TEST))
    assert [str(i.tag) for i in repo.all()] == ["FT-01", "IC-04"]
    assert [str(i.tag) for i in repo.with_function(InstrumentFunction.FIELD_TEST)] == ["FT-01"]
    assert repo.count() == 2


def test_the_register_is_rebuilt_from_the_store(repo: InstrumentRepository) -> None:
    repo.insert(instrument("IC-04"))
    repo.file(calibration())
    register = repo.register()
    assert len(register) == 1
    assert register.get("IC-04").due_on() == date(2025, 9, 1)
    assert len(register.schedule(date(2025, 6, 1))) == 1


def test_delete_takes_the_calibrations_and_points(repo: InstrumentRepository) -> None:
    repo.insert(instrument())
    repo.file(calibration())
    repo.delete("IC-04")
    assert repo.count() == 0
    assert repo.database.query("SELECT number FROM instrument_calibration") == []
    assert repo.database.query("SELECT nominal_f FROM instrument_check") == []
