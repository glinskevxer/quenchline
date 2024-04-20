from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import StateError, ValidationError
from quenchline.identity import SensorTag
from quenchline.sensors.calibration import Certificate, Convention
from quenchline.sensors.record import (
    Construction,
    SensorRole,
    SensorStatus,
    Thermocouple,
)
from quenchline.sensors.types import ThermocoupleType, ToleranceClass
from quenchline.temperature import Temperature

CERT = Certificate.of(
    "C-2401-118",
    date(2024, 1, 18),
    [(600.0, 1.0), (1600.0, 3.0)],
    convention=Convention.CORRECTION,
)


def couple(**changes: object) -> Thermocouple:
    base = {
        "tag": SensorTag.parse("TC-01188"),
        "kind": ThermocoupleType.N,
        "construction": Construction.NONEXPENDABLE,
        "role": SensorRole.CONTROL,
    }
    base.update(changes)
    return Thermocouple(**base)  # type: ignore[arg-type]


def test_a_couple_starts_in_stock_and_uncalibrated() -> None:
    tc = couple()
    assert tc.status is SensorStatus.IN_STOCK
    assert not tc.is_calibrated
    assert str(tc) == "TC-01188 type N control"


def test_construction_knows_itself() -> None:
    assert Construction.EXPENDABLE.is_expendable
    assert not Construction.NONEXPENDABLE.is_expendable


def test_permanent_roles() -> None:
    assert SensorRole.CONTROL.is_permanent
    assert SensorRole.RECORD.is_permanent
    assert SensorRole.OVER_TEMPERATURE.is_permanent
    assert not SensorRole.LOAD.is_permanent
    assert not SensorRole.SURVEY.is_permanent
    assert not SensorRole.TEST.is_permanent


def test_usable_statuses() -> None:
    assert SensorStatus.IN_STOCK.is_usable
    assert SensorStatus.IN_SERVICE.is_usable
    assert not SensorStatus.QUARANTINED.is_usable
    assert not SensorStatus.SCRAPPED.is_usable


def test_an_expendable_couple_cannot_control_a_furnace() -> None:
    with pytest.raises(ValidationError):
        couple(construction=Construction.EXPENDABLE, role=SensorRole.CONTROL)
    with pytest.raises(ValidationError):
        couple(construction=Construction.EXPENDABLE, role=SensorRole.OVER_TEMPERATURE)


def test_an_expendable_couple_can_be_a_load_sensor() -> None:
    tc = couple(construction=Construction.EXPENDABLE, role=SensorRole.LOAD)
    assert tc.role is SensorRole.LOAD


def test_special_limits_on_a_type_that_has_none_is_refused() -> None:
    with pytest.raises(ValidationError):
        couple(kind=ThermocoupleType.B, grade=ToleranceClass.SPECIAL)


def test_an_uncalibrated_couple_returns_the_reading_untouched() -> None:
    tc = couple(construction=Construction.EXPENDABLE, role=SensorRole.LOAD)
    assert tc.corrected(Temperature.fahrenheit(1550)).degf == pytest.approx(1550.0)


def test_a_calibrated_couple_applies_its_correction() -> None:
    tc = couple().with_certificate(CERT)
    assert tc.is_calibrated
    assert tc.corrected(Temperature.fahrenheit(1100)).degf == pytest.approx(1102.0)


def test_certificate_or_raise() -> None:
    with pytest.raises(StateError):
        couple().certificate_or_raise()
    assert couple().with_certificate(CERT).certificate_or_raise() is CERT


def test_going_into_service_needs_a_location() -> None:
    tc = couple().put_in_service(" furnace HT-04 control ")
    assert tc.status is SensorStatus.IN_SERVICE
    assert tc.location == "furnace HT-04 control"
    with pytest.raises(ValidationError):
        couple().put_in_service("   ")


def test_quarantine_records_the_reason() -> None:
    tc = couple().put_in_service("HT-04").quarantine("failed system accuracy test")
    assert tc.status is SensorStatus.QUARANTINED
    assert tc.notes == ("failed system accuracy test",)


def test_a_quarantined_couple_cannot_go_straight_back_in_service() -> None:
    tc = couple().quarantine("suspect")
    with pytest.raises(StateError):
        tc.put_in_service("HT-04")


def test_release_returns_it_to_stock() -> None:
    tc = couple().put_in_service("HT-04").quarantine("suspect").release()
    assert tc.status is SensorStatus.IN_STOCK
    assert tc.location == ""


def test_only_a_quarantined_couple_can_be_released() -> None:
    with pytest.raises(StateError):
        couple().release()


def test_scrapping_is_final() -> None:
    tc = couple().scrap("past its usable life")
    assert tc.status is SensorStatus.SCRAPPED
    assert tc.notes == ("past its usable life",)
    with pytest.raises(StateError):
        tc.put_in_service("HT-04")
    with pytest.raises(StateError):
        tc.quarantine("again")


def test_records_are_immutable_and_transitions_return_new_ones() -> None:
    tc = couple()
    in_service = tc.put_in_service("HT-04")
    assert tc.status is SensorStatus.IN_STOCK
    assert in_service is not tc
