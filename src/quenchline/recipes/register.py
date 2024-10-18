"""The recipe register, with revisions.

A recipe is never edited. A new revision of it is written, reviewed and
released, and the old one is superseded. That matters because a load run in
March was run to revision B and its certificate has to say so, even though
everybody has been running revision D since June.

So the register holds **every** revision of every code and knows which one is
released today. A revision moves through four states and only one transition is
interesting:

``DRAFT`` -> ``RELEASED``
    releasing a revision supersedes whichever one was released before it. That
    is the only way a revision becomes superseded, and it is done by the
    register rather than by the caller, because doing it by hand is how a shop
    ends up with two released revisions of the same recipe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from ..errors import ConflictError, NotFoundError, StateError, ValidationError
from .cycle import Recipe


class RecipeState(Enum):
    DRAFT = "draft"
    RELEASED = "released"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"

    @property
    def is_runnable(self) -> bool:
        return self is RecipeState.RELEASED


@dataclass
class RecipeRevision:
    """One revision of one recipe, with its state."""

    recipe: Recipe
    state: RecipeState = RecipeState.DRAFT
    released_on: date | None = None
    superseded_on: date | None = None
    author: str = ""

    @property
    def code(self) -> str:
        return self.recipe.code

    @property
    def revision(self) -> str:
        return self.recipe.revision

    @property
    def key(self) -> tuple[str, str]:
        return (self.code, self.revision)

    def __str__(self) -> str:
        return f"{self.recipe.identifier} ({self.state.value})"


@dataclass
class RecipeRegister:
    """Every revision of every recipe in the shop."""

    revisions: dict[tuple[str, str], RecipeRevision] = field(default_factory=dict)

    def add(self, recipe: Recipe, *, author: str = "") -> RecipeRevision:
        key = (recipe.code, recipe.revision)
        if key in self.revisions:
            raise ConflictError("recipe revision", f"{recipe.code} rev {recipe.revision}")
        revision = RecipeRevision(recipe, author=author)
        self.revisions[key] = revision
        return revision

    def get(self, code: str, revision: str) -> RecipeRevision:
        key = (code, revision)
        if key not in self.revisions:
            raise NotFoundError("recipe revision", f"{code} rev {revision}")
        return self.revisions[key]

    def __len__(self) -> int:
        return len(self.revisions)

    def codes(self) -> list[str]:
        return sorted({code for code, _ in self.revisions})

    def all(self) -> list[RecipeRevision]:
        return [self.revisions[key] for key in sorted(self.revisions)]

    def revisions_of(self, code: str) -> list[RecipeRevision]:
        return [r for r in self.all() if r.code == code]

    def released(self, code: str) -> RecipeRevision | None:
        for revision in self.revisions_of(code):
            if revision.state is RecipeState.RELEASED:
                return revision
        return None

    def runnable(self, code: str) -> RecipeRevision:
        """The revision a load may be run to today."""
        current = self.released(code)
        if current is None:
            raise StateError(f"no released revision of {code}", state="unreleased")
        return current

    def release(self, code: str, revision: str, on: date) -> RecipeRevision:
        """Release a draft, superseding whatever was released before it."""
        target = self.get(code, revision)
        if target.state is RecipeState.WITHDRAWN:
            raise StateError("a withdrawn revision cannot be released", state="withdrawn")
        if target.state is RecipeState.RELEASED:
            raise StateError("that revision is already released", state="released")
        if target.state is RecipeState.SUPERSEDED:
            raise StateError("a superseded revision cannot come back", state="superseded")
        previous = self.released(code)
        if previous is not None:
            if on < (previous.released_on or on):
                raise ValidationError(
                    "a release cannot predate the revision it supersedes", field="on"
                )
            previous.state = RecipeState.SUPERSEDED
            previous.superseded_on = on
        target.state = RecipeState.RELEASED
        target.released_on = on
        return target

    def withdraw(self, code: str, revision: str) -> RecipeRevision:
        target = self.get(code, revision)
        if target.state is RecipeState.SUPERSEDED:
            raise StateError("a superseded revision is already out of use", state="superseded")
        target.state = RecipeState.WITHDRAWN
        return target

    def released_recipes(self) -> list[Recipe]:
        return [r.recipe for r in self.all() if r.state is RecipeState.RELEASED]

    def history(self, code: str) -> list[tuple[str, RecipeState, date | None]]:
        return [(r.revision, r.state, r.released_on) for r in self.revisions_of(code)]
