from __future__ import annotations

import pytest

from quenchline.errors import NotFoundError, ValidationError
from quenchline.recipes.cycle import Recipe
from quenchline.recipes.steps import Step, StepKind, hold, quench, ramp, soak, temper
from quenchline.temperature import Temperature, degf
from quenchline.timespan import minutes

AUSTENITISE = soak("austenitise", Temperature.fahrenheit(1550), degf(25), minutes(60))
HEAT = ramp("heat", Temperature.fahrenheit(1550), maximum_per_hour=400.0)
OIL = quench("oil quench", "AAA fast oil", minutes(0.5))
TEMPERING = temper("temper", Temperature.fahrenheit(400), degf(15), minutes(120))


def recipe(*steps: Step, **changes: object) -> Recipe:
    base: dict[str, object] = {
        "code": "HT-4140-Q",
        "revision": "C",
        "title": "4140 harden and temper",
        "steps": steps or (HEAT, AUSTENITISE, OIL, TEMPERING),
    }
    base.update(changes)
    return Recipe(**base)  # type: ignore[arg-type]


def test_a_recipe_reports_its_identity() -> None:
    r = recipe()
    assert r.identifier == "HT-4140-Q rev C"
    assert str(r) == "HT-4140-Q rev C 4140 harden and temper"


def test_a_recipe_needs_a_code_a_revision_and_steps() -> None:
    with pytest.raises(ValidationError):
        recipe(code="  ")
    with pytest.raises(ValidationError):
        recipe(revision=" ")
    with pytest.raises(ValidationError):
        Recipe("HT-1", "A", "empty", ())


def test_load_sensor_count_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        recipe(load_sensors=-1)


def test_two_steps_cannot_share_a_name() -> None:
    with pytest.raises(ValidationError):
        recipe(AUSTENITISE, AUSTENITISE)


def test_a_cycle_cannot_open_with_a_quench_or_a_temper() -> None:
    with pytest.raises(ValidationError):
        recipe(OIL, TEMPERING)
    with pytest.raises(ValidationError):
        recipe(TEMPERING)


def test_a_cycle_cannot_end_on_a_ramp() -> None:
    with pytest.raises(ValidationError):
        recipe(AUSTENITISE, HEAT)


def test_a_temper_before_a_quench_is_refused() -> None:
    with pytest.raises(ValidationError):
        recipe(HEAT, AUSTENITISE, TEMPERING, OIL)


def test_a_temper_after_a_quench_is_fine() -> None:
    assert recipe(HEAT, AUSTENITISE, OIL, TEMPERING).has_quench


def test_a_cycle_with_no_quench_and_no_temper_is_fine() -> None:
    r = recipe(HEAT, AUSTENITISE)
    assert not r.has_quench


def test_step_lookup_by_name_and_position() -> None:
    r = recipe()
    assert r.step("austenitise") is AUSTENITISE
    assert r.index_of("oil quench") == 2
    with pytest.raises(NotFoundError):
        r.step("nonsense")
    with pytest.raises(NotFoundError):
        r.index_of("nonsense")


def test_steps_can_be_filtered_by_kind() -> None:
    r = recipe()
    assert r.of_kind(StepKind.SOAK) == (AUSTENITISE,)
    assert len(r.of_kind(StepKind.QUENCH)) == 1
    assert r.of_kind(StepKind.HOLD) == ()


def test_graded_steps_are_the_soaks_and_tempers() -> None:
    names = [s.name for s in recipe().graded_steps]
    assert names == ["austenitise", "temper"]


def test_setpoints_and_peak() -> None:
    r = recipe()
    assert [t.degf for t in r.setpoints] == [1550.0, 1550.0, 400.0]
    peak = r.peak()
    assert peak is not None
    assert peak.degf == pytest.approx(1550.0)


def test_a_cycle_of_holds_alone_has_no_peak() -> None:
    r = recipe(hold("wait", minutes(30)))
    assert r.peak() is None
    assert r.setpoints == ()


def test_minimum_time_is_the_soak_time_only() -> None:
    assert recipe().minimum_time() == minutes(180)


def test_load_sensor_requirement() -> None:
    assert not recipe().requires_load_sensors()
    assert recipe(load_sensors=2).requires_load_sensors()


def test_fits_checks_every_setpoint_against_a_range() -> None:
    r = recipe()
    assert r.fits(Temperature.fahrenheit(300), Temperature.fahrenheit(1700))
    assert not r.fits(Temperature.fahrenheit(500), Temperature.fahrenheit(1700))
    assert not r.fits(Temperature.fahrenheit(300), Temperature.fahrenheit(1500))


def test_a_cycle_with_no_setpoints_fits_anything() -> None:
    assert recipe(hold("wait", minutes(30))).fits(
        Temperature.fahrenheit(1000), Temperature.fahrenheit(1100)
    )


def test_revising_makes_a_new_recipe() -> None:
    original = recipe()
    revised = original.revised("D")
    assert revised.revision == "D"
    assert original.revision == "C"
    assert revised.code == original.code


def test_a_revision_can_change_the_steps() -> None:
    revised = recipe().revised("D", (HEAT, AUSTENITISE))
    assert len(revised.steps) == 2


def test_a_revision_has_to_change_the_revision() -> None:
    with pytest.raises(ValidationError):
        recipe().revised("C")


def test_a_revision_is_validated_like_any_other_recipe() -> None:
    with pytest.raises(ValidationError):
        recipe().revised("D", (TEMPERING, OIL))
