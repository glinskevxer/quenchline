from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.hardness.sampling import (
    LotVerdict,
    Specification,
    judge,
    sample_size,
)
from quenchline.hardness.scales import Hardness, HardnessScale

SPEC = Specification(HardnessScale.HRC, minimum=40.0, maximum=45.0)


def hrc(*values: float, converted: bool = False) -> list[Hardness]:
    return [Hardness(v, HardnessScale.HRC, converted) for v in values]


def test_small_lots_are_tested_completely() -> None:
    assert sample_size(1) == 1
    assert sample_size(3) == 3


def test_larger_lots_take_the_root() -> None:
    assert sample_size(4) == 3
    assert sample_size(16) == 4
    assert sample_size(100) == 10
    assert sample_size(101) == 11


def test_a_lot_needs_pieces() -> None:
    with pytest.raises(ValidationError):
        sample_size(0)


def test_a_specification_needs_a_limit() -> None:
    with pytest.raises(ValidationError):
        Specification(HardnessScale.HRC)
    with pytest.raises(ValidationError):
        Specification(HardnessScale.HRC, minimum=45.0, maximum=40.0)
    with pytest.raises(ValidationError):
        Specification(HardnessScale.HRC, minimum=40.0, maximum_spread=0.0)


def test_specification_text() -> None:
    assert str(SPEC) == "40 to 45 HRC"
    assert str(Specification(HardnessScale.HRC, minimum=40.0)) == "40 HRC minimum"
    assert str(Specification(HardnessScale.HRC, maximum=45.0)) == "45 HRC maximum"


def test_a_specification_only_reads_its_own_scale() -> None:
    with pytest.raises(ValidationError):
        SPEC.contains(Hardness(400.0, HardnessScale.HV))


def test_the_limits_are_inclusive() -> None:
    assert SPEC.contains(Hardness(40.0, HardnessScale.HRC))
    assert SPEC.contains(Hardness(45.0, HardnessScale.HRC))
    assert not SPEC.contains(Hardness(39.9, HardnessScale.HRC))


def test_a_clean_lot_is_accepted() -> None:
    result = judge(hrc(41.0, 42.0, 43.0), SPEC, 9)
    assert result.is_accepted
    assert result.average == pytest.approx(42.0)
    assert "all inside" in result.reason


def test_too_few_readings_is_a_rejection() -> None:
    result = judge(hrc(41.0, 42.0), SPEC, 100)
    assert result.verdict is LotVerdict.REJECTED
    assert result.required_sample == 10
    assert "required sample" in result.reason


def test_no_readings_at_all_is_an_error() -> None:
    with pytest.raises(ValidationError):
        judge([], SPEC, 9)


def test_one_bad_reading_buys_a_retest() -> None:
    result = judge(hrc(41.0, 42.0, 38.0), SPEC, 9)
    assert result.verdict is LotVerdict.RETEST
    assert not result.verdict.is_final
    assert len(result.failures) == 1
    assert "retest on 6 pieces" in result.reason


def test_two_bad_readings_reject_straight_away() -> None:
    result = judge(hrc(41.0, 38.0, 37.0), SPEC, 9)
    assert result.verdict is LotVerdict.REJECTED
    assert len(result.failures) == 2


def test_a_retest_needs_double_the_sample() -> None:
    result = judge(hrc(41.0, 42.0, 43.0), SPEC, 9, is_retest=True)
    assert result.verdict is LotVerdict.REJECTED
    assert result.required_sample == 6


def test_a_clean_retest_is_accepted() -> None:
    result = judge(hrc(41.0, 42.0, 43.0, 41.5, 42.5, 43.5), SPEC, 9, is_retest=True)
    assert result.is_accepted


def test_one_failure_on_a_retest_ends_it() -> None:
    result = judge(hrc(41.0, 42.0, 43.0, 41.5, 42.5, 38.0), SPEC, 9, is_retest=True)
    assert result.verdict is LotVerdict.REJECTED


def test_a_reading_over_the_maximum_fails_the_same_way() -> None:
    result = judge(hrc(41.0, 42.0, 48.0), SPEC, 9)
    assert result.verdict is LotVerdict.RETEST


def test_converted_readings_are_refused_by_default() -> None:
    readings = hrc(41.0, 42.0) + hrc(43.0, converted=True)
    result = judge(readings, SPEC, 9)
    assert result.verdict is LotVerdict.REJECTED
    assert "converted readings" in result.reason


def test_a_specification_can_allow_converted_readings() -> None:
    spec = Specification(HardnessScale.HRC, minimum=40.0, maximum=45.0, allow_converted=True)
    readings = hrc(41.0, 42.0) + hrc(43.0, converted=True)
    assert judge(readings, spec, 9).is_accepted


def test_a_spread_limit_can_reject_readings_that_are_all_in_range() -> None:
    spec = Specification(HardnessScale.HRC, minimum=40.0, maximum=45.0, maximum_spread=2.0)
    result = judge(hrc(40.5, 42.0, 44.5), spec, 9)
    assert result.verdict is LotVerdict.REJECTED
    assert "spread of 4" in result.reason


def test_a_tight_group_passes_the_spread_limit() -> None:
    spec = Specification(HardnessScale.HRC, minimum=40.0, maximum=45.0, maximum_spread=2.0)
    assert judge(hrc(41.0, 42.0, 42.5), spec, 9).is_accepted


def test_result_text() -> None:
    assert str(judge(hrc(41.0, 42.0, 43.0), SPEC, 9)).startswith("accepted:")
