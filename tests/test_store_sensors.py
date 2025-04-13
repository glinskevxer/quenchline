from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest

from quenchline.errors import ConflictError, NotFoundError
from quenchline.identity import SensorTag
from quenchline.sensors.calibration import Certificate, Convention
from quenchline.sensors.record import (
    Construction,
    SensorRole,
    SensorStatus,
    Thermocouple,
)
from quenchline.sensors.types import ThermocoupleType, ToleranceClass
from quenchline.sensors.usage import UsageEvent
from quenchline.store.database import Database
from quenchline.store.sensors import SensorRepository
from quenchline.temperature import Temperature
from quenchline.timespan import hours

CERT = Certificate.of(
    "C-24-001",
    date(2024, 3, 1),
    [(600.0, 1.0), (1700.0, 2.0)],
    convention=Convention.CORRECTION,
    laboratory="Kettering Calibration",
)


@pytest.fixture()
def repo() -> Iterator[SensorRepository]:
    with Database.in_memory() as database:
        yield SensorRepository(database)


def couple(tag: str = "TC-01", **changes: object) -> Thermocouple:
    base: dict[str, object] = {
        "tag": SensorTag.parse(tag),
        "kind": ThermocoupleType.N,
        "construction": Construction.NONEXPENDABLE,
        "role": SensorRole.SURVEY,
        "status": SensorStatus.IN_SERVICE,
        "location": "survey rack",
        "certificate": CERT,
    }
    base.update(changes)
    return Thermocouple(**base)  # type: ignore[arg-type]


def test_a_couple_round_trips(repo: SensorRepository) -> None:
    repo.insert(couple())
    loaded = repo.get("TC-00001")
    assert loaded.kind is ThermocoupleType.N
    assert loaded.construction is Construction.NONEXPENDABLE
    assert loaded.role is SensorRole.SURVEY
    assert loaded.status is SensorStatus.IN_SERVICE
    assert loaded.location == "survey rack"
    assert loaded.grade is ToleranceClass.STANDARD


def test_the_certificate_round_trips_with_its_points(repo: SensorRepository) -> None:
    repo.insert(couple())
    certificate = repo.get("TC-00001").certificate
    assert certificate is not None
    assert certificate.number == "C-24-001"
    assert certificate.laboratory == "Kettering Calibration"
    assert certificate.convention is Convention.CORRECTION
    assert len(certificate.points) == 2
    assert certificate.correction_at(Temperature.fahrenheit(1150)).degf == pytest.approx(1.5)


def test_an_uncalibrated_couple_round_trips(repo: SensorRepository) -> None:
    repo.insert(couple(certificate=None, role=SensorRole.LOAD))
    loaded = repo.get("TC-00001")
    assert loaded.certificate is None
    assert repo.certificates.count() == 0


def test_two_couples_can_share_a_certificate(repo: SensorRepository) -> None:
    repo.insert(couple("TC-01"))
    repo.insert(couple("TC-02"))
    assert repo.certificates.count() == 1
    assert repo.certificates.numbers() == ["C-24-001"]


def test_deleting_a_couple_leaves_the_certificate(repo: SensorRepository) -> None:
    repo.insert(couple("TC-01"))
    repo.insert(couple("TC-02"))
    repo.delete("TC-00001")
    assert repo.count() == 1
    assert repo.certificates.exists("C-24-001")


def test_inserting_twice_is_a_conflict(repo: SensorRepository) -> None:
    repo.insert(couple())
    with pytest.raises(ConflictError):
        repo.insert(couple())


def test_save_replaces_the_record(repo: SensorRepository) -> None:
    repo.insert(couple())
    repo.save(couple(location="furnace HT-04"))
    assert repo.get("TC-00001").location == "furnace HT-04"
    assert repo.count() == 1


def test_unknown_couples_and_certificates(repo: SensorRepository) -> None:
    with pytest.raises(NotFoundError):
        repo.get("TC-00099")
    with pytest.raises(NotFoundError):
        repo.certificates.get("C-nothing")
    with pytest.raises(NotFoundError):
        repo.delete("TC-00099")
    with pytest.raises(NotFoundError):
        repo.ledger("TC-00099")


def test_listing_helpers(repo: SensorRepository) -> None:
    repo.insert(couple("TC-01"))
    repo.insert(couple("TC-02", role=SensorRole.LOAD, certificate=None))
    assert [str(c.tag) for c in repo.all()] == ["TC-00001", "TC-00002"]
    assert [str(c.tag) for c in repo.in_role(SensorRole.LOAD)] == ["TC-00002"]
    assert [str(c.tag) for c in repo.uncalibrated()] == ["TC-00002"]


def test_usage_events_round_trip_in_order(repo: SensorRepository) -> None:
    repo.insert(couple())
    repo.record_use(
        "TC-00001",
        UsageEvent(
            date(2024, 9, 1),
            Temperature.fahrenheit(1550),
            hours(2),
            SensorRole.SURVEY,
            "TUS-1",
        ),
    )
    repo.record_use(
        "TC-00001",
        UsageEvent(date(2024, 6, 1), Temperature.fahrenheit(1200), hours(1), SensorRole.SURVEY),
    )
    ledger = repo.ledger("TC-00001")
    assert ledger.uses == 2
    assert [e.on for e in ledger.events] == [date(2024, 6, 1), date(2024, 9, 1)]
    hottest = ledger.hottest()
    assert hottest is not None
    assert hottest.degf == pytest.approx(1550.0)
    assert ledger.events[1].reference == "TUS-1"


def test_hours_survive_the_round_trip(repo: SensorRepository) -> None:
    repo.insert(couple())
    repo.record_use(
        "TC-00001",
        UsageEvent(
            date(2024, 9, 1), Temperature.fahrenheit(1550), hours(2.5), SensorRole.SURVEY
        ),
    )
    ledger = repo.ledger("TC-00001")
    assert ledger.hours_above(Temperature.fahrenheit(1000)) == pytest.approx(2.5)


def test_recording_against_an_unknown_couple_is_refused(repo: SensorRepository) -> None:
    with pytest.raises(NotFoundError):
        repo.record_use(
            "TC-00099",
            UsageEvent(
                date(2024, 9, 1), Temperature.fahrenheit(1550), hours(2), SensorRole.SURVEY
            ),
        )


def test_deleting_a_couple_takes_its_uses(repo: SensorRepository) -> None:
    repo.insert(couple())
    repo.record_use(
        "TC-00001",
        UsageEvent(date(2024, 9, 1), Temperature.fahrenheit(1550), hours(2), SensorRole.SURVEY),
    )
    repo.delete("TC-00001")
    assert repo.database.query("SELECT id FROM sensor_use") == []


def test_an_empty_ledger_comes_back_empty(repo: SensorRepository) -> None:
    repo.insert(couple())
    assert repo.ledger("TC-00001").is_empty


def test_a_short_tag_finds_the_same_couple(repo: SensorRepository) -> None:
    repo.insert(couple("TC-01"))
    assert repo.exists("TC-1")
    assert str(repo.get("TC-1").tag) == "TC-00001"


def test_a_short_tag_books_a_use_against_the_same_couple(repo: SensorRepository) -> None:
    repo.insert(couple("TC-01"))
    repo.record_use(
        "TC-1",
        UsageEvent(date(2024, 9, 1), Temperature.fahrenheit(1550), hours(2), SensorRole.SURVEY),
    )
    assert repo.ledger("TC-00001").uses == 1
