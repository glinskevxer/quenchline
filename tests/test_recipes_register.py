from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import ConflictError, NotFoundError, StateError, ValidationError
from quenchline.recipes.cycle import Recipe
from quenchline.recipes.register import RecipeRegister, RecipeState
from quenchline.recipes.steps import ramp, soak
from quenchline.temperature import Temperature, degf
from quenchline.timespan import minutes

HEAT = ramp("heat", Temperature.fahrenheit(1550), maximum_per_hour=400.0)
HOLD = soak("austenitise", Temperature.fahrenheit(1550), degf(25), minutes(60))


def recipe(revision: str = "A", code: str = "HT-4140-Q") -> Recipe:
    return Recipe(code, revision, "4140 harden", (HEAT, HOLD))


def test_states_know_which_one_can_run() -> None:
    assert RecipeState.RELEASED.is_runnable
    for state in (RecipeState.DRAFT, RecipeState.SUPERSEDED, RecipeState.WITHDRAWN):
        assert not state.is_runnable


def test_a_new_revision_starts_as_a_draft() -> None:
    register = RecipeRegister()
    revision = register.add(recipe(), author="dt")
    assert revision.state is RecipeState.DRAFT
    assert revision.author == "dt"
    assert revision.key == ("HT-4140-Q", "A")
    assert str(revision) == "HT-4140-Q rev A (draft)"


def test_the_same_revision_cannot_be_added_twice() -> None:
    register = RecipeRegister()
    register.add(recipe())
    with pytest.raises(ConflictError):
        register.add(recipe())


def test_an_unknown_revision_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        RecipeRegister().get("HT-4140-Q", "A")


def test_nothing_is_runnable_until_something_is_released() -> None:
    register = RecipeRegister()
    register.add(recipe())
    assert register.released("HT-4140-Q") is None
    with pytest.raises(StateError):
        register.runnable("HT-4140-Q")


def test_releasing_makes_a_revision_runnable() -> None:
    register = RecipeRegister()
    register.add(recipe())
    released = register.release("HT-4140-Q", "A", date(2024, 3, 1))
    assert released.state is RecipeState.RELEASED
    assert released.released_on == date(2024, 3, 1)
    assert register.runnable("HT-4140-Q").revision == "A"


def test_releasing_a_new_revision_supersedes_the_old_one() -> None:
    register = RecipeRegister()
    register.add(recipe("A"))
    register.add(recipe("B"))
    register.release("HT-4140-Q", "A", date(2024, 3, 1))
    register.release("HT-4140-Q", "B", date(2024, 6, 1))
    assert register.get("HT-4140-Q", "A").state is RecipeState.SUPERSEDED
    assert register.get("HT-4140-Q", "A").superseded_on == date(2024, 6, 1)
    assert register.runnable("HT-4140-Q").revision == "B"


def test_only_one_revision_is_ever_released() -> None:
    register = RecipeRegister()
    for revision in ("A", "B", "C"):
        register.add(recipe(revision))
    register.release("HT-4140-Q", "A", date(2024, 3, 1))
    register.release("HT-4140-Q", "B", date(2024, 6, 1))
    register.release("HT-4140-Q", "C", date(2024, 9, 1))
    released = [r for r in register.all() if r.state is RecipeState.RELEASED]
    assert len(released) == 1


def test_a_release_cannot_predate_the_one_it_supersedes() -> None:
    register = RecipeRegister()
    register.add(recipe("A"))
    register.add(recipe("B"))
    register.release("HT-4140-Q", "A", date(2024, 6, 1))
    with pytest.raises(ValidationError):
        register.release("HT-4140-Q", "B", date(2024, 3, 1))


def test_a_released_revision_cannot_be_released_again() -> None:
    register = RecipeRegister()
    register.add(recipe())
    register.release("HT-4140-Q", "A", date(2024, 3, 1))
    with pytest.raises(StateError):
        register.release("HT-4140-Q", "A", date(2024, 6, 1))


def test_a_superseded_revision_cannot_come_back() -> None:
    register = RecipeRegister()
    register.add(recipe("A"))
    register.add(recipe("B"))
    register.release("HT-4140-Q", "A", date(2024, 3, 1))
    register.release("HT-4140-Q", "B", date(2024, 6, 1))
    with pytest.raises(StateError):
        register.release("HT-4140-Q", "A", date(2024, 9, 1))


def test_a_withdrawn_revision_cannot_be_released() -> None:
    register = RecipeRegister()
    register.add(recipe())
    register.withdraw("HT-4140-Q", "A")
    assert register.get("HT-4140-Q", "A").state is RecipeState.WITHDRAWN
    with pytest.raises(StateError):
        register.release("HT-4140-Q", "A", date(2024, 3, 1))


def test_a_superseded_revision_cannot_be_withdrawn() -> None:
    register = RecipeRegister()
    register.add(recipe("A"))
    register.add(recipe("B"))
    register.release("HT-4140-Q", "A", date(2024, 3, 1))
    register.release("HT-4140-Q", "B", date(2024, 6, 1))
    with pytest.raises(StateError):
        register.withdraw("HT-4140-Q", "A")


def test_withdrawing_the_released_revision_leaves_nothing_runnable() -> None:
    register = RecipeRegister()
    register.add(recipe())
    register.release("HT-4140-Q", "A", date(2024, 3, 1))
    register.withdraw("HT-4140-Q", "A")
    with pytest.raises(StateError):
        register.runnable("HT-4140-Q")


def test_listing_helpers() -> None:
    register = RecipeRegister()
    register.add(recipe("A"))
    register.add(recipe("B"))
    register.add(recipe("A", code="HT-8620-C"))
    assert len(register) == 3
    assert register.codes() == ["HT-4140-Q", "HT-8620-C"]
    assert [r.revision for r in register.revisions_of("HT-4140-Q")] == ["A", "B"]


def test_released_recipes_lists_only_the_live_ones() -> None:
    register = RecipeRegister()
    register.add(recipe("A"))
    register.add(recipe("A", code="HT-8620-C"))
    register.release("HT-4140-Q", "A", date(2024, 3, 1))
    assert [r.code for r in register.released_recipes()] == ["HT-4140-Q"]


def test_history_reports_every_revision_in_order() -> None:
    register = RecipeRegister()
    register.add(recipe("A"))
    register.add(recipe("B"))
    register.release("HT-4140-Q", "A", date(2024, 3, 1))
    register.release("HT-4140-Q", "B", date(2024, 6, 1))
    history = register.history("HT-4140-Q")
    assert [row[0] for row in history] == ["A", "B"]
    assert history[0][1] is RecipeState.SUPERSEDED
    assert history[1][2] == date(2024, 6, 1)
