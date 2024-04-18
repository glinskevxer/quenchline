from __future__ import annotations

import pytest

from quenchline.errors import OutOfRangeError, ParseError, ValidationError
from quenchline.temperature import (
    Scale,
    Temperature,
    TemperatureDelta,
    coerce_scale,
    degc,
    degf,
    round_temperature,
)


def test_scale_parses_the_spellings_the_shop_uses() -> None:
    for text in ("F", "f", "degF", "FAHRENHEIT", "°F"):
        assert Scale.parse(text) is Scale.FAHRENHEIT
    for text in ("C", "degC", "celsius", "Centigrade"):
        assert Scale.parse(text) is Scale.CELSIUS


def test_scale_rejects_kelvin() -> None:
    with pytest.raises(ParseError):
        Scale.parse("K")


def test_freezing_and_boiling_round_trip() -> None:
    assert Temperature.celsius(0).degf == pytest.approx(32.0)
    assert Temperature.celsius(100).degf == pytest.approx(212.0)
    assert Temperature.fahrenheit(32).degc == pytest.approx(0.0)
    assert Temperature.fahrenheit(212).degc == pytest.approx(100.0)


def test_austenitizing_temperature_converts() -> None:
    assert Temperature.fahrenheit(1550).degc == pytest.approx(843.3333, abs=1e-3)
    assert Temperature.celsius(845).degf == pytest.approx(1553.0)


def test_scales_meet_at_minus_forty() -> None:
    assert Temperature.fahrenheit(-40).degc == pytest.approx(-40.0)


def test_below_absolute_zero_is_refused_on_both_scales() -> None:
    with pytest.raises(OutOfRangeError):
        Temperature.fahrenheit(-460.0)
    with pytest.raises(OutOfRangeError):
        Temperature.celsius(-274.0)


def test_absolute_zero_itself_is_allowed() -> None:
    assert Temperature.celsius(-273.15).value == pytest.approx(-273.15)


def test_to_the_same_scale_returns_the_same_object() -> None:
    t = Temperature.fahrenheit(1000)
    assert t.to(Scale.FAHRENHEIT) is t


def test_parse_reads_a_scale_suffix() -> None:
    assert Temperature.parse("1550F") == Temperature.fahrenheit(1550)
    assert Temperature.parse("  845 degC ") == Temperature.celsius(845)
    assert Temperature.parse("1550.5 F").value == pytest.approx(1550.5)


def test_parse_refuses_a_bare_number_with_no_default() -> None:
    with pytest.raises(ParseError):
        Temperature.parse("850")


def test_parse_accepts_a_bare_number_when_a_default_is_given() -> None:
    t = Temperature.parse("850", default_scale=Scale.CELSIUS)
    assert t.scale is Scale.CELSIUS
    assert t.value == pytest.approx(850.0)


def test_parse_refuses_empty_and_nonsense() -> None:
    with pytest.raises(ParseError):
        Temperature.parse("   ")
    with pytest.raises(ParseError):
        Temperature.parse("hot")


def test_a_delta_converts_by_ratio_not_by_offset() -> None:
    assert degf(18).degc == pytest.approx(10.0)
    assert degc(10).degf == pytest.approx(18.0)
    assert degf(0).degc == pytest.approx(0.0)


def test_delta_arithmetic() -> None:
    assert (degf(10) + degf(5)).magnitude == pytest.approx(15.0)
    assert (degf(10) - degc(5)).magnitude == pytest.approx(1.0)
    assert (degf(10) * 3).magnitude == pytest.approx(30.0)
    assert abs(degf(-7)).magnitude == pytest.approx(7.0)
    assert (-degf(7)).magnitude == pytest.approx(-7.0)


def test_delta_ordering_crosses_scales() -> None:
    assert degc(10) > degf(17)
    assert degc(10) >= degf(18)
    assert degf(17) < degc(10)
    assert degf(18) <= degc(10)


def test_adding_a_delta_to_a_temperature_keeps_the_temperature_scale() -> None:
    t = Temperature.fahrenheit(1550) + degc(10)
    assert t.scale is Scale.FAHRENHEIT
    assert t.value == pytest.approx(1568.0)


def test_subtracting_a_delta_gives_a_temperature() -> None:
    t = Temperature.fahrenheit(1550) - degf(50)
    assert isinstance(t, Temperature)
    assert t.value == pytest.approx(1500.0)


def test_subtracting_a_temperature_gives_a_delta() -> None:
    d = Temperature.fahrenheit(1560) - Temperature.fahrenheit(1550)
    assert isinstance(d, TemperatureDelta)
    assert d.magnitude == pytest.approx(10.0)


def test_difference_is_signed_and_uses_the_left_scale() -> None:
    d = Temperature.fahrenheit(1540).difference(Temperature.celsius(845))
    assert d.scale is Scale.FAHRENHEIT
    assert d.magnitude == pytest.approx(-13.0)


def test_temperature_ordering_crosses_scales() -> None:
    assert Temperature.celsius(845) > Temperature.fahrenheit(1550)
    assert Temperature.fahrenheit(1550) < Temperature.celsius(845)
    assert Temperature.celsius(0) <= Temperature.fahrenheit(32)
    assert Temperature.celsius(0) >= Temperature.fahrenheit(32)


def test_close_to_uses_the_absolute_tolerance() -> None:
    setpoint = Temperature.fahrenheit(1550)
    assert setpoint.close_to(Temperature.fahrenheit(1559), degf(10))
    assert setpoint.close_to(Temperature.fahrenheit(1541), degf(10))
    assert not setpoint.close_to(Temperature.fahrenheit(1562), degf(10))


def test_close_to_ignores_the_sign_of_the_tolerance() -> None:
    setpoint = Temperature.fahrenheit(1550)
    assert setpoint.close_to(Temperature.fahrenheit(1555), degf(-10))


def test_formatting() -> None:
    assert Temperature.fahrenheit(1550).format() == "1550 F"
    assert Temperature.celsius(843.33).format(1) == "843.3 C"
    assert str(degf(10)) == "+10.0 F"
    assert str(degf(-10)) == "-10.0 F"


def test_coerce_scale_picks_the_majority() -> None:
    values = [Temperature.celsius(800), Temperature.celsius(810), Temperature.fahrenheit(1500)]
    assert coerce_scale(values) is Scale.CELSIUS


def test_coerce_scale_breaks_a_tie_toward_fahrenheit() -> None:
    values = [Temperature.celsius(800), Temperature.fahrenheit(1500)]
    assert coerce_scale(values) is Scale.FAHRENHEIT


def test_coerce_scale_refuses_an_empty_list() -> None:
    with pytest.raises(ValidationError):
        coerce_scale([])


def test_round_temperature_goes_half_away_from_zero() -> None:
    assert round_temperature(Temperature.fahrenheit(1552.5)).value == pytest.approx(1553.0)
    assert round_temperature(Temperature.fahrenheit(1551.5)).value == pytest.approx(1552.0)


def test_round_temperature_honours_a_step_and_keeps_the_scale() -> None:
    rounded = round_temperature(Temperature.celsius(843.33), 0.5)
    assert rounded.scale is Scale.CELSIUS
    assert rounded.value == pytest.approx(843.5)


def test_round_temperature_refuses_a_zero_step() -> None:
    with pytest.raises(ValidationError):
        round_temperature(Temperature.fahrenheit(1550), 0.0)
