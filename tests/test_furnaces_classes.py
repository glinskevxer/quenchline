from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.furnaces.classes import (
    FurnaceClass,
    InstrumentationType,
    sat_interval,
    sensor_requirements,
    tus_interval,
    uniformity_tolerance,
)


def test_class_parsing() -> None:
    assert FurnaceClass.parse("2") is FurnaceClass.CLASS_2
    assert FurnaceClass.parse(" class 4 ") is FurnaceClass.CLASS_4
    with pytest.raises(ValidationError):
        FurnaceClass.parse("class 9")
    with pytest.raises(ValidationError):
        FurnaceClass.parse("precision")


def test_class_formatting_and_precision_flag() -> None:
    assert str(FurnaceClass.CLASS_3) == "class 3"
    assert FurnaceClass.CLASS_1.is_precision
    assert FurnaceClass.CLASS_2.is_precision
    assert not FurnaceClass.CLASS_3.is_precision


def test_uniformity_tolerance_per_class() -> None:
    assert uniformity_tolerance(FurnaceClass.CLASS_1).degf == pytest.approx(5.0)
    assert uniformity_tolerance(FurnaceClass.CLASS_3).degf == pytest.approx(15.0)
    assert uniformity_tolerance(FurnaceClass.CLASS_6).degf == pytest.approx(50.0)


def test_instrumentation_parsing() -> None:
    assert InstrumentationType.parse("a") is InstrumentationType.A
    assert InstrumentationType.parse(" Type D ") is InstrumentationType.D
    with pytest.raises(ValidationError):
        InstrumentationType.parse("F")


def test_instrumentation_ranking() -> None:
    assert InstrumentationType.A.rank == 0
    assert InstrumentationType.E.rank == 4
    assert InstrumentationType.A.at_least(InstrumentationType.C)
    assert InstrumentationType.C.at_least(InstrumentationType.C)
    assert not InstrumentationType.D.at_least(InstrumentationType.C)


def test_sensor_requirements_per_type() -> None:
    type_a = sensor_requirements(InstrumentationType.A)
    assert type_a.control_sensors == 2
    assert type_a.recording_required
    assert type_a.over_temperature_required
    assert type_a.load_sensors_required
    assert type_a.total_permanent_sensors == 3

    type_e = sensor_requirements(InstrumentationType.E)
    assert type_e.control_sensors == 1
    assert not type_e.recording_required
    assert not type_e.over_temperature_required
    assert type_e.total_permanent_sensors == 1


def test_type_b_carries_load_sensors_but_no_over_temperature_circuit() -> None:
    type_b = sensor_requirements(InstrumentationType.B)
    assert type_b.load_sensors_required
    assert not type_b.over_temperature_required


def test_sat_interval_depends_only_on_instrumentation() -> None:
    assert sat_interval(InstrumentationType.A).count == 3
    assert sat_interval(InstrumentationType.C).count == 2
    assert sat_interval(InstrumentationType.E).count == 1


def test_the_base_survey_interval_comes_from_the_class() -> None:
    assert tus_interval(FurnaceClass.CLASS_1, InstrumentationType.C).count == 3
    assert tus_interval(FurnaceClass.CLASS_3, InstrumentationType.C).count == 6
    assert tus_interval(FurnaceClass.CLASS_6, InstrumentationType.C).count == 12


def test_good_instrumentation_doubles_the_interval() -> None:
    assert tus_interval(FurnaceClass.CLASS_3, InstrumentationType.A).count == 12
    assert tus_interval(FurnaceClass.CLASS_3, InstrumentationType.B).count == 12


def test_poor_instrumentation_halves_it() -> None:
    assert tus_interval(FurnaceClass.CLASS_3, InstrumentationType.D).count == 3
    assert tus_interval(FurnaceClass.CLASS_3, InstrumentationType.E).count == 3


def test_the_halving_never_goes_below_a_month() -> None:
    assert tus_interval(FurnaceClass.CLASS_1, InstrumentationType.E).count == 1


def test_a_run_of_clean_surveys_earns_one_further_doubling() -> None:
    assert (
        tus_interval(FurnaceClass.CLASS_3, InstrumentationType.C, consecutive_passes=2).count
        == 6
    )
    assert (
        tus_interval(FurnaceClass.CLASS_3, InstrumentationType.C, consecutive_passes=3).count
        == 12
    )


def test_the_earned_doubling_does_not_stack_further() -> None:
    at_three = tus_interval(FurnaceClass.CLASS_3, InstrumentationType.C, consecutive_passes=3)
    at_nine = tus_interval(FurnaceClass.CLASS_3, InstrumentationType.C, consecutive_passes=9)
    assert at_three == at_nine


def test_a_badly_watched_furnace_earns_nothing_for_behaving() -> None:
    assert (
        tus_interval(FurnaceClass.CLASS_3, InstrumentationType.D, consecutive_passes=9).count
        == 3
    )


def test_the_two_doublings_compose_for_a_well_watched_furnace() -> None:
    assert (
        tus_interval(FurnaceClass.CLASS_3, InstrumentationType.A, consecutive_passes=3).count
        == 24
    )


def test_negative_pass_counts_are_refused() -> None:
    with pytest.raises(ValidationError):
        tus_interval(FurnaceClass.CLASS_3, InstrumentationType.A, consecutive_passes=-1)
