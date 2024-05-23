from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import ValidationError
from quenchline.sensors.calibration import Certificate, Convention
from quenchline.sensors.drift import (
    DriftVerdict,
    compare,
    project_out_of_tolerance,
)
from quenchline.sensors.types import ThermocoupleType

FIRST = date(2023, 6, 1)
SECOND = date(2024, 6, 1)


def cert(number: str, issued: date, values: list[float]) -> Certificate:
    points = list(zip([600.0, 1000.0, 1600.0], values, strict=True))
    return Certificate.of(number, issued, points, convention=Convention.CORRECTION)


def test_a_steady_couple_is_stable() -> None:
    report = compare(
        cert("A", FIRST, [1.0, 2.0, 3.0]),
        cert("B", SECOND, [1.0, 2.1, 3.0]),
        ThermocoupleType.K,
    )
    assert report.verdict is DriftVerdict.STABLE
    assert report.is_clean
    assert not report.verdict.needs_action


def test_a_moving_couple_is_flagged_as_drifting() -> None:
    report = compare(
        cert("A", FIRST, [1.0, 2.0, 3.0]),
        cert("B", SECOND, [1.0, 2.0, 9.0]),
        ThermocoupleType.K,
    )
    assert report.verdict is DriftVerdict.DRIFTING
    assert report.verdict.needs_action
    assert report.worst is not None
    assert report.worst.nominal.degf == pytest.approx(1600.0)


def test_a_correction_past_the_initial_tolerance_is_out_of_tolerance() -> None:
    report = compare(
        cert("A", FIRST, [1.0, 2.0, 3.0]),
        cert("B", SECOND, [1.0, 2.0, 20.0]),
        ThermocoupleType.K,
    )
    assert report.verdict is DriftVerdict.OUT_OF_TOLERANCE


def test_only_shared_points_are_compared() -> None:
    earlier = Certificate.of(
        "A", FIRST, [(600.0, 1.0), (1000.0, 2.0)], convention=Convention.CORRECTION
    )
    later = Certificate.of(
        "B", SECOND, [(1000.0, 2.4), (1600.0, 9.0)], convention=Convention.CORRECTION
    )
    report = compare(earlier, later, ThermocoupleType.K)
    assert [p.nominal.degf for p in report.points] == [1000.0]


def test_certificates_with_nothing_in_common_are_refused() -> None:
    earlier = Certificate.of("A", FIRST, [(600.0, 1.0)], convention=Convention.CORRECTION)
    later = Certificate.of("B", SECOND, [(1600.0, 1.0)], convention=Convention.CORRECTION)
    with pytest.raises(ValidationError):
        compare(earlier, later, ThermocoupleType.K)


def test_the_certificates_must_be_in_order() -> None:
    with pytest.raises(ValidationError):
        compare(
            cert("A", SECOND, [1.0, 2.0, 3.0]),
            cert("B", FIRST, [1.0, 2.0, 3.0]),
            ThermocoupleType.K,
        )


def test_the_drift_fraction_is_bounded() -> None:
    for fraction in (0.0, -0.5, 1.5):
        with pytest.raises(ValidationError):
            compare(
                cert("A", FIRST, [1.0, 2.0, 3.0]),
                cert("B", SECOND, [1.0, 2.0, 3.0]),
                ThermocoupleType.K,
                drift_fraction=fraction,
            )


def test_a_tighter_drift_fraction_catches_smaller_movement() -> None:
    args = (cert("A", FIRST, [1.0, 2.0, 3.0]), cert("B", SECOND, [1.0, 2.0, 6.0]))
    assert compare(*args, ThermocoupleType.K).verdict is DriftVerdict.STABLE
    tight = compare(*args, ThermocoupleType.K, drift_fraction=0.1)
    assert tight.verdict is DriftVerdict.DRIFTING


def test_drift_per_year_scales_by_the_gap_between_certificates() -> None:
    six_months = compare(
        cert("A", FIRST, [1.0, 2.0, 3.0]),
        cert("B", date(2023, 12, 1), [1.0, 2.0, 6.0]),
        ThermocoupleType.K,
    )
    assert six_months.worst is not None
    assert six_months.worst.change.degf == pytest.approx(3.0)
    assert six_months.worst.per_year.degf == pytest.approx(5.98, abs=0.05)


def test_projection_returns_a_date_when_drift_is_heading_out() -> None:
    report = compare(
        cert("A", FIRST, [1.0, 2.0, 3.0]),
        cert("B", SECOND, [1.0, 2.0, 8.0]),
        ThermocoupleType.K,
    )
    projected = project_out_of_tolerance(report, SECOND)
    assert projected is not None
    assert projected > SECOND


def test_projection_is_none_when_the_correction_is_shrinking() -> None:
    report = compare(
        cert("A", FIRST, [1.0, 2.0, 8.0]),
        cert("B", SECOND, [1.0, 2.0, 3.0]),
        ThermocoupleType.K,
    )
    assert project_out_of_tolerance(report, SECOND) is None


def test_projection_is_none_when_nothing_moved() -> None:
    report = compare(
        cert("A", FIRST, [1.0, 2.0, 3.0]),
        cert("B", SECOND, [1.0, 2.0, 3.0]),
        ThermocoupleType.K,
    )
    assert project_out_of_tolerance(report, SECOND) is None


def test_projection_is_today_when_it_is_already_past_the_limit() -> None:
    report = compare(
        cert("A", FIRST, [1.0, 2.0, 3.0]),
        cert("B", SECOND, [1.0, 2.0, 20.0]),
        ThermocoupleType.K,
    )
    assert project_out_of_tolerance(report, SECOND) == SECOND
