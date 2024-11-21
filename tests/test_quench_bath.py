from __future__ import annotations

from datetime import date

import pytest

from quenchline.calendar_rules import Interval
from quenchline.errors import ValidationError
from quenchline.measure import Mass
from quenchline.quench.bath import Bath, BathFault, readiness
from quenchline.quench.media import Agitation, gas, oil, polymer, salt
from quenchline.temperature import Temperature, degf

TODAY = date(2024, 11, 20)
CHECKED = date(2024, 11, 18)

FAST_OIL = oil("AAA fast oil", Temperature.fahrenheit(130), degf(20))
UCON = polymer("polymer 10 percent", Temperature.fahrenheit(100), degf(15), 8.0, 12.0)
NITROGEN = gas("nitrogen 6 bar", Temperature.fahrenheit(80), degf(20))
NEUTRAL_SALT = salt(
    "neutral salt", Temperature.fahrenheit(400), degf(25), Temperature.fahrenheit(300)
)

LIGHT = Mass.pounds(1000)


def bath(**changes: object) -> Bath:
    base: dict[str, object] = {
        "identifier": "QT-1",
        "medium": FAST_OIL,
        "gallons": 2000.0,
        "temperature": Temperature.fahrenheit(130),
        "agitation": Agitation.GOOD,
        "last_checked": CHECKED,
    }
    base.update(changes)
    return Bath(**base)  # type: ignore[arg-type]


def test_bath_validation() -> None:
    with pytest.raises(ValidationError):
        bath(identifier="  ")
    with pytest.raises(ValidationError):
        bath(gallons=0.0)


def test_a_polymer_bath_needs_a_measured_concentration() -> None:
    with pytest.raises(ValidationError):
        bath(medium=UCON)
    ok = bath(medium=UCON, temperature=Temperature.fahrenheit(100), concentration=10.0)
    assert ok.concentration == pytest.approx(10.0)


def test_an_oil_bath_cannot_carry_a_concentration() -> None:
    with pytest.raises(ValidationError):
        bath(concentration=10.0)


def test_a_ready_bath_reports_ready() -> None:
    result = readiness(bath(), LIGHT, TODAY)
    assert result.is_ready
    assert str(result) == "QT-1 is ready"


def test_a_cold_bath_is_refused() -> None:
    result = readiness(bath(temperature=Temperature.fahrenheit(100)), LIGHT, TODAY)
    assert BathFault.TOO_COLD in result.faults
    assert not result.is_ready


def test_a_hot_bath_is_refused() -> None:
    result = readiness(bath(temperature=Temperature.fahrenheit(170)), LIGHT, TODAY)
    assert BathFault.TOO_HOT in result.faults


def test_the_band_edges_are_inclusive() -> None:
    assert readiness(bath(temperature=Temperature.fahrenheit(110)), LIGHT, TODAY).is_ready
    assert readiness(bath(temperature=Temperature.fahrenheit(150)), LIGHT, TODAY).is_ready


def test_a_frozen_salt_bath_reports_frozen_rather_than_cold() -> None:
    frozen = bath(
        medium=NEUTRAL_SALT, temperature=Temperature.fahrenheit(280), agitation=Agitation.GOOD
    )
    result = readiness(frozen, LIGHT, TODAY)
    assert BathFault.FROZEN in result.faults
    assert BathFault.TOO_COLD not in result.faults


def test_weak_agitation_is_refused() -> None:
    result = readiness(bath(agitation=Agitation.MILD), LIGHT, TODAY)
    assert BathFault.WEAK_AGITATION in result.faults


def test_a_gas_quench_is_never_asked_about_agitation() -> None:
    quench = bath(
        medium=NITROGEN,
        temperature=Temperature.fahrenheit(80),
        agitation=Agitation.NONE,
    )
    result = readiness(quench, LIGHT, TODAY)
    assert BathFault.WEAK_AGITATION not in result.faults


def test_a_polymer_out_of_concentration_is_refused() -> None:
    weak = bath(medium=UCON, temperature=Temperature.fahrenheit(100), concentration=6.0)
    result = readiness(weak, LIGHT, TODAY)
    assert BathFault.CONCENTRATION_OUT in result.faults


def test_a_polymer_inside_its_range_passes() -> None:
    good = bath(medium=UCON, temperature=Temperature.fahrenheit(100), concentration=9.0)
    assert readiness(good, LIGHT, TODAY).is_ready


def test_an_overloaded_bath_is_refused() -> None:
    result = readiness(bath(gallons=500.0), Mass.pounds(1500), TODAY)
    assert BathFault.OVERLOADED in result.faults


def test_capacity_reports_the_heaviest_allowed_load() -> None:
    assert bath().capacity().pounds_value == pytest.approx(2000.0)
    assert bath(medium=NEUTRAL_SALT, agitation=Agitation.GOOD).capacity().pounds_value == (
        pytest.approx(1200.0)
    )


def test_a_bath_that_was_never_checked_is_refused() -> None:
    result = readiness(bath(last_checked=None), LIGHT, TODAY)
    assert BathFault.CHECK_OVERDUE in result.faults
    assert bath(last_checked=None).check_due() is None


def test_an_overdue_check_is_refused() -> None:
    result = readiness(bath(last_checked=date(2024, 10, 1)), LIGHT, TODAY)
    assert BathFault.CHECK_OVERDUE in result.faults


def test_grace_delays_the_overdue_check() -> None:
    stale = bath(last_checked=date(2024, 11, 5))
    assert BathFault.CHECK_OVERDUE in readiness(stale, LIGHT, TODAY).faults
    assert BathFault.CHECK_OVERDUE not in readiness(stale, LIGHT, TODAY, grace=14).faults


def test_the_check_interval_can_be_changed() -> None:
    monthly = bath(last_checked=date(2024, 11, 1), check_interval=Interval.months(1))
    assert monthly.check_due() == date(2024, 12, 1)
    assert readiness(monthly, LIGHT, TODAY).is_ready


def test_taking_a_bath_out_of_service_blocks_it() -> None:
    out = bath().take_out_of_service("cooler failed")
    result = readiness(out, LIGHT, TODAY)
    assert BathFault.NOT_IN_SERVICE in result.faults
    assert "cooler failed" in out.notes
    assert readiness(out.return_to_service(), LIGHT, TODAY).is_ready
    with pytest.raises(ValidationError):
        bath().take_out_of_service("  ")


def test_recording_a_measurement_updates_the_bath() -> None:
    updated = bath().measured(TODAY, Temperature.fahrenheit(140), agitation=Agitation.STRONG)
    assert updated.temperature.degf == pytest.approx(140.0)
    assert updated.agitation is Agitation.STRONG
    assert updated.last_checked == TODAY
    assert updated.check_due() == date(2024, 11, 27)


def test_every_fault_is_reported_not_just_the_first() -> None:
    bad = bath(
        temperature=Temperature.fahrenheit(200),
        agitation=Agitation.NONE,
        gallons=100.0,
        last_checked=None,
    )
    result = readiness(bad, Mass.pounds(1500), TODAY)
    assert len(result.faults) == 4
    assert "not ready" in str(result)
