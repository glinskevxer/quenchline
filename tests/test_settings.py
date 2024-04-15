from __future__ import annotations

from pathlib import Path

import pytest

from quenchline.calendar_rules import DueRule
from quenchline.errors import ParseError, ValidationError
from quenchline.settings import Settings
from quenchline.temperature import Scale

SAMPLE = """
[quenchline]
shop_name = "Ravensthorpe Heat Treat"
database = "shop.sqlite"
report_scale = "C"
reading_step = 0.5
schedule_grace_days = 7
default_due_rule = "end_of_month"
"""


def test_defaults_are_usable_without_a_file() -> None:
    settings = Settings.defaults()
    assert settings.database == Path("quenchline.sqlite")
    assert settings.report_scale is Scale.FAHRENHEIT
    assert settings.schedule_grace_days == 0
    assert settings.default_due_rule is DueRule.ANNIVERSARY


def test_load_reads_a_toml_file(tmp_path: Path) -> None:
    path = tmp_path / "quenchline.toml"
    path.write_text(SAMPLE)
    settings = Settings.load(path, environ={})
    assert settings.shop_name == "Ravensthorpe Heat Treat"
    assert settings.database == Path("shop.sqlite")
    assert settings.report_scale is Scale.CELSIUS
    assert settings.reading_step == pytest.approx(0.5)
    assert settings.schedule_grace_days == 7
    assert settings.default_due_rule is DueRule.END_OF_MONTH


def test_a_file_without_the_table_header_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "flat.toml"
    path.write_text('shop_name = "Flat"\n')
    assert Settings.load(path, environ={}).shop_name == "Flat"


def test_a_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings.load(tmp_path / "nope.toml", environ={})


def test_the_environment_beats_the_file(tmp_path: Path) -> None:
    path = tmp_path / "quenchline.toml"
    path.write_text(SAMPLE)
    settings = Settings.load(path, environ={"QUENCHLINE_SHOP_NAME": "Night Shift"})
    assert settings.shop_name == "Night Shift"
    assert settings.report_scale is Scale.CELSIUS


def test_the_environment_alone_is_enough() -> None:
    settings = Settings.load(None, environ={"QUENCHLINE_SCHEDULE_GRACE_DAYS": "14"})
    assert settings.schedule_grace_days == 14
    assert settings.shop_name == "unnamed shop"


def test_unknown_keys_are_refused() -> None:
    with pytest.raises(ValidationError):
        Settings.from_mapping({"colour": "blue"})


def test_a_bad_due_rule_is_refused() -> None:
    with pytest.raises(ParseError):
        Settings.from_mapping({"default_due_rule": "whenever"})


def test_a_bad_scale_is_refused() -> None:
    with pytest.raises(ParseError):
        Settings.from_mapping({"report_scale": "kelvin"})


def test_numeric_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings.from_mapping({"reading_step": 0})
    with pytest.raises(ValidationError):
        Settings.from_mapping({"schedule_grace_days": -1})
    with pytest.raises(ValidationError):
        Settings.from_mapping({"certificate_prefix": "   "})


def test_replace_returns_a_new_settings() -> None:
    base = Settings.defaults()
    changed = base.replace(shop_name="Second Shift", report_scale="C")
    assert changed.shop_name == "Second Shift"
    assert changed.report_scale is Scale.CELSIUS
    assert base.shop_name == "unnamed shop"


def test_as_mapping_round_trips() -> None:
    base = Settings.defaults().replace(shop_name="Round Trip")
    assert Settings.from_mapping(base.as_mapping()) == base
