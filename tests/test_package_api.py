from __future__ import annotations

import importlib

import quenchline


def test_version_is_exported() -> None:
    assert quenchline.__version__ == "1.0.0"


def test_every_name_in_all_actually_resolves() -> None:
    for name in quenchline.__all__:
        assert hasattr(quenchline, name), name


def test_all_is_sorted_so_diffs_stay_small() -> None:
    assert list(quenchline.__all__) == sorted(quenchline.__all__)


def test_the_public_names_are_the_ones_callers_need() -> None:
    assert quenchline.Temperature.fahrenheit(1550).degc
    assert quenchline.Band.symmetric(
        quenchline.Temperature.fahrenheit(1550), quenchline.degf(25)
    ).contains(quenchline.Temperature.fahrenheit(1560))
    assert str(quenchline.FurnaceTag.parse("HT-4")) == "HT-04"
    assert quenchline.minutes(90).format() == "1:30"


def test_the_package_imports_cleanly_from_scratch() -> None:
    module = importlib.reload(quenchline)
    assert module.__all__ == quenchline.__all__
