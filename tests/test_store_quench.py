from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest

from quenchline.calendar_rules import Interval
from quenchline.errors import ConflictError, NotFoundError
from quenchline.quench.bath import Bath
from quenchline.quench.media import Agitation, MediumKind, gas, oil, polymer, salt
from quenchline.store.database import Database
from quenchline.store.quench import BathRepository
from quenchline.temperature import Temperature, degf

FAST_OIL = oil("AAA fast oil", Temperature.fahrenheit(130), degf(20))
UCON = polymer("polymer 10 percent", Temperature.fahrenheit(100), degf(15), 8.0, 12.0)
NITROGEN = gas("nitrogen 6 bar", Temperature.fahrenheit(80), degf(20))
NEUTRAL_SALT = salt(
    "neutral salt", Temperature.fahrenheit(400), degf(25), Temperature.fahrenheit(300)
)


@pytest.fixture()
def repo() -> Iterator[BathRepository]:
    with Database.in_memory() as database:
        yield BathRepository(database)


def bath(identifier: str = "QT-1", **changes: object) -> Bath:
    base: dict[str, object] = {
        "identifier": identifier,
        "medium": FAST_OIL,
        "gallons": 2000.0,
        "temperature": Temperature.fahrenheit(130),
        "agitation": Agitation.GOOD,
        "last_checked": date(2025, 6, 20),
    }
    base.update(changes)
    return Bath(**base)  # type: ignore[arg-type]


def test_an_oil_bath_round_trips(repo: BathRepository) -> None:
    repo.insert(bath())
    loaded = repo.get("QT-1")
    assert loaded.medium.name == "AAA fast oil"
    assert loaded.medium.kind is MediumKind.OIL
    assert loaded.gallons == pytest.approx(2000.0)
    assert loaded.temperature.degf == pytest.approx(130.0)
    assert loaded.agitation is Agitation.GOOD
    assert loaded.in_service


def test_the_operating_band_round_trips(repo: BathRepository) -> None:
    repo.insert(bath())
    band = repo.get("QT-1").medium.operating
    assert band.lower.degf == pytest.approx(110.0)
    assert band.upper.degf == pytest.approx(150.0)


def test_a_polymer_keeps_its_concentration_range(repo: BathRepository) -> None:
    repo.insert(
        bath(
            "QT-2",
            medium=UCON,
            temperature=Temperature.fahrenheit(100),
            concentration=10.0,
        )
    )
    loaded = repo.get("QT-2")
    assert loaded.concentration == pytest.approx(10.0)
    assert loaded.medium.concentration_low == pytest.approx(8.0)
    assert loaded.medium.concentration_ok(9.0)


def test_a_salt_bath_keeps_its_melting_point(repo: BathRepository) -> None:
    repo.insert(bath("QT-3", medium=NEUTRAL_SALT, temperature=Temperature.fahrenheit(400)))
    loaded = repo.get("QT-3")
    assert loaded.medium.melting_point is not None
    assert loaded.medium.melting_point.degf == pytest.approx(300.0)
    assert not loaded.medium.above_melting(Temperature.fahrenheit(280))


def test_a_gas_quench_round_trips_with_no_agitation(repo: BathRepository) -> None:
    repo.insert(
        bath(
            "QT-4",
            medium=NITROGEN,
            temperature=Temperature.fahrenheit(80),
            agitation=Agitation.NONE,
        )
    )
    loaded = repo.get("QT-4")
    assert loaded.medium.minimum_agitation is Agitation.NONE
    assert loaded.concentration is None


def test_the_check_interval_round_trips(repo: BathRepository) -> None:
    repo.insert(bath(check_interval=Interval.months(1)))
    loaded = repo.get("QT-1")
    assert loaded.check_interval == Interval.months(1)
    assert loaded.check_due() == date(2025, 7, 20)


def test_a_bath_never_checked_round_trips(repo: BathRepository) -> None:
    repo.insert(bath(last_checked=None))
    assert repo.get("QT-1").last_checked is None
    assert repo.get("QT-1").check_due() is None


def test_out_of_service_round_trips(repo: BathRepository) -> None:
    repo.insert(bath().take_out_of_service("cooler failed"))
    assert not repo.get("QT-1").in_service


def test_inserting_twice_is_a_conflict(repo: BathRepository) -> None:
    repo.insert(bath())
    with pytest.raises(ConflictError):
        repo.insert(bath())


def test_an_unknown_bath_is_not_found(repo: BathRepository) -> None:
    with pytest.raises(NotFoundError):
        repo.get("QT-9")
    with pytest.raises(NotFoundError):
        repo.delete("QT-9")


def test_save_replaces_the_record(repo: BathRepository) -> None:
    repo.insert(bath())
    repo.save(bath().measured(date(2025, 7, 1), Temperature.fahrenheit(140)))
    loaded = repo.get("QT-1")
    assert loaded.temperature.degf == pytest.approx(140.0)
    assert loaded.last_checked == date(2025, 7, 1)
    assert repo.count() == 1


def test_listing_helpers(repo: BathRepository) -> None:
    repo.insert(bath("QT-1"))
    repo.insert(
        bath("QT-2", medium=UCON, temperature=Temperature.fahrenheit(100), concentration=10.0)
    )
    repo.insert(bath("QT-3").take_out_of_service("drained"))
    assert [b.identifier for b in repo.all()] == ["QT-1", "QT-2", "QT-3"]
    assert [b.identifier for b in repo.in_service()] == ["QT-1", "QT-2"]
    assert [b.identifier for b in repo.of_kind(MediumKind.POLYMER)] == ["QT-2"]


def test_delete_removes_the_bath(repo: BathRepository) -> None:
    repo.insert(bath())
    repo.delete("QT-1")
    assert repo.count() == 0
