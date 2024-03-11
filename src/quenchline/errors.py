"""The exception hierarchy.

Every error raised by this package derives from :class:`QuenchlineError`, so a
caller that wants to catch everything the shop code can throw has exactly one
name to catch. Errors carry structured fields rather than only a message,
because the CLI renders them into an operator facing table and the store layer
writes some of them to the quarantine log.
"""

from __future__ import annotations


class QuenchlineError(Exception):
    """Base class for everything this package raises."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class ValidationError(QuenchlineError):
    """A value did not satisfy a rule that the domain imposes on it."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field

    def __str__(self) -> str:
        if self.field is None:
            return self.message
        return f"{self.field}: {self.message}"


class UnitError(ValidationError):
    """A temperature or duration was given in a unit that cannot be used here."""


class ParseError(ValidationError):
    """Text could not be read as the value it was supposed to name."""

    def __init__(self, message: str, *, text: str, field: str | None = None) -> None:
        super().__init__(message, field=field)
        self.text = text

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base} (input {self.text!r})"


class OutOfRangeError(ValidationError):
    """A value fell outside the range the domain allows for it."""

    def __init__(
        self,
        message: str,
        *,
        value: float,
        low: float | None = None,
        high: float | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message, field=field)
        self.value = value
        self.low = low
        self.high = high


class NotFoundError(QuenchlineError):
    """A record was asked for by identity and does not exist."""

    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"no {kind} with key {key!r}")
        self.kind = kind
        self.key = key


class ConflictError(QuenchlineError):
    """A record would collide with one that already exists."""

    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"{kind} {key!r} already exists")
        self.kind = kind
        self.key = key


class StateError(QuenchlineError):
    """An operation is legal in general but not from the current state."""

    def __init__(self, message: str, *, state: str | None = None) -> None:
        super().__init__(message)
        self.state = state
