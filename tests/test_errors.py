from __future__ import annotations

import pytest

from quenchline.errors import (
    ConflictError,
    NotFoundError,
    OutOfRangeError,
    ParseError,
    QuenchlineError,
    StateError,
    UnitError,
    ValidationError,
)


def test_every_error_is_a_quenchline_error() -> None:
    for cls in (ValidationError, UnitError, ParseError, OutOfRangeError):
        assert issubclass(cls, QuenchlineError)
    for cls2 in (NotFoundError, ConflictError, StateError):
        assert issubclass(cls2, QuenchlineError)


def test_unit_error_is_a_validation_error() -> None:
    assert issubclass(UnitError, ValidationError)
    assert issubclass(ParseError, ValidationError)
    assert issubclass(OutOfRangeError, ValidationError)


def test_validation_error_without_field_prints_message_only() -> None:
    err = ValidationError("soak band cannot be negative")
    assert str(err) == "soak band cannot be negative"
    assert err.field is None


def test_validation_error_with_field_prefixes_it() -> None:
    err = ValidationError("cannot be negative", field="soak_band")
    assert str(err) == "soak_band: cannot be negative"


def test_parse_error_carries_the_offending_text() -> None:
    err = ParseError("not a temperature", text="hot", field="setpoint")
    assert err.text == "hot"
    assert "setpoint: not a temperature" in str(err)
    assert "'hot'" in str(err)


def test_out_of_range_error_carries_bounds() -> None:
    err = OutOfRangeError("too cold", value=-500.0, low=-459.67, field="temperature")
    assert err.value == pytest.approx(-500.0)
    assert err.low == pytest.approx(-459.67)
    assert err.high is None


def test_not_found_error_names_kind_and_key() -> None:
    err = NotFoundError("furnace", "HT-04")
    assert err.kind == "furnace"
    assert err.key == "HT-04"
    assert str(err) == "no furnace with key 'HT-04'"


def test_conflict_error_names_kind_and_key() -> None:
    err = ConflictError("thermocouple", "TC-1188")
    assert str(err) == "thermocouple 'TC-1188' already exists"


def test_state_error_keeps_the_state_it_refused_from() -> None:
    err = StateError("cannot certify a load that never ran", state="planned")
    assert err.state == "planned"
    assert str(err) == "cannot certify a load that never ran"


def test_errors_can_be_caught_as_the_base_class() -> None:
    with pytest.raises(QuenchlineError):
        raise NotFoundError("recipe", "R-9")
