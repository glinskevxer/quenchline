from __future__ import annotations

import pytest

from quenchline.sensors.leadwire import (
    ColdJunction,
    ExtensionWire,
    WireGrade,
    combined_offset,
    mismatch_error,
    sensitivity_curve,
)
from quenchline.sensors.types import ThermocoupleType
from quenchline.temperature import Temperature


def test_matching_wire_is_recognised() -> None:
    wire = ExtensionWire(ThermocoupleType.K)
    assert wire.matches(ThermocoupleType.K)
    assert not wire.matches(ThermocoupleType.N)
    assert wire.grade is WireGrade.EXTENSION


def test_matching_wire_produces_no_error() -> None:
    wire = ExtensionWire(ThermocoupleType.K)
    result = mismatch_error(ThermocoupleType.K, wire, Temperature.fahrenheit(110))
    assert result.error.degf == pytest.approx(0.0)
    assert not result.is_significant


def test_the_wrong_wire_reads_high_when_it_is_more_sensitive() -> None:
    wire = ExtensionWire(ThermocoupleType.J)
    result = mismatch_error(ThermocoupleType.K, wire, Temperature.fahrenheit(110))
    assert result.error.degf > 0
    assert result.is_significant


def test_the_wrong_wire_reads_low_when_it_is_less_sensitive() -> None:
    wire = ExtensionWire(ThermocoupleType.N)
    result = mismatch_error(ThermocoupleType.K, wire, Temperature.fahrenheit(110))
    assert result.error.degf < 0


def test_a_joint_at_the_reference_temperature_hides_the_fault_entirely() -> None:
    wire = ExtensionWire(ThermocoupleType.J)
    result = mismatch_error(ThermocoupleType.K, wire, Temperature.fahrenheit(32))
    assert result.error.degf == pytest.approx(0.0)


def test_the_error_grows_with_the_joint_temperature() -> None:
    wire = ExtensionWire(ThermocoupleType.J)
    warm = mismatch_error(ThermocoupleType.K, wire, Temperature.fahrenheit(80))
    hot = mismatch_error(ThermocoupleType.K, wire, Temperature.fahrenheit(150))
    assert abs(hot.error.degf) > abs(warm.error.degf)


def test_the_mismatch_records_both_types() -> None:
    result = mismatch_error(
        ThermocoupleType.K, ExtensionWire(ThermocoupleType.J), Temperature.fahrenheit(110)
    )
    assert result.couple is ThermocoupleType.K
    assert result.wire is ThermocoupleType.J
    assert result.joint.degf == pytest.approx(110.0)


def test_a_hot_terminal_block_makes_the_reading_low() -> None:
    junction = ColdJunction(Temperature.fahrenheit(70), Temperature.fahrenheit(110))
    assert junction.error.degf == pytest.approx(-40.0)
    assert not junction.is_compensated


def test_a_cold_terminal_block_makes_the_reading_high() -> None:
    junction = ColdJunction(Temperature.fahrenheit(70), Temperature.fahrenheit(50))
    assert junction.error.degf == pytest.approx(20.0)


def test_a_correctly_compensated_junction_reports_itself_as_such() -> None:
    junction = ColdJunction(Temperature.fahrenheit(70), Temperature.fahrenheit(70.2))
    assert junction.is_compensated
    assert junction.error.degf == pytest.approx(-0.2)


def test_correcting_removes_the_junction_error() -> None:
    junction = ColdJunction(Temperature.fahrenheit(70), Temperature.fahrenheit(110))
    corrected = junction.correct(Temperature.fahrenheit(1510))
    assert corrected.degf == pytest.approx(1550.0)


def test_offsets_add_up() -> None:
    mismatch = mismatch_error(
        ThermocoupleType.K, ExtensionWire(ThermocoupleType.J), Temperature.fahrenheit(110)
    )
    junction = ColdJunction(Temperature.fahrenheit(70), Temperature.fahrenheit(110))
    total = combined_offset(mismatch, junction)
    assert total.degf == pytest.approx(mismatch.error.degf + junction.error.degf)


def test_offsets_of_nothing_are_zero() -> None:
    assert combined_offset(None, None).degf == pytest.approx(0.0)


def test_one_offset_alone_is_itself() -> None:
    junction = ColdJunction(Temperature.fahrenheit(70), Temperature.fahrenheit(110))
    assert combined_offset(None, junction).degf == pytest.approx(-40.0)


def test_sensitivity_curve_clamps_outside_its_range() -> None:
    curve = sensitivity_curve(ThermocoupleType.K)
    assert curve.at(1000.0) == pytest.approx(22.8)
    assert curve.at(0.0) == pytest.approx(22.8 * 0.85)
    assert curve.at(3000.0) == pytest.approx(22.8 * 1.05)
