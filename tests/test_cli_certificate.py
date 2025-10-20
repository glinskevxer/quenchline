from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from quenchline.cli.main import EXIT_NOT_FOUND, EXIT_STATE, main

TRACE = """Elapsed (min),Channel 1,Channel 2,Channel 3,Channel 4
0,95,96,90,91
30,1540,1541,1536,1537
100,1552,1551,1549,1548
"""


@pytest.fixture()
def cli(tmp_path: Path) -> Callable[..., Result]:
    database = tmp_path / "shop.sqlite"
    settings = tmp_path / "quenchline.toml"
    settings.write_text(
        '[quenchline]\nshop_name = "Ravensthorpe Heat Treat"\ncertificate_prefix = "CERT"\n'
    )

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(
            main,
            [
                "--database",
                str(database),
                "--settings",
                str(settings),
                "--today",
                "2025-08-04",
                *args,
            ],
        )

    return invoke


def run_a_load(cli: Callable[..., Result], tmp_path: Path) -> None:
    cli(
        "recipe",
        "add",
        "HT-4140-Q",
        "--revision",
        "C",
        "--title",
        "4140 harden",
        "--step",
        "ramp:heat:setpoint=1550F,max_rate=4000",
        "--step",
        "soak:austenitise:setpoint=1550F,band=25,minimum=1h",
    )
    cli("recipe", "release", "HT-4140-Q", "--revision", "C")
    cli(
        "load",
        "plan",
        "L25-0001",
        "--work-order",
        "W104417",
        "--furnace",
        "HT-04",
        "--recipe",
        "HT-4140-Q",
        "--revision",
        "C",
        "--weight",
        "1450lb",
        "--part",
        "PN-8891:40:4140",
    )
    cli("load", "charge", "L25-0001")
    cli("load", "start", "L25-0001", "--at", "2025-08-04T07:00:00")
    path = tmp_path / "run.csv"
    path.write_text(TRACE)
    cli("load", "attach", "L25-0001", str(path), "--profile", "eurotherm 6100")
    cli("load", "finish", "L25-0001", "--at", "2025-08-04T12:00:00")


def test_a_complete_load_cannot_be_certificated(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    run_a_load(cli, tmp_path)
    result = cli("report", "certificate", "L25-0001")
    assert result.exit_code == EXIT_STATE


def test_certifying_then_printing(cli: Callable[..., Result], tmp_path: Path) -> None:
    run_a_load(cli, tmp_path)
    assert "certified" in cli("load", "certify", "L25-0001").output
    result = cli("report", "certificate", "L25-0001")
    assert result.exit_code == 0
    assert "certificate of conformance" in result.output
    assert "CERT-L25-0001" in result.output
    assert "Ravensthorpe Heat Treat" in result.output
    assert "PN-8891" in result.output
    assert "HT-4140-Q rev C" in result.output


def test_the_certificate_number_can_be_given(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    run_a_load(cli, tmp_path)
    cli("load", "certify", "L25-0001")
    result = cli("report", "certificate", "L25-0001", "--number", "CERT-25-0099")
    assert "CERT-25-0099" in result.output


def test_the_customer_block_is_printed(cli: Callable[..., Result], tmp_path: Path) -> None:
    run_a_load(cli, tmp_path)
    cli("load", "certify", "L25-0001")
    result = cli(
        "report",
        "certificate",
        "L25-0001",
        "--customer",
        "Bardsley Gears",
        "--customer-order",
        "PO-88431",
        "--specification",
        "AMS 2759/2",
        "--signatory",
        "D Turnbull",
    )
    assert "Bardsley Gears" in result.output
    assert "PO-88431" in result.output
    assert "AMS 2759/2" in result.output
    assert "D Turnbull" in result.output


def test_certifying_an_incomplete_load_is_refused(cli: Callable[..., Result]) -> None:
    cli(
        "load",
        "plan",
        "L25-0002",
        "--work-order",
        "W104417",
        "--furnace",
        "HT-04",
        "--recipe",
        "HT-4140-Q",
        "--revision",
        "C",
    )
    assert cli("load", "certify", "L25-0002").exit_code == EXIT_STATE


def test_a_certificate_for_an_unknown_load(cli: Callable[..., Result]) -> None:
    assert cli("report", "certificate", "L25-9999").exit_code == EXIT_NOT_FOUND


def test_the_module_entry_point_runs() -> None:
    from quenchline.__main__ import entry

    assert callable(entry)


def test_running_the_module_prints_help() -> None:
    """``python -m quenchline`` works however the suite itself was started.

    The subprocess gets an explicit import path built from where the package
    actually is, rather than inheriting whatever the parent happened to have.
    Without that this passes under one invocation and fails under another, which
    is the least useful kind of test.
    """
    import os
    import subprocess
    import sys

    import quenchline

    package_root = str(Path(quenchline.__file__).resolve().parent.parent)
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        f"{package_root}{os.pathsep}{existing}" if existing else package_root
    )
    finished = subprocess.run(
        [sys.executable, "-m", "quenchline", "--help"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert finished.returncode == 0, finished.stderr
    assert "furnace" in finished.stdout
