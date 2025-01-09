from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import ConflictError, StateError, ValidationError
from quenchline.schedule.deferral import (
    Deferral,
    DeferralRegister,
    DeferralState,
    deferrable,
    maximum_days,
)
from quenchline.schedule.policy import Activity

DUE = date(2025, 2, 10)
APPROVED = date(2025, 2, 3)


def deferral(
    activity: Activity = Activity.INSTRUMENT_CALIBRATION,
    subject: str = "IC-04",
    days: int = 10,
    countersigned: str = "",
) -> Deferral:
    return Deferral(
        activity, subject, DUE, days, "dt", APPROVED, "furnace stripped", countersigned
    )


def test_validation() -> None:
    with pytest.raises(ValidationError):
        deferral(days=0)
    with pytest.raises(ValidationError):
        Deferral(Activity.BATH_CHECK, "QT-1", DUE, 3, "  ", APPROVED, "reason")
    with pytest.raises(ValidationError):
        Deferral(Activity.BATH_CHECK, "QT-1", DUE, 3, "dt", APPROVED, "  ")


def test_the_new_due_date_moves_by_the_days_granted() -> None:
    assert deferral(days=10).new_due == date(2025, 2, 20)


def test_a_short_deferral_needs_one_signature() -> None:
    short = deferral(days=10)
    assert not short.needs_countersignature
    assert short.is_signed


def test_a_long_deferral_needs_two() -> None:
    long = deferral(days=20)
    assert long.needs_countersignature
    assert not long.is_signed
    assert deferral(days=20, countersigned="qa").is_signed


def test_the_signature_threshold_is_exclusive() -> None:
    assert not deferral(days=14).needs_countersignature
    assert deferral(days=15).needs_countersignature


def test_covers_runs_out_at_the_new_date() -> None:
    d = deferral(days=10)
    assert d.covers(date(2025, 2, 20))
    assert not d.covers(date(2025, 2, 21))


def test_a_closed_deferral_covers_nothing() -> None:
    register = DeferralRegister()
    register.grant(deferral())
    closed = register.close(Activity.INSTRUMENT_CALIBRATION, "IC-04", used=True)
    assert closed.state is DeferralState.USED
    assert not closed.covers(date(2025, 2, 15))


def test_deferral_text() -> None:
    assert str(deferral()) == "instrument_calibration IC-04 deferred 10 days to 2025-02-20"


def test_a_precision_furnace_survey_cannot_be_deferred() -> None:
    assert not deferrable(Activity.UNIFORMITY_SURVEY, precision_furnace=True, aerospace=False)
    assert deferrable(Activity.UNIFORMITY_SURVEY, precision_furnace=False, aerospace=False)


def test_an_aerospace_sat_cannot_be_deferred() -> None:
    assert not deferrable(
        Activity.SYSTEM_ACCURACY_TEST, precision_furnace=False, aerospace=True
    )
    assert deferrable(Activity.SYSTEM_ACCURACY_TEST, precision_furnace=False, aerospace=False)


def test_a_bath_check_is_deferrable_in_either_case() -> None:
    assert deferrable(Activity.BATH_CHECK, precision_furnace=True, aerospace=True)


def test_the_ceiling_differs_by_activity() -> None:
    assert maximum_days(Activity.BATH_CHECK) == 7
    assert maximum_days(Activity.SYSTEM_ACCURACY_TEST) == 14
    assert maximum_days(Activity.INSTRUMENT_CALIBRATION) == 30


def test_granting_files_the_deferral() -> None:
    register = DeferralRegister()
    register.grant(deferral())
    assert len(register) == 1
    assert register.open_for(Activity.INSTRUMENT_CALIBRATION, "IC-04") is not None


def test_a_deferral_that_cannot_be_granted_is_refused() -> None:
    register = DeferralRegister()
    with pytest.raises(StateError):
        register.grant(
            deferral(Activity.UNIFORMITY_SURVEY, "HT-04 main", 10),
            precision_furnace=True,
        )


def test_a_deferral_over_the_ceiling_is_refused() -> None:
    register = DeferralRegister()
    with pytest.raises(ValidationError):
        register.grant(deferral(Activity.BATH_CHECK, "QT-1", 10))


def test_an_unsigned_long_deferral_is_refused() -> None:
    register = DeferralRegister()
    with pytest.raises(ValidationError):
        register.grant(deferral(days=25))
    register.grant(deferral(days=25, countersigned="qa"))
    assert len(register) == 1


def test_two_open_deferrals_on_the_same_thing_are_refused() -> None:
    register = DeferralRegister()
    register.grant(deferral())
    with pytest.raises(ConflictError):
        register.grant(deferral())


def test_a_closed_deferral_frees_the_slot() -> None:
    register = DeferralRegister()
    register.grant(deferral())
    register.close(Activity.INSTRUMENT_CALIBRATION, "IC-04", used=True)
    register.grant(deferral(days=5))
    assert len(register) == 2
    assert len(register.open_deferrals()) == 1


def test_closing_nothing_is_an_error() -> None:
    with pytest.raises(StateError):
        DeferralRegister().close(Activity.BATH_CHECK, "QT-1", used=True)


def test_cancelling_marks_it_cancelled() -> None:
    register = DeferralRegister()
    register.grant(deferral())
    closed = register.close(Activity.INSTRUMENT_CALIBRATION, "IC-04", used=False)
    assert closed.state is DeferralState.CANCELLED


def test_effective_due_uses_an_open_deferral() -> None:
    register = DeferralRegister()
    register.grant(deferral(days=10))
    assert register.effective_due(Activity.INSTRUMENT_CALIBRATION, "IC-04", DUE) == date(
        2025, 2, 20
    )


def test_effective_due_ignores_a_deferral_against_a_different_date() -> None:
    register = DeferralRegister()
    register.grant(deferral(days=10))
    other = date(2025, 6, 1)
    assert register.effective_due(Activity.INSTRUMENT_CALIBRATION, "IC-04", other) == other


def test_effective_due_of_something_never_deferred() -> None:
    assert DeferralRegister().effective_due(Activity.BATH_CHECK, "QT-1", DUE) == DUE
