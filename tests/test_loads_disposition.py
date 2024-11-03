from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.loads.deviation import Deviation, DeviationKind, Severity
from quenchline.loads.disposition import Disposition, Policy, decide, summarise
from quenchline.timespan import minutes


def finding(kind: DeviationKind, severity: Severity, step: str = "austenitise") -> Deviation:
    return Deviation(kind, step, "detail", severity)


SHORT_MINOR = finding(DeviationKind.SHORT_SOAK, Severity.MINOR)
SHORT_MAJOR = finding(DeviationKind.SHORT_SOAK, Severity.MAJOR)
SHORT_CRITICAL = finding(DeviationKind.SHORT_SOAK, Severity.CRITICAL)
OVER = finding(DeviationKind.OVER_TEMPERATURE, Severity.CRITICAL, "C1")
LOST = finding(DeviationKind.SENSOR_LOST, Severity.MAJOR)
ORDER = finding(DeviationKind.OUT_OF_ORDER, Severity.CRITICAL, "cycle")


def test_disposition_properties() -> None:
    assert Disposition.ACCEPT.ships
    assert Disposition.ACCEPT_AS_IS.ships
    assert not Disposition.REWORK.ships
    assert not Disposition.SCRAP.ships
    assert Disposition.ACCEPT_AS_IS.needs_a_signature
    assert Disposition.SCRAP.needs_a_signature
    assert not Disposition.ACCEPT.needs_a_signature


def test_policy_validation() -> None:
    with pytest.raises(ValidationError):
        Policy(rework_limit=-1)
    with pytest.raises(ValidationError):
        Policy(reworks_so_far=-1)


def test_a_clean_run_is_accepted() -> None:
    decision = decide(())
    assert decision.disposition is Disposition.ACCEPT
    assert decision.ships
    assert decision.driving is None


def test_minor_findings_alone_still_ship() -> None:
    decision = decide((SHORT_MINOR,))
    assert decision.disposition is Disposition.ACCEPT
    assert "minor deviation" in decision.reason


def test_a_reworkable_major_goes_back_in_the_furnace() -> None:
    decision = decide((SHORT_MAJOR,))
    assert decision.disposition is Disposition.REWORK
    assert not decision.ships


def test_rework_stops_at_the_limit() -> None:
    policy = Policy(reworks_so_far=2, rework_limit=2)
    assert not policy.may_rework
    decision = decide((SHORT_MAJOR,), policy)
    assert decision.disposition is Disposition.ACCEPT_AS_IS


def test_a_material_that_cannot_be_rerun_never_reworks() -> None:
    policy = Policy(material_allows_rerun=False)
    assert decide((SHORT_MAJOR,), policy).disposition is Disposition.ACCEPT_AS_IS


def test_without_a_concession_the_same_load_goes_to_review() -> None:
    policy = Policy(allow_concession=False, material_allows_rerun=False)
    decision = decide((SHORT_MAJOR,), policy)
    assert decision.disposition is Disposition.REVIEW


def test_an_over_temperature_is_scrapped_whatever_the_policy_says() -> None:
    for policy in (Policy(), Policy(allow_concession=False), Policy(rework_limit=9)):
        decision = decide((OVER,), policy)
        assert decision.disposition is Disposition.SCRAP
        assert decision.driving is OVER


def test_scrap_beats_a_reworkable_finding_on_the_same_run() -> None:
    assert decide((SHORT_MAJOR, OVER)).disposition is Disposition.SCRAP


def test_a_critical_short_soak_can_still_be_reworked() -> None:
    decision = decide((SHORT_CRITICAL,))
    assert decision.disposition is Disposition.REWORK


def test_a_critical_short_soak_past_the_rework_limit_goes_to_review() -> None:
    policy = Policy(reworks_so_far=2)
    decision = decide((SHORT_CRITICAL,), policy)
    assert decision.disposition is Disposition.REVIEW


def test_a_lost_sensor_is_not_reworkable_and_takes_a_concession() -> None:
    decision = decide((LOST,))
    assert decision.disposition is Disposition.ACCEPT_AS_IS
    assert decision.driving is LOST


def test_an_out_of_order_cycle_needs_a_review() -> None:
    assert decide((ORDER,)).disposition is Disposition.REVIEW


def test_the_driving_finding_is_the_most_severe_blocking_one() -> None:
    decision = decide((SHORT_MINOR, LOST))
    assert decision.driving is LOST


def test_decision_text() -> None:
    assert str(decide((SHORT_MAJOR,))).startswith("rework:")


def test_summarise_counts_every_severity() -> None:
    counts = summarise((SHORT_MINOR, SHORT_MAJOR, OVER))
    assert counts == {"minor": 1, "major": 1, "critical": 1}


def test_summarise_of_nothing_is_all_zeroes() -> None:
    assert summarise(()) == {"minor": 0, "major": 0, "critical": 0}


def test_a_shortfall_is_carried_through_to_the_decision() -> None:
    detailed = Deviation(
        DeviationKind.SHORT_SOAK,
        "austenitise",
        "held 0:50 of a required 1:00",
        Severity.MAJOR,
        shortfall=minutes(10),
    )
    decision = decide((detailed,))
    assert decision.driving is not None
    assert decision.driving.shortfall == minutes(10)
