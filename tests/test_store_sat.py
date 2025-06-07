from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest

from quenchline.errors import ConflictError, NotFoundError
from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.identity import FurnaceTag, InstrumentTag, SensorTag
from quenchline.sat.model import SatMethod, SatReading, SatTest
from quenchline.store.database import Database
from quenchline.store.sat import SatRepository
from quenchline.temperature import Scale, Temperature, TemperatureDelta

ZERO = TemperatureDelta(0.0, Scale.FAHRENHEIT)


@pytest.fixture()
def repo() -> Iterator[SatRepository]:
    with Database.in_memory() as database:
        yield SatRepository(database)


def side(
    indicated: float,
    sensor: str | None = "TC-01",
    sensor_correction: float = 0.0,
    instrument_correction: float = 0.0,
) -> SatReading:
    return SatReading(
        Temperature.fahrenheit(indicated),
        TemperatureDelta(sensor_correction, Scale.FAHRENHEIT),
        TemperatureDelta(instrument_correction, Scale.FAHRENHEIT),
        SensorTag.parse(sensor) if sensor else None,
        InstrumentTag.parse("IC-04"),
    )


def sat(
    number: str = "SAT-25-001",
    furnace: str = "HT-04",
    performed: date = date(2025, 3, 1),
    system: float = 1552.0,
) -> SatTest:
    return SatTest(
        number=number,
        furnace=FurnaceTag.parse(furnace),
        performed=performed,
        setpoint=Temperature.fahrenheit(1550),
        system=side(system, "TC-01", -1.0, 0.5),
        test=side(1550.0, "TC-99", 0.5, -0.5),
        technician="dt",
    )


def test_a_test_round_trips(repo: SatRepository) -> None:
    repo.insert(sat())
    loaded = repo.get("SAT-25-001")
    assert str(loaded.furnace) == "HT-04"
    assert loaded.performed == date(2025, 3, 1)
    assert loaded.setpoint.degf == pytest.approx(1550.0)
    assert loaded.technician == "dt"
    assert loaded.method is SatMethod.PROBE


def test_both_sides_of_the_comparison_survive(repo: SatRepository) -> None:
    repo.insert(sat())
    loaded = repo.get("SAT-25-001")
    assert loaded.system.indicated.degf == pytest.approx(1552.0)
    assert loaded.system.sensor_correction.degf == pytest.approx(-1.0)
    assert loaded.system.instrument_correction.degf == pytest.approx(0.5)
    assert str(loaded.system.sensor) == "TC-00001"
    assert str(loaded.test.sensor) == "TC-00099"
    assert loaded.difference.degf == pytest.approx(loaded.system_value.degf - 1550.0)


def test_an_alternate_method_test_with_no_probe_round_trips(repo: SatRepository) -> None:
    test = SatTest(
        number="SAT-25-002",
        furnace=FurnaceTag.parse("HT-04"),
        performed=date(2025, 3, 1),
        setpoint=Temperature.fahrenheit(1550),
        system=side(1552.0),
        test=SatReading(Temperature.fahrenheit(1550.0), ZERO, ZERO),
        method=SatMethod.ALTERNATE,
    )
    repo.insert(test)
    loaded = repo.get("SAT-25-002")
    assert loaded.method is SatMethod.ALTERNATE
    assert loaded.test.sensor is None


def test_the_correction_policy_round_trips(repo: SatRepository) -> None:
    repo.insert(sat().with_corrections(apply_corrections=False))
    assert not repo.get("SAT-25-001").apply_corrections


def test_inserting_twice_is_a_conflict(repo: SatRepository) -> None:
    repo.insert(sat())
    with pytest.raises(ConflictError):
        repo.insert(sat())


def test_an_unknown_test_is_not_found(repo: SatRepository) -> None:
    with pytest.raises(NotFoundError):
        repo.get("SAT-25-999")
    with pytest.raises(NotFoundError):
        repo.delete("SAT-25-999")


def test_save_replaces_the_record(repo: SatRepository) -> None:
    repo.insert(sat())
    repo.save(sat(system=1556.0))
    assert repo.get("SAT-25-001").system.indicated.degf == pytest.approx(1556.0)
    assert repo.count() == 1


def test_tests_come_back_per_furnace_in_date_order(repo: SatRepository) -> None:
    repo.insert(sat("SAT-25-002", performed=date(2025, 6, 1)))
    repo.insert(sat("SAT-25-001", performed=date(2025, 3, 1)))
    repo.insert(sat("SAT-25-003", furnace="HT-11"))
    assert [t.number for t in repo.for_furnace("HT-04")] == ["SAT-25-001", "SAT-25-002"]
    assert [t.number for t in repo.for_furnace("ht-4")] == ["SAT-25-001", "SAT-25-002"]
    assert repo.furnaces() == ["HT-04", "HT-11"]
    assert len(repo.all()) == 3


def test_the_history_is_rebuilt_and_judged_on_the_way_out(repo: SatRepository) -> None:
    repo.insert(sat("SAT-25-001", performed=date(2025, 3, 1), system=1552.0))
    repo.insert(sat("SAT-25-002", performed=date(2025, 6, 1), system=1570.0))
    history = repo.history("HT-04", FurnaceClass.CLASS_3, InstrumentationType.D)
    assert [r.test.number for r in history.results] == ["SAT-25-001", "SAT-25-002"]
    assert history.results[0].is_pass
    assert not history.results[1].is_pass
    assert history.consecutive_passes() == 0


def test_reclassifying_the_furnace_changes_the_old_verdicts(repo: SatRepository) -> None:
    repo.insert(sat(system=1554.0))
    loose = repo.history("HT-04", FurnaceClass.CLASS_6, InstrumentationType.D)
    tight = repo.history("HT-04", FurnaceClass.CLASS_1, InstrumentationType.D)
    assert loose.results[0].is_pass
    assert not tight.results[0].is_pass


def test_a_history_for_a_furnace_with_no_tests_is_empty(repo: SatRepository) -> None:
    history = repo.history("HT-99", FurnaceClass.CLASS_3, InstrumentationType.D)
    assert history.is_empty


def test_delete_removes_the_test(repo: SatRepository) -> None:
    repo.insert(sat())
    repo.delete("SAT-25-001")
    assert repo.count() == 0
