from __future__ import annotations

from pathlib import Path

import pytest

from quenchline.errors import ConflictError, NotFoundError, ValidationError
from quenchline.ingest.mapping import ColumnMap, MappingProfile, TimeUnit
from quenchline.ingest.profiles import (
    BUILT_IN,
    DATAPAQ_TP3,
    EUROTHERM_6100,
    HONEYWELL_DR4500,
    ProfileLibrary,
    build_profile,
)
from quenchline.loads.trace import ChannelRole
from quenchline.temperature import Scale

SAMPLE = """
[[profile]]
name = "yokogawa mv1000"
time_heading = "Elapsed"
time_unit = "seconds"
scale = "C"
delimiter = ";"
dropout_markers = ["", "+OVER", "-OVER"]

  [[profile.column]]
  heading = "CH01"
  key = "C1"
  role = "control"

  [[profile.column]]
  heading = "CH02"
  key = "L1"
  role = "load"
"""


def test_the_built_in_profiles_are_all_different() -> None:
    assert len(BUILT_IN) == 3
    assert len({p.name for p in BUILT_IN}) == 3


def test_the_eurotherm_profile_reads_minutes_in_fahrenheit() -> None:
    assert EUROTHERM_6100.time_unit is TimeUnit.MINUTES
    assert EUROTHERM_6100.scale is Scale.FAHRENHEIT
    assert EUROTHERM_6100.keys == ("C1", "R1", "L1", "L2")


def test_the_honeywell_profile_reads_a_wall_clock() -> None:
    assert HONEYWELL_DR4500.time_unit is TimeUnit.CLOCK
    assert HONEYWELL_DR4500.is_dropout("OPEN")


def test_the_datapaq_profile_is_semicolon_delimited_celsius() -> None:
    assert DATAPAQ_TP3.delimiter == ";"
    assert DATAPAQ_TP3.scale is Scale.CELSIUS
    assert len(DATAPAQ_TP3.columns) == 4


def test_a_library_starts_with_the_built_ins() -> None:
    library = ProfileLibrary.with_built_ins()
    assert len(library) == 3
    assert "eurotherm 6100" in library
    assert "EUROTHERM 6100" in library
    assert library.names() == ["datapaq tp3", "eurotherm 6100", "honeywell dr4500"]


def test_lookup_is_case_insensitive() -> None:
    library = ProfileLibrary.with_built_ins()
    assert library.get(" Eurotherm 6100 ").name == "eurotherm 6100"
    with pytest.raises(NotFoundError):
        library.get("nothing")


def test_the_same_profile_cannot_be_added_twice() -> None:
    library = ProfileLibrary.with_built_ins()
    with pytest.raises(ConflictError):
        library.add(EUROTHERM_6100)


def test_a_new_profile_can_be_added() -> None:
    library = ProfileLibrary()
    library.add(
        MappingProfile(
            name="one off",
            time_heading="t",
            time_unit=TimeUnit.SECONDS,
            scale=Scale.FAHRENHEIT,
            columns=(ColumnMap("a", "C1", ChannelRole.CONTROL),),
        )
    )
    assert len(library) == 1


def test_a_toml_document_becomes_a_profile() -> None:
    import tomllib

    library = ProfileLibrary()
    added = library.load_mapping(tomllib.loads(SAMPLE))
    assert len(added) == 1
    profile = library.get("yokogawa mv1000")
    assert profile.delimiter == ";"
    assert profile.scale is Scale.CELSIUS
    assert profile.time_unit is TimeUnit.SECONDS
    assert profile.keys == ("C1", "L1")
    assert profile.is_dropout("+over")


def test_a_toml_file_is_loaded_from_disk(tmp_path: Path) -> None:
    path = tmp_path / "profiles.toml"
    path.write_text(SAMPLE)
    library = ProfileLibrary()
    library.load_file(path)
    assert "yokogawa mv1000" in library


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ProfileLibrary().load_file(tmp_path / "nope.toml")


def test_a_document_with_no_profiles_is_refused() -> None:
    with pytest.raises(ValidationError):
        ProfileLibrary().load_mapping({})
    with pytest.raises(ValidationError):
        ProfileLibrary().load_mapping({"profile": []})


def test_a_profile_missing_a_field_is_refused() -> None:
    for missing in ("name", "time_heading", "time_unit", "scale"):
        entry = {
            "name": "x",
            "time_heading": "t",
            "time_unit": "seconds",
            "scale": "F",
            "column": [{"heading": "a", "key": "C1", "role": "control"}],
        }
        del entry[missing]
        with pytest.raises(ValidationError):
            build_profile(entry)


def test_a_profile_with_no_columns_is_refused() -> None:
    with pytest.raises(ValidationError):
        build_profile({"name": "x", "time_heading": "t", "time_unit": "seconds", "scale": "F"})


def test_a_column_missing_a_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        build_profile(
            {
                "name": "x",
                "time_heading": "t",
                "time_unit": "seconds",
                "scale": "F",
                "column": [{"heading": "a", "key": "C1"}],
            }
        )


def test_unknown_roles_and_units_are_refused() -> None:
    base = {
        "name": "x",
        "time_heading": "t",
        "time_unit": "seconds",
        "scale": "F",
        "column": [{"heading": "a", "key": "C1", "role": "control"}],
    }
    with pytest.raises(ValidationError):
        build_profile({**base, "time_unit": "fortnights"})
    with pytest.raises(ValidationError):
        build_profile({**base, "column": [{"heading": "a", "key": "C1", "role": "vibes"}]})
