from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import ValidationError
from quenchline.schedule.policy import (
    Activity,
    DueItem,
    Urgency,
    attention,
    by_activity,
    rank,
    urgency_of,
)

TODAY = date(2025, 2, 3)


def item(activity: Activity, subject: str, due: date | None, *, grace: int = 0) -> DueItem:
    return DueItem.of(activity, subject, due, TODAY, grace=grace)


def test_activities_know_what_they_block() -> None:
    assert Activity.UNIFORMITY_SURVEY.stops_the_furnace
    assert Activity.SYSTEM_ACCURACY_TEST.stops_the_furnace
    assert not Activity.BATH_CHECK.stops_the_furnace
    assert Activity.UNIFORMITY_SURVEY.weight > Activity.SYSTEM_ACCURACY_TEST.weight
    assert Activity.BATH_CHECK.weight > Activity.INSTRUMENT_CALIBRATION.weight


def test_urgency_ranking() -> None:
    assert Urgency.NEVER_DONE.rank < Urgency.OVERDUE.rank < Urgency.SCHEDULED.rank
    assert Urgency.OVERDUE.needs_attention
    assert Urgency.NEVER_DONE.needs_attention
    assert not Urgency.DUE_SOON.needs_attention


def test_urgency_of_each_position() -> None:
    assert urgency_of(None, TODAY) is Urgency.NEVER_DONE
    assert urgency_of(date(2025, 1, 1), TODAY) is Urgency.OVERDUE
    assert urgency_of(TODAY, TODAY) is Urgency.DUE_NOW
    assert urgency_of(date(2025, 2, 10), TODAY) is Urgency.DUE_SOON
    assert urgency_of(date(2025, 6, 1), TODAY) is Urgency.SCHEDULED


def test_grace_moves_an_overdue_item_back_to_due_now() -> None:
    assert urgency_of(date(2025, 1, 30), TODAY) is Urgency.OVERDUE
    assert urgency_of(date(2025, 1, 30), TODAY, grace=10) is Urgency.DUE_NOW


def test_the_soon_window_can_be_widened() -> None:
    assert urgency_of(date(2025, 3, 1), TODAY) is Urgency.SCHEDULED
    assert urgency_of(date(2025, 3, 1), TODAY, soon=60) is Urgency.DUE_SOON


def test_a_negative_soon_window_is_refused() -> None:
    with pytest.raises(ValidationError):
        urgency_of(TODAY, TODAY, soon=-1)


def test_an_item_carries_its_days_left() -> None:
    soon = item(Activity.BATH_CHECK, "QT-1", date(2025, 2, 10))
    late = item(Activity.BATH_CHECK, "QT-2", date(2025, 1, 20))
    assert soon.days_left == 7
    assert late.days_left == -14
    assert item(Activity.BATH_CHECK, "QT-3", None).days_left is None


def test_item_text() -> None:
    assert (
        str(item(Activity.BATH_CHECK, "QT-1", date(2025, 2, 10)))
        == "bath_check QT-1: 2025-02-10 (due_soon)"
    )
    assert "never done" in str(item(Activity.BATH_CHECK, "QT-9", None))


def test_never_done_comes_first_of_all() -> None:
    items = [
        item(Activity.BATH_CHECK, "QT-1", date(2025, 1, 1)),
        item(Activity.UNIFORMITY_SURVEY, "HT-04", None),
    ]
    assert rank(items)[0].subject == "HT-04"


def test_overdue_beats_scheduled_whatever_it_blocks() -> None:
    items = [
        item(Activity.UNIFORMITY_SURVEY, "HT-04", date(2025, 6, 1)),
        item(Activity.INSTRUMENT_CALIBRATION, "IC-04", date(2025, 1, 1)),
    ]
    assert rank(items)[0].subject == "IC-04"


def test_a_bath_check_three_days_late_outranks_a_calibration_three_weeks_late() -> None:
    items = [
        item(Activity.INSTRUMENT_CALIBRATION, "IC-04", date(2025, 1, 13)),
        item(Activity.BATH_CHECK, "QT-1", date(2025, 1, 31)),
    ]
    assert rank(items)[0].subject == "QT-1"


def test_within_one_activity_the_latest_comes_first() -> None:
    items = [
        item(Activity.BATH_CHECK, "QT-1", date(2025, 1, 31)),
        item(Activity.BATH_CHECK, "QT-2", date(2025, 1, 1)),
    ]
    assert [i.subject for i in rank(items)] == ["QT-2", "QT-1"]


def test_ties_break_on_the_subject_so_the_board_is_stable() -> None:
    items = [
        item(Activity.BATH_CHECK, "QT-2", date(2025, 1, 20)),
        item(Activity.BATH_CHECK, "QT-1", date(2025, 1, 20)),
    ]
    assert [i.subject for i in rank(items)] == ["QT-1", "QT-2"]


def test_attention_drops_the_things_that_are_fine() -> None:
    items = [
        item(Activity.BATH_CHECK, "QT-1", date(2025, 6, 1)),
        item(Activity.BATH_CHECK, "QT-2", date(2025, 1, 1)),
        item(Activity.BATH_CHECK, "QT-3", date(2025, 2, 10)),
    ]
    assert [i.subject for i in attention(items)] == ["QT-2"]


def test_by_activity_groups_and_keeps_every_key() -> None:
    grouped = by_activity([item(Activity.BATH_CHECK, "QT-1", date(2025, 1, 1))])
    assert set(grouped) == set(Activity)
    assert [i.subject for i in grouped[Activity.BATH_CHECK]] == ["QT-1"]
    assert grouped[Activity.UNIFORMITY_SURVEY] == []
