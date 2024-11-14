from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.measure import Mass
from quenchline.quench.media import (
    Agitation,
    Medium,
    MediumKind,
    gas,
    load_ratio,
    oil,
    polymer,
    salt,
)
from quenchline.temperature import Temperature, degf
from quenchline.tolerance import Band

FAST_OIL = oil("AAA fast oil", Temperature.fahrenheit(130), degf(20))
UCON = polymer("polymer 10 percent", Temperature.fahrenheit(100), degf(15), 8.0, 12.0)
NITROGEN = gas("nitrogen 6 bar", Temperature.fahrenheit(80), degf(20))
NEUTRAL_SALT = salt(
    "neutral salt", Temperature.fahrenheit(400), degf(25), Temperature.fahrenheit(300)
)


def test_medium_kind_properties() -> None:
    assert MediumKind.OIL.is_liquid
    assert not MediumKind.GAS.is_liquid
    assert MediumKind.POLYMER.has_concentration
    assert not MediumKind.OIL.has_concentration
    assert MediumKind.WATER.needs_agitation
    assert not MediumKind.GAS.needs_agitation
    assert MediumKind.MOLTEN_SALT.has_a_melting_point
    assert not MediumKind.OIL.has_a_melting_point


def test_agitation_grades_compare() -> None:
    assert Agitation.GOOD.at_least(Agitation.MODERATE)
    assert Agitation.MODERATE.at_least(Agitation.MODERATE)
    assert not Agitation.MILD.at_least(Agitation.MODERATE)
    assert Agitation.MILD.is_moving
    assert not Agitation.NONE.is_moving


def test_an_oil_bath_has_a_band_and_no_concentration() -> None:
    assert FAST_OIL.operating.upper.degf == pytest.approx(150.0)
    assert str(FAST_OIL) == "AAA fast oil (oil)"
    with pytest.raises(ValidationError):
        FAST_OIL.concentration_ok(10.0)


def test_a_polymer_needs_its_concentration_range() -> None:
    assert UCON.concentration_ok(10.0)
    assert UCON.concentration_ok(8.0)
    assert not UCON.concentration_ok(7.5)
    with pytest.raises(ValidationError):
        Medium("bare polymer", MediumKind.POLYMER, FAST_OIL.operating)


def test_an_inverted_concentration_range_is_refused() -> None:
    with pytest.raises(ValidationError):
        polymer("backwards", Temperature.fahrenheit(100), degf(15), 12.0, 8.0)


def test_a_non_polymer_cannot_carry_a_concentration() -> None:
    with pytest.raises(ValidationError):
        Medium(
            "oil with a number",
            MediumKind.OIL,
            FAST_OIL.operating,
            concentration_low=8.0,
            concentration_high=12.0,
        )


def test_a_gas_quench_has_no_agitation() -> None:
    assert NITROGEN.minimum_agitation is Agitation.NONE
    with pytest.raises(ValidationError):
        Medium(
            "stirred gas",
            MediumKind.GAS,
            NITROGEN.operating,
            minimum_agitation=Agitation.GOOD,
        )


def test_a_salt_bath_needs_a_melting_point() -> None:
    assert NEUTRAL_SALT.above_melting(Temperature.fahrenheit(400))
    assert not NEUTRAL_SALT.above_melting(Temperature.fahrenheit(280))
    with pytest.raises(ValidationError):
        Medium("bare salt", MediumKind.MOLTEN_SALT, NEUTRAL_SALT.operating)


def test_a_medium_without_a_melting_point_is_always_liquid_enough() -> None:
    assert FAST_OIL.above_melting(Temperature.fahrenheit(40))


def test_a_medium_needs_a_name() -> None:
    with pytest.raises(ValidationError):
        Medium("  ", MediumKind.OIL, FAST_OIL.operating)


def test_load_ratio_limits_differ_by_medium() -> None:
    assert FAST_OIL.max_pounds_per_gallon == pytest.approx(1.0)
    assert UCON.max_pounds_per_gallon == pytest.approx(1.2)
    assert NEUTRAL_SALT.max_pounds_per_gallon == pytest.approx(0.6)


def test_load_ratio_is_pounds_per_gallon() -> None:
    assert load_ratio(Mass.pounds(1500), 2000.0) == pytest.approx(0.75)
    assert load_ratio(Mass.kilograms(500), 1000.0) == pytest.approx(1.1023, abs=1e-3)


def test_a_bath_with_no_volume_is_refused() -> None:
    with pytest.raises(ValidationError):
        load_ratio(Mass.pounds(1500), 0.0)


def test_the_band_helper_builds_what_the_medium_holds() -> None:
    assert FAST_OIL.operating == Band.symmetric(Temperature.fahrenheit(130), degf(20))
