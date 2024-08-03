from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import ValidationError
from quenchline.identity import FurnaceTag, InstrumentTag, SensorTag
from quenchline.sat.model import SatMethod, SatReading, SatTest
from quenchline.temperature import Scale, Temperature, TemperatureDelta

FURNACE = FurnaceTag.parse("HT-04")
PERFORMED = date(2024, 7, 8)
SETPOINT = Temperature.fahrenheit(1550)


def delta(value: float) -> TemperatureDelta:
    return TemperatureDelta(value, Scale.FAHRENHEIT)


def reading(
    indicated: float, sensor: float, instrument: float, tag: str | None = None
) -> SatReading:
    return SatReading(
        Temperature.fahrenheit(indicated),
        delta(sensor),
        delta(instrument),
        SensorTag.parse(tag) if tag else None,
        InstrumentTag.parse("IC-04"),
    )


def sat(**changes: object) -> SatTest:
    base: dict[str, object] = {
        "number": "SAT-2407-04",
        "furnace": FURNACE,
        "performed": PERFORMED,
        "setpoint": SETPOINT,
        "system": reading(1550.0, -1.0, 0.5, "TC-01"),
        "test": reading(1551.0, 0.5, -0.5, "TC-99"),
    }
    base.update(changes)
    return SatTest(**base)  # type: ignore[arg-type]


def test_a_reading_adds_both_corrections() -> None:
    r = reading(1550.0, -1.0, 0.5, "TC-01")
    assert r.total_correction.degf == pytest.approx(-0.5)
    assert r.corrected().degf == pytest.approx(1549.5)


def test_a_reading_can_be_taken_raw() -> None:
    r = reading(1550.0, -1.0, 0.5, "TC-01")
    assert r.value(apply_corrections=False).degf == pytest.approx(1550.0)
    assert r.value(apply_corrections=True).degf == pytest.approx(1549.5)


def test_the_difference_is_system_minus_test() -> None:
    t = sat()
    assert t.system_value.degf == pytest.approx(1549.5)
    assert t.test_value.degf == pytest.approx(1551.0)
    assert t.difference.degf == pytest.approx(-1.5)
    assert not t.reads_high


def test_a_furnace_reading_high_is_a_positive_difference() -> None:
    t = sat(system=reading(1556.0, 0.0, 0.0, "TC-01"))
    assert t.difference.degf == pytest.approx(5.0)
    assert t.reads_high


def test_corrections_can_be_turned_off_and_the_answer_moves() -> None:
    corrected = sat()
    raw = corrected.with_corrections(apply_corrections=False)
    assert corrected.difference.degf == pytest.approx(-1.5)
    assert raw.difference.degf == pytest.approx(-1.0)


def test_applying_corrections_to_one_side_only_would_hide_a_double_fault() -> None:
    both_drifting = sat(
        system=reading(1550.0, 3.0, 3.0, "TC-01"),
        test=reading(1550.0, 0.0, 0.0, "TC-99"),
    )
    assert both_drifting.with_corrections(
        apply_corrections=False
    ).difference.degf == pytest.approx(0.0)
    assert both_drifting.difference.degf == pytest.approx(6.0)


def test_offset_from_setpoint_uses_the_test_side() -> None:
    t = sat(test=reading(1543.0, 0.0, 0.0, "TC-99"))
    assert t.offset_from_setpoint.degf == pytest.approx(-7.0)


def test_a_blank_number_is_refused() -> None:
    with pytest.raises(ValidationError):
        sat(number="  ")


def test_a_probe_test_needs_the_test_sensor_named() -> None:
    with pytest.raises(ValidationError):
        sat(test=reading(1551.0, 0.0, 0.0))


def test_the_alternate_method_needs_no_test_sensor() -> None:
    t = sat(method=SatMethod.ALTERNATE, test=reading(1551.0, 0.0, 0.0))
    assert t.method is SatMethod.ALTERNATE
    assert not t.method.needs_a_test_sensor


def test_string_form_names_the_furnace_and_setpoint() -> None:
    assert str(sat()) == "SAT-2407-04 on HT-04 at 1550 F"
