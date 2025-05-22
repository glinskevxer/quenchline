from __future__ import annotations

from collections.abc import Iterator

import pytest

from quenchline.errors import ConflictError, NotFoundError
from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.furnaces.record import Furnace, FurnaceStatus
from quenchline.furnaces.zones import QualifiedRange, WorkZone
from quenchline.identity import FurnaceTag
from quenchline.measure import Volume
from quenchline.store.database import Database
from quenchline.store.furnaces import FurnaceRepository
from quenchline.temperature import Temperature

MAIN = WorkZone(
    "main", Volume(40.0), Temperature.fahrenheit(1000), Temperature.fahrenheit(1800)
)
REAR = WorkZone("rear", Volume(12.0), Temperature.fahrenheit(900), Temperature.fahrenheit(1600))
RANGE = QualifiedRange(Temperature.fahrenheit(1200), Temperature.fahrenheit(1700))


@pytest.fixture()
def repo() -> Iterator[FurnaceRepository]:
    with Database.in_memory() as database:
        yield FurnaceRepository(database)


def furnace(tag: str = "HT-04", **changes: object) -> Furnace:
    base: dict[str, object] = {
        "tag": FurnaceTag.parse(tag),
        "furnace_class": FurnaceClass.CLASS_3,
        "instrumentation": InstrumentationType.D,
        "zones": (MAIN,),
        "qualified": RANGE,
        "description": "front loader",
    }
    base.update(changes)
    return Furnace(**base)  # type: ignore[arg-type]


def test_a_furnace_round_trips(repo: FurnaceRepository) -> None:
    repo.insert(furnace())
    loaded = repo.get("HT-04")
    assert str(loaded.tag) == "HT-04"
    assert loaded.furnace_class is FurnaceClass.CLASS_3
    assert loaded.instrumentation is InstrumentationType.D
    assert loaded.description == "front loader"
    assert loaded.status is FurnaceStatus.IN_SERVICE


def test_the_qualified_range_round_trips(repo: FurnaceRepository) -> None:
    repo.insert(furnace())
    qualified = repo.get("HT-04").qualified
    assert qualified is not None
    assert qualified.low.degf == pytest.approx(1200.0)
    assert qualified.high.degf == pytest.approx(1700.0)


def test_an_unqualified_furnace_round_trips_as_none(repo: FurnaceRepository) -> None:
    repo.insert(furnace(qualified=None))
    assert repo.get("HT-04").qualified is None


def test_zones_round_trip_in_name_order(repo: FurnaceRepository) -> None:
    repo.insert(furnace(zones=(REAR, MAIN)))
    zones = repo.get("HT-04").zones
    assert [z.name for z in zones] == ["main", "rear"]
    assert zones[0].volume.cubic_feet == pytest.approx(40.0)
    assert zones[1].high.degf == pytest.approx(1600.0)


def test_a_furnace_with_no_zones_round_trips(repo: FurnaceRepository) -> None:
    repo.insert(furnace(zones=()))
    assert repo.get("HT-04").zones == ()


def test_inserting_twice_is_a_conflict(repo: FurnaceRepository) -> None:
    repo.insert(furnace())
    with pytest.raises(ConflictError):
        repo.insert(furnace())


def test_an_unknown_furnace_is_not_found(repo: FurnaceRepository) -> None:
    with pytest.raises(NotFoundError):
        repo.get("HT-99")
    assert not repo.exists("HT-99")


def test_save_replaces_the_record_and_its_zones(repo: FurnaceRepository) -> None:
    repo.insert(furnace())
    repo.save(furnace(zones=(REAR,), description="rebuilt"))
    loaded = repo.get("HT-04")
    assert [z.name for z in loaded.zones] == ["rear"]
    assert loaded.description == "rebuilt"
    assert repo.count() == 1


def test_save_works_on_a_furnace_that_is_not_there_yet(repo: FurnaceRepository) -> None:
    repo.save(furnace())
    assert repo.exists("HT-04")


def test_listing_helpers(repo: FurnaceRepository) -> None:
    repo.insert(furnace("HT-04"))
    repo.insert(furnace("HT-11", furnace_class=FurnaceClass.CLASS_1))
    repo.insert(furnace("HT-12", status=FurnaceStatus.DOWN))
    assert [str(f.tag) for f in repo.all()] == ["HT-04", "HT-11", "HT-12"]
    assert [str(f.tag) for f in repo.of_class(FurnaceClass.CLASS_1)] == ["HT-11"]
    assert [str(f.tag) for f in repo.in_service()] == ["HT-04", "HT-11"]
    assert repo.count() == 3


def test_delete_takes_the_zones_with_it(repo: FurnaceRepository) -> None:
    repo.insert(furnace())
    repo.delete("HT-04")
    assert repo.count() == 0
    assert repo.database.query("SELECT name FROM work_zone") == []


def test_deleting_something_that_is_not_there_is_an_error(repo: FurnaceRepository) -> None:
    with pytest.raises(NotFoundError):
        repo.delete("HT-99")


def test_a_failed_insert_leaves_nothing_behind(repo: FurnaceRepository) -> None:
    repo.insert(furnace())
    with pytest.raises(ConflictError):
        repo.insert(furnace("HT-04", zones=(REAR,)))
    assert [z.name for z in repo.get("HT-04").zones] == ["main"]


def test_wired_sensors_round_trip(repo: FurnaceRepository) -> None:
    from quenchline.identity import SensorTag
    from quenchline.sensors.record import SensorRole

    wired = furnace().wire(SensorRole.CONTROL, SensorTag.parse("TC-01"))
    wired = wired.wire(SensorRole.RECORD, SensorTag.parse("TC-02"))
    repo.insert(wired)
    loaded = repo.get("HT-04")
    assert loaded.sensor_count(SensorRole.CONTROL) == 1
    assert [str(t) for t in loaded.sensors_in_role(SensorRole.RECORD)] == ["TC-00002"]


def test_saving_replaces_the_wiring(repo: FurnaceRepository) -> None:
    from quenchline.identity import SensorTag
    from quenchline.sensors.record import SensorRole

    repo.insert(furnace().wire(SensorRole.CONTROL, SensorTag.parse("TC-01")))
    repo.save(repo.get("HT-04").unwire(SensorTag.parse("TC-01")))
    assert repo.get("HT-04").sensors == ()


def test_wired_to_finds_the_furnace(repo: FurnaceRepository) -> None:
    from quenchline.identity import SensorTag
    from quenchline.sensors.record import SensorRole

    repo.insert(furnace().wire(SensorRole.CONTROL, SensorTag.parse("TC-01")))
    assert repo.wired_to("TC-1") == "HT-04"
    assert repo.wired_to("TC-99") is None


def test_deleting_a_furnace_takes_its_wiring(repo: FurnaceRepository) -> None:
    from quenchline.identity import SensorTag
    from quenchline.sensors.record import SensorRole

    repo.insert(furnace().wire(SensorRole.CONTROL, SensorTag.parse("TC-01")))
    repo.delete("HT-04")
    assert repo.database.query("SELECT sensor_tag FROM furnace_sensor") == []
