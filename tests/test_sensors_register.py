from __future__ import annotations

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
from quenchline.sensors.register import (
    Blocker,
    SensorRegister,
    build_register,
    calibration_interval,
    requires_certificate,
)
from quenchline.sensors.types import ThermocoupleType, ToleranceClass
from quenchline.sensors.usage import UsageEvent
from quenchline.temperature import Temperature
from quenchline.timespan import hours

TODAY = date(2024, 9, 1)
WORKING = Temperature.fahrenheit(1550)

GOOD_CERT = Certificate.of(
    "C-24-001",
    date(2024, 3, 1),
    [(600.0, 1.0), (1700.0, 2.0)],
    convention=Convention.CORRECTION,
)
OLD_CERT = Certificate.of(
    "C-21-009",
    date(2021, 3, 1),
    [(600.0, 1.0), (1700.0, 2.0)],
    convention=Convention.CORRECTION,
)
NARROW_CERT = Certificate.of(
    "C-24-002",
    date(2024, 3, 1),
    [(400.0, 1.0), (900.0, 2.0)],
    convention=Convention.CORRECTION,
)


def couple(tag: str, **changes: object) -> Thermocouple:
    base: dict[str, object] = {
        "tag": SensorTag.parse(tag),
        "kind": ThermocoupleType.N,
        "construction": Construction.NONEXPENDABLE,
        "role": SensorRole.SURVEY,
        "status": SensorStatus.IN_SERVICE,
    }
    base.update(changes)
    return Thermocouple(**base)  # type: ignore[arg-type]


def test_certificate_requirement_depends_on_role_and_construction() -> None:
    assert requires_certificate(Construction.NONEXPENDABLE, SensorRole.SURVEY)
    assert requires_certificate(Construction.EXPENDABLE, SensorRole.SURVEY)
    assert requires_certificate(Construction.NONEXPENDABLE, SensorRole.TEST)
    assert not requires_certificate(Construction.NONEXPENDABLE, SensorRole.CONTROL)
    assert not requires_certificate(Construction.NONEXPENDABLE, SensorRole.RECORD)
    assert not requires_certificate(Construction.EXPENDABLE, SensorRole.LOAD)
    assert requires_certificate(Construction.NONEXPENDABLE, SensorRole.LOAD)


def test_noble_couples_get_a_longer_calibration_interval() -> None:
    assert calibration_interval(couple("TC-1", kind=ThermocoupleType.S)).count == 2
    assert calibration_interval(couple("TC-2", kind=ThermocoupleType.N)).count == 1


def test_register_add_and_get() -> None:
    register = build_register([couple("TC-01", certificate=GOOD_CERT)])
    assert len(register) == 1
    assert "TC-00001" in register
    assert register.get("TC-00001").tag.serial == 1


def test_adding_the_same_tag_twice_is_a_conflict() -> None:
    register = build_register([couple("TC-01")])
    with pytest.raises(ConflictError):
        register.add(couple("TC-01"))


def test_unknown_tags_are_not_found() -> None:
    register = SensorRegister()
    with pytest.raises(NotFoundError):
        register.get("TC-99")
    with pytest.raises(NotFoundError):
        register.ledger("TC-99")
    with pytest.raises(NotFoundError):
        register.replace(couple("TC-99"))


def test_replace_swaps_the_record_but_keeps_the_ledger() -> None:
    register = build_register([couple("TC-01")])
    register.record_use(
        "TC-00001",
        UsageEvent(TODAY, Temperature.fahrenheit(1550), hours(2), SensorRole.SURVEY),
    )
    register.replace(couple("TC-01", location="bench"))
    assert register.get("TC-00001").location == "bench"
    assert register.ledger("TC-00001").uses == 1


def test_listing_helpers() -> None:
    register = build_register(
        [
            couple("TC-02", role=SensorRole.SURVEY),
            couple("TC-01", role=SensorRole.LOAD, status=SensorStatus.IN_STOCK),
        ]
    )
    assert [str(c.tag) for c in register.all()] == ["TC-00001", "TC-00002"]
    assert [str(c.tag) for c in register.in_role(SensorRole.SURVEY)] == ["TC-00002"]
    assert [str(c.tag) for c in register.in_service()] == ["TC-00002"]


def test_a_good_survey_couple_is_eligible() -> None:
    register = build_register([couple("TC-01", certificate=GOOD_CERT)])
    result = register.check("TC-00001", SensorRole.SURVEY, WORKING, TODAY)
    assert result.is_eligible
    assert "may be used" in str(result)


def test_a_scrapped_couple_is_refused() -> None:
    register = build_register(
        [couple("TC-01", certificate=GOOD_CERT, status=SensorStatus.SCRAPPED)]
    )
    result = register.check("TC-00001", SensorRole.SURVEY, WORKING, TODAY)
    assert Blocker.NOT_USABLE in result.blockers


def test_a_couple_not_rated_for_the_temperature_is_refused() -> None:
    register = build_register([couple("TC-01", kind=ThermocoupleType.J)])
    result = register.check("TC-00001", SensorRole.SURVEY, WORKING, TODAY)
    assert Blocker.OUT_OF_RANGE in result.blockers


def test_a_survey_couple_with_no_certificate_is_refused() -> None:
    register = build_register([couple("TC-01")])
    result = register.check("TC-00001", SensorRole.SURVEY, WORKING, TODAY)
    assert Blocker.NO_CERTIFICATE in result.blockers


def test_the_same_couple_is_fine_as_a_control_sensor() -> None:
    register = build_register([couple("TC-01", role=SensorRole.CONTROL)])
    result = register.check("TC-00001", SensorRole.CONTROL, WORKING, TODAY)
    assert result.is_eligible


def test_an_expired_certificate_is_refused() -> None:
    register = build_register([couple("TC-01", certificate=OLD_CERT)])
    result = register.check("TC-00001", SensorRole.SURVEY, WORKING, TODAY)
    assert Blocker.CERTIFICATE_EXPIRED in result.blockers


def test_a_certificate_that_stops_short_of_the_working_temperature_is_refused() -> None:
    register = build_register([couple("TC-01", certificate=NARROW_CERT)])
    result = register.check("TC-00001", SensorRole.SURVEY, WORKING, TODAY)
    assert Blocker.CERTIFICATE_RANGE in result.blockers


def test_a_base_metal_test_couple_must_be_special_limits() -> None:
    register = build_register([couple("TC-01", certificate=GOOD_CERT, role=SensorRole.TEST)])
    loose = register.check("TC-00001", SensorRole.TEST, WORKING, TODAY)
    assert Blocker.GRADE_TOO_LOOSE in loose.blockers

    register2 = build_register(
        [
            couple(
                "TC-02",
                certificate=GOOD_CERT,
                role=SensorRole.TEST,
                grade=ToleranceClass.SPECIAL,
            )
        ]
    )
    tight = register2.check("TC-00002", SensorRole.TEST, WORKING, TODAY)
    assert tight.is_eligible


def test_a_noble_test_couple_needs_no_special_grade() -> None:
    register = build_register(
        [couple("TC-03", kind=ThermocoupleType.S, certificate=GOOD_CERT, role=SensorRole.TEST)]
    )
    assert register.check("TC-00003", SensorRole.TEST, WORKING, TODAY).is_eligible


def test_a_spent_couple_is_refused_and_listed() -> None:
    register = build_register(
        [
            couple(
                "TC-01",
                kind=ThermocoupleType.K,
                construction=Construction.EXPENDABLE,
                role=SensorRole.LOAD,
            )
        ]
    )
    register.record_use(
        "TC-00001",
        UsageEvent(TODAY, Temperature.fahrenheit(1550), hours(2), SensorRole.LOAD),
    )
    result = register.check("TC-00001", SensorRole.LOAD, WORKING, TODAY)
    assert Blocker.LIFE_SPENT in result.blockers
    assert [str(c.tag) for c in register.spent()] == ["TC-00001"]


def test_every_reason_is_reported_not_just_the_first() -> None:
    register = build_register(
        [couple("TC-01", kind=ThermocoupleType.J, status=SensorStatus.SCRAPPED)]
    )
    result = register.check("TC-00001", SensorRole.SURVEY, WORKING, TODAY)
    assert len(result.blockers) >= 3
    assert "refused" in str(result)


def test_eligible_filters_the_whole_register() -> None:
    register = build_register(
        [
            couple("TC-01", certificate=GOOD_CERT),
            couple("TC-02"),
            couple("TC-03", certificate=GOOD_CERT, status=SensorStatus.SCRAPPED),
        ]
    )
    assert [str(c.tag) for c in register.eligible(SensorRole.SURVEY, WORKING, TODAY)] == [
        "TC-00001"
    ]
