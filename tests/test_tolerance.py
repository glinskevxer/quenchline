from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.temperature import Scale, Temperature, degc, degf
from quenchline.tolerance import Band, Position, band_from_spec

SETPOINT = Temperature.fahrenheit(1550)


def test_symmetric_band_bounds() -> None:
    band = Band.symmetric(SETPOINT, degf(25))
    assert band.lower.value == pytest.approx(1525.0)
    assert band.upper.value == pytest.approx(1575.0)
    assert band.is_symmetric


def test_band_is_closed_at_both_ends() -> None:
    band = Band.symmetric(SETPOINT, degf(25))
    assert band.contains(Temperature.fahrenheit(1525))
    assert band.contains(Temperature.fahrenheit(1575))
    assert not band.contains(Temperature.fahrenheit(1524.9))
    assert not band.contains(Temperature.fahrenheit(1575.1))


def test_position_names_the_side() -> None:
    band = Band.symmetric(SETPOINT, degf(25))
    assert band.position(Temperature.fahrenheit(1500)) is Position.BELOW
    assert band.position(Temperature.fahrenheit(1550)) is Position.INSIDE
    assert band.position(Temperature.fahrenheit(1600)) is Position.ABOVE


def test_only_inside_is_not_an_excursion() -> None:
    assert not Position.INSIDE.is_excursion
    assert Position.BELOW.is_excursion
    assert Position.ABOVE.is_excursion


def test_one_sided_bands() -> None:
    high = Band.one_sided_high(SETPOINT, degf(25))
    assert high.lower.value == pytest.approx(1550.0)
    assert high.upper.value == pytest.approx(1575.0)
    assert not high.is_symmetric

    low = Band.one_sided_low(SETPOINT, degf(15))
    assert low.lower.value == pytest.approx(1535.0)
    assert low.upper.value == pytest.approx(1550.0)


def test_tolerance_magnitudes_must_be_unsigned() -> None:
    with pytest.raises(ValidationError):
        Band(SETPOINT, degf(-5), degf(5))
    with pytest.raises(ValidationError):
        Band(SETPOINT, degf(5), degf(-5))


def test_width_adds_both_sides() -> None:
    band = Band(SETPOINT, degf(10), degf(25))
    assert band.width.magnitude == pytest.approx(35.0)


def test_band_tolerances_may_be_given_on_the_other_scale() -> None:
    band = Band.symmetric(SETPOINT, degc(10))
    assert band.upper.value == pytest.approx(1568.0)
    assert band.lower.value == pytest.approx(1532.0)
    assert band.scale is Scale.FAHRENHEIT


def test_deviation_is_signed_from_the_setpoint() -> None:
    band = Band.symmetric(SETPOINT, degf(25))
    assert band.deviation(Temperature.fahrenheit(1560)).magnitude == pytest.approx(10.0)
    assert band.deviation(Temperature.fahrenheit(1540)).magnitude == pytest.approx(-10.0)


def test_excursion_is_zero_inside_the_band() -> None:
    band = Band.symmetric(SETPOINT, degf(25))
    assert band.excursion(Temperature.fahrenheit(1570)).magnitude == pytest.approx(0.0)


def test_excursion_measures_from_the_nearest_limit() -> None:
    band = Band.symmetric(SETPOINT, degf(25))
    assert band.excursion(Temperature.fahrenheit(1580)).magnitude == pytest.approx(5.0)
    assert band.excursion(Temperature.fahrenheit(1515)).magnitude == pytest.approx(-10.0)


def test_clamp_pulls_a_reading_to_the_limit() -> None:
    band = Band.symmetric(SETPOINT, degf(25))
    assert band.clamp(Temperature.fahrenheit(1600)).value == pytest.approx(1575.0)
    assert band.clamp(Temperature.fahrenheit(1400)).value == pytest.approx(1525.0)
    assert band.clamp(Temperature.fahrenheit(1551)).value == pytest.approx(1551.0)


def test_widen_and_tighten() -> None:
    band = Band.symmetric(SETPOINT, degf(25))
    assert band.widen(degf(10)).upper.value == pytest.approx(1585.0)
    assert band.tighten(degf(10)).upper.value == pytest.approx(1565.0)


def test_tighten_past_the_setpoint_is_refused() -> None:
    band = Band.symmetric(SETPOINT, degf(25))
    with pytest.raises(ValidationError):
        band.tighten(degf(30))


def test_overlaps_is_symmetric_and_closed() -> None:
    a = Band.symmetric(SETPOINT, degf(25))
    b = Band.symmetric(Temperature.fahrenheit(1600), degf(25))
    c = Band.symmetric(Temperature.fahrenheit(1610), degf(25))
    assert a.overlaps(b)
    assert b.overlaps(a)
    assert not a.overlaps(c)


def test_band_formatting() -> None:
    assert Band.symmetric(SETPOINT, degf(25)).format() == "1550 F +/-25"
    assert Band(SETPOINT, degf(0), degf(25)).format() == "1550 F +25 -0"


def test_band_from_spec_reads_a_symmetric_tolerance() -> None:
    band = band_from_spec(SETPOINT, "+/-10")
    assert band.is_symmetric
    assert band.upper.value == pytest.approx(1560.0)


def test_band_from_spec_reads_an_asymmetric_tolerance() -> None:
    band = band_from_spec(SETPOINT, "+25/-0")
    assert band.upper.value == pytest.approx(1575.0)
    assert band.lower.value == pytest.approx(1550.0)


def test_band_from_spec_rejects_bad_text() -> None:
    for spec in ("", "10", "+25", "25/-0", "+25/0"):
        with pytest.raises(ValidationError):
            band_from_spec(SETPOINT, spec)


def test_a_band_can_be_given_as_two_limits() -> None:
    band = Band.from_limits(Temperature.fahrenheit(1525), Temperature.fahrenheit(1575))
    assert band.setpoint.value == pytest.approx(1550.0)
    assert band.is_symmetric
    assert band.lower.value == pytest.approx(1525.0)
    assert band.upper.value == pytest.approx(1575.0)


def test_a_lopsided_pair_of_limits_still_centres_the_setpoint() -> None:
    band = Band.from_limits(Temperature.fahrenheit(1500), Temperature.fahrenheit(1580))
    assert band.setpoint.value == pytest.approx(1540.0)
    assert band.width.magnitude == pytest.approx(80.0)


def test_inverted_limits_are_refused() -> None:
    with pytest.raises(ValidationError):
        Band.from_limits(Temperature.fahrenheit(1575), Temperature.fahrenheit(1525))


def test_str_is_the_default_format() -> None:
    band = Band.symmetric(SETPOINT, degf(25))
    assert str(band) == band.format()
    assert str(Band(SETPOINT, degf(0), degf(25))) == "1550 F +25 -0"
