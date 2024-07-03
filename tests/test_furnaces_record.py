from __future__ import annotations

import pytest

from quenchline.errors import StateError, ValidationError
from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.furnaces.record import Deficiency, Furnace, FurnaceStatus
from quenchline.furnaces.zones import QualifiedRange, WorkZone
from quenchline.identity import FurnaceTag, SensorTag
from quenchline.measure import Volume
from quenchline.sensors.record import SensorRole
from quenchline.temperature import Temperature

MAIN = WorkZone(
    "main", Volume(40.0), Temperature.fahrenheit(1000), Temperature.fahrenheit(1800)
)
RANGE = QualifiedRange(Temperature.fahrenheit(1200), Temperature.fahrenheit(1700))


def furnace(**changes: object) -> Furnace:
    base: dict[str, object] = {
        "tag": FurnaceTag.parse("HT-04"),
        "furnace_class": FurnaceClass.CLASS_3,
        "instrumentation": InstrumentationType.D,
        "zones": (MAIN,),
        "qualified": RANGE,
    }
    base.update(changes)
    return Furnace(**base)  # type: ignore[arg-type]


def wired(f: Furnace, pairs: list[tuple[SensorRole, str]]) -> Furnace:
    for role, tag in pairs:
        f = f.wire(role, SensorTag.parse(tag))
    return f


def test_a_furnace_reports_its_grading() -> None:
    f = furnace()
    assert str(f) == "HT-04 class 3 type D"
    assert f.tolerance.degf == pytest.approx(15.0)


def test_duplicate_zone_names_are_refused() -> None:
    with pytest.raises(ValidationError):
        furnace(zones=(MAIN, MAIN))


def test_the_same_sensor_cannot_be_wired_twice() -> None:
    f = wired(furnace(), [(SensorRole.CONTROL, "TC-01")])
    with pytest.raises(ValidationError):
        f.wire(SensorRole.RECORD, SensorTag.parse("TC-01"))


def test_wiring_and_unwiring() -> None:
    f = wired(furnace(), [(SensorRole.CONTROL, "TC-01"), (SensorRole.RECORD, "TC-02")])
    assert f.sensor_count(SensorRole.CONTROL) == 1
    assert [str(t) for t in f.sensors_in_role(SensorRole.RECORD)] == ["TC-00002"]
    stripped = f.unwire(SensorTag.parse("TC-01"))
    assert stripped.sensor_count(SensorRole.CONTROL) == 0
    with pytest.raises(ValidationError):
        stripped.unwire(SensorTag.parse("TC-01"))


def test_zone_lookup() -> None:
    assert furnace().zone("main") is MAIN
    with pytest.raises(ValidationError):
        furnace().zone("front")


def test_adding_a_zone() -> None:
    second = WorkZone(
        "rear", Volume(10.0), Temperature.fahrenheit(900), Temperature.fahrenheit(1600)
    )
    f = furnace().add_zone(second)
    assert len(f.zones) == 2
    with pytest.raises(ValidationError):
        f.add_zone(second)


def test_survey_sensor_count_comes_off_the_zone_and_the_class() -> None:
    assert furnace().survey_sensors_needed("main") == 9
    assert furnace(furnace_class=FurnaceClass.CLASS_1).survey_sensors_needed("main") == 11


def test_may_run_needs_service_qualification_and_a_zone_that_reaches() -> None:
    f = furnace()
    assert f.may_run(Temperature.fahrenheit(1550))
    assert not f.may_run(Temperature.fahrenheit(1750))
    assert not f.take_down("element failed").may_run(Temperature.fahrenheit(1550))
    assert not f.revoke_qualification().may_run(Temperature.fahrenheit(1550))


def test_a_qualified_range_outside_every_zone_still_refuses() -> None:
    narrow = WorkZone(
        "main", Volume(40.0), Temperature.fahrenheit(1000), Temperature.fahrenheit(1400)
    )
    f = furnace(zones=(narrow,))
    assert not f.may_run(Temperature.fahrenheit(1550))


def test_qualification_can_be_widened_one_survey_at_a_time() -> None:
    f = furnace(qualified=None)
    f = f.widen_qualification(Temperature.fahrenheit(1550))
    assert f.qualified is not None
    assert f.qualified.is_single_point
    f = f.widen_qualification(Temperature.fahrenheit(1700))
    assert f.qualified is not None
    assert f.qualified.high.degf == pytest.approx(1700.0)


def test_a_type_d_furnace_with_one_control_sensor_is_complete() -> None:
    f = wired(furnace(), [(SensorRole.CONTROL, "TC-01"), (SensorRole.RECORD, "TC-02")])
    assert f.deficiencies() == ()


def test_a_furnace_claiming_type_a_has_to_carry_the_hardware() -> None:
    f = wired(
        furnace(instrumentation=InstrumentationType.A),
        [(SensorRole.CONTROL, "TC-01"), (SensorRole.RECORD, "TC-02")],
    )
    found = f.deficiencies()
    assert Deficiency.TOO_FEW_CONTROL_SENSORS in found
    assert Deficiency.NO_OVER_TEMPERATURE in found
    assert Deficiency.NO_LOAD_SENSORS in found


def test_a_type_a_furnace_that_does_carry_it_is_clean() -> None:
    f = wired(
        furnace(instrumentation=InstrumentationType.A),
        [
            (SensorRole.CONTROL, "TC-01"),
            (SensorRole.CONTROL, "TC-02"),
            (SensorRole.RECORD, "TC-03"),
            (SensorRole.OVER_TEMPERATURE, "TC-04"),
            (SensorRole.LOAD, "TC-05"),
        ],
    )
    assert f.deficiencies() == ()


def test_a_type_e_furnace_needs_no_recorder() -> None:
    f = wired(furnace(instrumentation=InstrumentationType.E), [(SensorRole.CONTROL, "TC-01")])
    assert f.deficiencies() == ()


def test_a_furnace_with_no_work_zone_is_deficient() -> None:
    f = wired(furnace(zones=()), [(SensorRole.CONTROL, "TC-01"), (SensorRole.RECORD, "TC-02")])
    assert Deficiency.NO_WORK_ZONE in f.deficiencies()


def test_deficiencies_only_check_qualification_when_asked_about_a_temperature() -> None:
    f = wired(
        furnace(qualified=None),
        [(SensorRole.CONTROL, "TC-01"), (SensorRole.RECORD, "TC-02")],
    )
    assert f.deficiencies() == ()
    assert Deficiency.NOT_QUALIFIED in f.deficiencies(Temperature.fahrenheit(1550))


def test_status_transitions() -> None:
    f = furnace()
    down = f.take_down("burner out")
    assert down.status is FurnaceStatus.DOWN
    assert not down.status.can_run_work
    assert down.bring_up().status is FurnaceStatus.IN_SERVICE
    with pytest.raises(ValidationError):
        f.take_down("  ")


def test_mothballing_drops_the_qualification_and_blocks_a_restart() -> None:
    f = furnace().mothball()
    assert f.qualified is None
    with pytest.raises(StateError):
        f.bring_up()
