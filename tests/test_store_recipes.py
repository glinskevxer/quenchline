from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest

from quenchline.errors import ConflictError, NotFoundError
from quenchline.recipes.cycle import Recipe
from quenchline.recipes.register import RecipeRevision, RecipeState
from quenchline.recipes.steps import StepKind, hold, quench, ramp, soak, temper
from quenchline.store.database import Database
from quenchline.store.recipes import RecipeRepository
from quenchline.temperature import Temperature, degf
from quenchline.timespan import minutes

STEPS = (
    ramp("heat", Temperature.fahrenheit(1550), maximum_per_hour=400.0),
    soak("austenitise", Temperature.fahrenheit(1550), degf(25), minutes(60)),
    quench("oil quench", "AAA fast oil", minutes(0.5)),
    temper("temper", Temperature.fahrenheit(400), degf(15), minutes(120)),
)


@pytest.fixture()
def repo() -> Iterator[RecipeRepository]:
    with Database.in_memory() as database:
        yield RecipeRepository(database)


def revision(code: str = "HT-4140-Q", rev: str = "C") -> RecipeRevision:
    recipe = Recipe(code, rev, "4140 harden and temper", STEPS, 2, "4140")
    return RecipeRevision(recipe, author="dt")


def test_a_recipe_round_trips(repo: RecipeRepository) -> None:
    repo.insert(revision())
    loaded = repo.get("HT-4140-Q", "C")
    assert loaded.recipe.title == "4140 harden and temper"
    assert loaded.recipe.material == "4140"
    assert loaded.recipe.load_sensors == 2
    assert loaded.state is RecipeState.DRAFT
    assert loaded.author == "dt"


def test_the_steps_come_back_in_order(repo: RecipeRepository) -> None:
    repo.insert(revision())
    steps = repo.get("HT-4140-Q", "C").recipe.steps
    assert [s.name for s in steps] == ["heat", "austenitise", "oil quench", "temper"]
    assert [s.kind for s in steps] == [
        StepKind.RAMP,
        StepKind.SOAK,
        StepKind.QUENCH,
        StepKind.TEMPER,
    ]


def test_every_field_of_a_soak_survives(repo: RecipeRepository) -> None:
    repo.insert(revision())
    step = repo.get("HT-4140-Q", "C").recipe.step("austenitise")
    assert step.setpoint is not None
    assert step.setpoint.degf == pytest.approx(1550.0)
    assert step.tolerance is not None
    assert step.tolerance.degf == pytest.approx(25.0)
    assert step.minimum_time == minutes(60)
    assert step.grades_temperature


def test_a_ramp_keeps_its_rate(repo: RecipeRepository) -> None:
    repo.insert(revision())
    step = repo.get("HT-4140-Q", "C").recipe.step("heat")
    assert step.rate_limit().maximum == pytest.approx(400.0)
    assert step.minimum_time is None


def test_a_quench_keeps_its_medium_and_delay(repo: RecipeRepository) -> None:
    repo.insert(revision())
    step = repo.get("HT-4140-Q", "C").recipe.step("oil quench")
    assert step.medium == "AAA fast oil"
    assert step.quench_delay == minutes(0.5)
    assert step.setpoint is None


def test_a_hold_with_nothing_on_it_round_trips(repo: RecipeRepository) -> None:
    recipe = Recipe("HT-WAIT", "A", "equalise", (hold("wait", minutes(20)),))
    repo.insert(RecipeRevision(recipe))
    step = repo.get("HT-WAIT", "A").recipe.step("wait")
    assert step.kind is StepKind.HOLD
    assert step.minimum_time == minutes(20)
    assert step.ramp is None


def test_a_maximum_time_survives(repo: RecipeRepository) -> None:
    from quenchline.recipes.steps import Step

    capped = Step(
        StepKind.SOAK,
        "austenitise",
        setpoint=Temperature.fahrenheit(1550),
        tolerance=degf(25),
        minimum_time=minutes(60),
        maximum_time=minutes(90),
    )
    recipe = Recipe("HT-CAP", "A", "capped", (capped,))
    repo.insert(RecipeRevision(recipe))
    assert repo.get("HT-CAP", "A").recipe.step("austenitise").maximum_time == minutes(90)


def test_inserting_twice_is_a_conflict(repo: RecipeRepository) -> None:
    repo.insert(revision())
    with pytest.raises(ConflictError):
        repo.insert(revision())


def test_an_unknown_revision_is_not_found(repo: RecipeRepository) -> None:
    with pytest.raises(NotFoundError):
        repo.get("HT-4140-Q", "Z")
    with pytest.raises(NotFoundError):
        repo.delete("HT-4140-Q", "Z")


def test_listing_helpers(repo: RecipeRepository) -> None:
    repo.insert(revision("HT-4140-Q", "C"))
    repo.insert(revision("HT-4140-Q", "D"))
    repo.insert(revision("HT-8620-C", "A"))
    assert repo.codes() == ["HT-4140-Q", "HT-8620-C"]
    assert [r.revision for r in repo.revisions_of("HT-4140-Q")] == ["C", "D"]
    assert repo.count() == 3


def test_the_release_state_round_trips(repo: RecipeRepository) -> None:
    register = repo.register()
    register.add(revision().recipe)
    register.release("HT-4140-Q", "C", date(2025, 3, 1))
    repo.save_register(register)
    loaded = repo.get("HT-4140-Q", "C")
    assert loaded.state is RecipeState.RELEASED
    assert loaded.released_on == date(2025, 3, 1)
    assert repo.released("HT-4140-Q") is not None


def test_superseding_round_trips(repo: RecipeRepository) -> None:
    register = repo.register()
    register.add(revision("HT-4140-Q", "C").recipe)
    register.add(revision("HT-4140-Q", "D").recipe)
    register.release("HT-4140-Q", "C", date(2025, 3, 1))
    register.release("HT-4140-Q", "D", date(2025, 6, 1))
    repo.save_register(register)
    assert repo.get("HT-4140-Q", "C").state is RecipeState.SUPERSEDED
    assert repo.get("HT-4140-Q", "C").superseded_on == date(2025, 6, 1)
    released = repo.released("HT-4140-Q")
    assert released is not None
    assert released.revision == "D"


def test_nothing_is_released_until_it_is(repo: RecipeRepository) -> None:
    repo.insert(revision())
    assert repo.released("HT-4140-Q") is None


def test_the_register_is_rebuilt_from_the_store(repo: RecipeRepository) -> None:
    repo.insert(revision("HT-4140-Q", "C"))
    repo.insert(revision("HT-4140-Q", "D"))
    register = repo.register()
    assert len(register) == 2
    assert [r.revision for r in register.revisions_of("HT-4140-Q")] == ["C", "D"]


def test_delete_takes_the_steps(repo: RecipeRepository) -> None:
    repo.insert(revision())
    repo.delete("HT-4140-Q", "C")
    assert repo.count() == 0
    assert repo.database.query("SELECT name FROM recipe_step") == []
