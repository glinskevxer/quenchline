from __future__ import annotations

import pytest

from quenchline.errors import OutOfRangeError, ValidationError
from quenchline.sensors.types import (
    JunctionClass,
    ThermocoupleType,
    ToleranceClass,
    initial_tolerance,
)
from quenchline.temperature import Temperature


def test_parse_accepts_the_spellings_on_a_tag() -> None:
    assert ThermocoupleType.parse("k") is ThermocoupleType.K
    assert ThermocoupleType.parse(" Type N ") is ThermocoupleType.N
    assert ThermocoupleType.parse("TYPE R") is ThermocoupleType.R


def test_parse_refuses_a_letter_that_is_not_a_type() -> None:
    with pytest.raises(ValidationError):
        ThermocoupleType.parse("Q")


def test_base_and_noble_split() -> None:
    for kind in (ThermocoupleType.K, ThermocoupleType.N, ThermocoupleType.J):
        assert kind.junction is JunctionClass.BASE_METAL
        assert not kind.is_noble
    for kind in (ThermocoupleType.R, ThermocoupleType.S, ThermocoupleType.B):
        assert kind.junction is JunctionClass.NOBLE_METAL
        assert kind.is_noble


def test_junction_class_knows_itself() -> None:
    assert JunctionClass.NOBLE_METAL.is_noble
    assert not JunctionClass.BASE_METAL.is_noble


def test_legs_name_the_two_wires() -> None:
    assert ThermocoupleType.K.legs == ("nickel chromium", "nickel aluminium")
    assert ThermocoupleType.J.legs == ("iron", "constantan")


def test_rated_range_per_type() -> None:
    assert ThermocoupleType.K.upper_limit.degf == pytest.approx(2282.0)
    assert ThermocoupleType.J.upper_limit.degf == pytest.approx(1382.0)
    assert ThermocoupleType.B.lower_limit.degf == pytest.approx(1600.0)


def test_covers_uses_the_rated_range() -> None:
    assert ThermocoupleType.K.covers(Temperature.fahrenheit(1550))
    assert not ThermocoupleType.J.covers(Temperature.fahrenheit(1550))
    assert not ThermocoupleType.B.covers(Temperature.fahrenheit(1550))


def test_standard_tolerance_is_the_fixed_value_when_cold() -> None:
    tolerance = initial_tolerance(ThermocoupleType.K, Temperature.celsius(200))
    assert tolerance.degc == pytest.approx(2.2)


def test_standard_tolerance_is_the_percentage_when_hot() -> None:
    tolerance = initial_tolerance(ThermocoupleType.K, Temperature.fahrenheit(1550))
    assert tolerance.degc == pytest.approx(6.325, abs=1e-3)


def test_special_limits_are_tighter() -> None:
    standard = initial_tolerance(ThermocoupleType.K, Temperature.fahrenheit(1550))
    special = initial_tolerance(
        ThermocoupleType.K, Temperature.fahrenheit(1550), ToleranceClass.SPECIAL
    )
    assert special.degc < standard.degc
    assert special.degc == pytest.approx(3.373, abs=1e-3)


def test_the_percentage_applies_to_the_celsius_reading() -> None:
    tolerance = initial_tolerance(ThermocoupleType.K, Temperature.celsius(1000))
    assert tolerance.degc == pytest.approx(7.5)


def test_the_crossover_point_is_where_the_two_limits_meet() -> None:
    below = initial_tolerance(ThermocoupleType.K, Temperature.celsius(290))
    above = initial_tolerance(ThermocoupleType.K, Temperature.celsius(300))
    assert below.degc == pytest.approx(2.2)
    assert above.degc == pytest.approx(2.25)


def test_type_b_has_no_special_grade() -> None:
    assert not ThermocoupleType.B.has_special_limits()
    assert ThermocoupleType.K.has_special_limits()
    with pytest.raises(ValidationError):
        initial_tolerance(
            ThermocoupleType.B, Temperature.fahrenheit(2000), ToleranceClass.SPECIAL
        )


def test_tolerance_outside_the_rated_range_is_refused() -> None:
    with pytest.raises(OutOfRangeError):
        initial_tolerance(ThermocoupleType.J, Temperature.fahrenheit(1550))
    with pytest.raises(OutOfRangeError):
        initial_tolerance(ThermocoupleType.B, Temperature.fahrenheit(1000))


def test_noble_types_are_much_tighter_than_base_types() -> None:
    reading = Temperature.fahrenheit(2000)
    noble = initial_tolerance(ThermocoupleType.S, reading)
    base = initial_tolerance(ThermocoupleType.K, reading)
    assert noble.degc < base.degc
