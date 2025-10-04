"""The schema, as an ordered list of migrations.

Hand rolled rather than a framework, because the schema is small and the
guarantees this shop needs are specific.

Every migration carries a **checksum of its own statements**. When the database
is opened, the checksum of each already applied migration is compared against
the checksum recorded when it ran. If somebody edits migration 3 after it has
been applied in the field, the database will not open, and it says which
migration and what the two checksums were.

That is the whole reason for the design. A schema that drifts silently between
one shop's install and another's is how a report that works here returns nothing
there, and a checksum turns a mystery into a message on startup.

Migrations are **append only**. To change something, add a migration. The list
here is the truth, the database is the record of what has been done to it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..errors import ValidationError


def checksum_of(statements: tuple[str, ...]) -> str:
    """A stable digest of a migration's statements.

    Whitespace is normalised so reindenting a migration does not look like a
    change to it, but every other character counts.
    """
    normalised = "\n".join(" ".join(statement.split()) for statement in statements)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class Migration:
    """One numbered step of the schema."""

    version: int
    name: str
    statements: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValidationError("migration versions start at one", field="version")
        if not self.name.strip():
            raise ValidationError("a migration needs a name", field="name")
        if not self.statements:
            raise ValidationError("a migration needs statements", field="statements")

    @property
    def checksum(self) -> str:
        return checksum_of(self.statements)

    def __str__(self) -> str:
        return f"{self.version:03d} {self.name}"


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        1,
        "furnaces and zones",
        (
            """
            CREATE TABLE furnace (
                tag TEXT PRIMARY KEY,
                furnace_class INTEGER NOT NULL,
                instrumentation TEXT NOT NULL,
                status TEXT NOT NULL,
                qualified_low REAL,
                qualified_high REAL,
                description TEXT NOT NULL DEFAULT ''
            )
            """,
            """
            CREATE TABLE work_zone (
                furnace_tag TEXT NOT NULL REFERENCES furnace(tag) ON DELETE CASCADE,
                name TEXT NOT NULL,
                cubic_feet REAL NOT NULL,
                low_f REAL NOT NULL,
                high_f REAL NOT NULL,
                PRIMARY KEY (furnace_tag, name)
            )
            """,
        ),
    ),
    Migration(
        2,
        "sensors and certificates",
        (
            """
            CREATE TABLE thermocouple (
                tag TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                construction TEXT NOT NULL,
                role TEXT NOT NULL,
                grade TEXT NOT NULL,
                status TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT '',
                certificate_number TEXT
            )
            """,
            """
            CREATE TABLE certificate (
                number TEXT PRIMARY KEY,
                issued TEXT NOT NULL,
                convention TEXT NOT NULL,
                laboratory TEXT NOT NULL DEFAULT '',
                accredited INTEGER NOT NULL DEFAULT 1
            )
            """,
            """
            CREATE TABLE certificate_point (
                certificate_number TEXT NOT NULL
                    REFERENCES certificate(number) ON DELETE CASCADE,
                nominal_f REAL NOT NULL,
                value_f REAL NOT NULL,
                PRIMARY KEY (certificate_number, nominal_f)
            )
            """,
        ),
    ),
    Migration(
        3,
        "sensor usage",
        (
            """
            CREATE TABLE sensor_use (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor_tag TEXT NOT NULL REFERENCES thermocouple(tag) ON DELETE CASCADE,
                used_on TEXT NOT NULL,
                peak_f REAL NOT NULL,
                seconds REAL NOT NULL,
                role TEXT NOT NULL,
                reference TEXT NOT NULL DEFAULT ''
            )
            """,
            "CREATE INDEX sensor_use_by_tag ON sensor_use(sensor_tag)",
        ),
    ),
    Migration(
        4,
        "loads and parts",
        (
            """
            CREATE TABLE load_record (
                lot TEXT PRIMARY KEY,
                work_order TEXT NOT NULL,
                furnace_tag TEXT NOT NULL,
                recipe_code TEXT NOT NULL,
                recipe_revision TEXT NOT NULL,
                state TEXT NOT NULL,
                weight_lb REAL,
                charged_at TEXT,
                started_at TEXT,
                finished_at TEXT
            )
            """,
            """
            CREATE TABLE load_part (
                lot TEXT NOT NULL REFERENCES load_record(lot) ON DELETE CASCADE,
                part_number TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                material TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (lot, part_number)
            )
            """,
            "CREATE INDEX load_by_furnace ON load_record(furnace_tag)",
        ),
    ),
    Migration(
        5,
        "nonconformance",
        (
            """
            CREATE TABLE nonconformance (
                number TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                reference TEXT NOT NULL,
                raised_on TEXT NOT NULL,
                summary TEXT NOT NULL,
                stage TEXT NOT NULL,
                disposition TEXT,
                suspect_from TEXT,
                suspect_to TEXT
            )
            """,
            "CREATE INDEX ncr_by_reference ON nonconformance(reference)",
        ),
    ),
    Migration(
        6,
        "load trace reference",
        (
            "ALTER TABLE load_record ADD COLUMN trace_source TEXT",
            "ALTER TABLE load_record ADD COLUMN trace_digest TEXT",
            "ALTER TABLE load_record ADD COLUMN trace_started TEXT",
            "CREATE INDEX load_by_trace_digest ON load_record(trace_digest)",
        ),
    ),
    Migration(
        7,
        "furnace sensors",
        (
            """
            CREATE TABLE furnace_sensor (
                furnace_tag TEXT NOT NULL REFERENCES furnace(tag) ON DELETE CASCADE,
                sensor_tag TEXT NOT NULL,
                role TEXT NOT NULL,
                PRIMARY KEY (furnace_tag, sensor_tag)
            )
            """,
            "CREATE INDEX furnace_sensor_by_sensor ON furnace_sensor(sensor_tag)",
        ),
    ),
    Migration(
        8,
        "system accuracy tests",
        (
            """
            CREATE TABLE sat_test (
                number TEXT PRIMARY KEY,
                furnace_tag TEXT NOT NULL,
                performed TEXT NOT NULL,
                setpoint_f REAL NOT NULL,
                method TEXT NOT NULL,
                apply_corrections INTEGER NOT NULL DEFAULT 1,
                technician TEXT NOT NULL DEFAULT '',
                system_indicated_f REAL NOT NULL,
                system_sensor_correction_f REAL NOT NULL,
                system_instrument_correction_f REAL NOT NULL,
                system_sensor TEXT,
                system_instrument TEXT,
                test_indicated_f REAL NOT NULL,
                test_sensor_correction_f REAL NOT NULL,
                test_instrument_correction_f REAL NOT NULL,
                test_sensor TEXT,
                test_instrument TEXT
            )
            """,
            "CREATE INDEX sat_by_furnace ON sat_test(furnace_tag, performed)",
        ),
    ),
    Migration(
        9,
        "recipes and steps",
        (
            """
            CREATE TABLE recipe (
                code TEXT NOT NULL,
                revision TEXT NOT NULL,
                title TEXT NOT NULL,
                material TEXT NOT NULL DEFAULT '',
                load_sensors INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL,
                released_on TEXT,
                superseded_on TEXT,
                author TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (code, revision)
            )
            """,
            """
            CREATE TABLE recipe_step (
                code TEXT NOT NULL,
                revision TEXT NOT NULL,
                position INTEGER NOT NULL,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                setpoint_f REAL,
                tolerance_f REAL,
                minimum_seconds REAL,
                maximum_seconds REAL,
                ramp_maximum REAL,
                ramp_minimum REAL,
                quench_delay_seconds REAL,
                medium TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (code, revision, position),
                FOREIGN KEY (code, revision)
                    REFERENCES recipe(code, revision) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX recipe_by_state ON recipe(code, state)",
        ),
    ),
    Migration(
        10,
        "load trace profile",
        ("ALTER TABLE load_record ADD COLUMN trace_profile TEXT",),
    ),
    Migration(
        11,
        "quench baths",
        (
            """
            CREATE TABLE quench_bath (
                identifier TEXT PRIMARY KEY,
                medium_name TEXT NOT NULL,
                medium_kind TEXT NOT NULL,
                setpoint_f REAL NOT NULL,
                band_f REAL NOT NULL,
                minimum_agitation INTEGER NOT NULL,
                concentration_low REAL,
                concentration_high REAL,
                melting_point_f REAL,
                gallons REAL NOT NULL,
                temperature_f REAL NOT NULL,
                agitation INTEGER NOT NULL,
                concentration REAL,
                last_checked TEXT,
                check_interval_count INTEGER NOT NULL,
                check_interval_unit TEXT NOT NULL,
                in_service INTEGER NOT NULL DEFAULT 1
            )
            """,
        ),
    ),
    Migration(
        12,
        "instruments and calibrations",
        (
            """
            CREATE TABLE instrument (
                tag TEXT PRIMARY KEY,
                function TEXT NOT NULL,
                span_low_f REAL NOT NULL,
                span_high_f REAL NOT NULL,
                accuracy_percent REAL NOT NULL,
                accuracy_basis TEXT NOT NULL,
                accuracy_floor_f REAL NOT NULL DEFAULT 0,
                resolution_f REAL NOT NULL,
                readout TEXT NOT NULL,
                interval_count INTEGER NOT NULL,
                interval_unit TEXT NOT NULL,
                due_rule TEXT NOT NULL,
                status TEXT NOT NULL,
                make TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                serial TEXT NOT NULL DEFAULT ''
            )
            """,
            """
            CREATE TABLE instrument_calibration (
                number TEXT PRIMARY KEY,
                instrument_tag TEXT NOT NULL
                    REFERENCES instrument(tag) ON DELETE CASCADE,
                performed TEXT NOT NULL,
                tolerance_f REAL NOT NULL,
                technician TEXT NOT NULL DEFAULT '',
                standard TEXT NOT NULL DEFAULT ''
            )
            """,
            """
            CREATE TABLE instrument_check (
                calibration_number TEXT NOT NULL
                    REFERENCES instrument_calibration(number) ON DELETE CASCADE,
                nominal_f REAL NOT NULL,
                as_found_f REAL NOT NULL,
                as_left_f REAL,
                PRIMARY KEY (calibration_number, nominal_f)
            )
            """,
            "CREATE INDEX calibration_by_instrument "
            "ON instrument_calibration(instrument_tag, performed)",
        ),
    ),
    Migration(
        13,
        "audit trail",
        (
            """
            CREATE TABLE audit_entry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                subject TEXT NOT NULL,
                reference TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT ''
            )
            """,
            "CREATE INDEX audit_by_reference ON audit_entry(subject, reference)",
            "CREATE INDEX audit_by_time ON audit_entry(at)",
        ),
    ),
    Migration(
        14,
        "survey outcomes",
        (
            """
            CREATE TABLE survey_outcome (
                number TEXT PRIMARY KEY,
                furnace_tag TEXT NOT NULL,
                zone TEXT NOT NULL,
                performed TEXT NOT NULL,
                passed INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE survey_setpoint (
                survey_number TEXT NOT NULL
                    REFERENCES survey_outcome(number) ON DELETE CASCADE,
                setpoint_f REAL NOT NULL,
                passed INTEGER NOT NULL,
                PRIMARY KEY (survey_number, setpoint_f)
            )
            """,
            "CREATE INDEX survey_by_zone ON survey_outcome(furnace_tag, zone, performed)",
        ),
    ),
)


def validate(migrations: tuple[Migration, ...] = MIGRATIONS) -> None:
    """Check the migration list is a contiguous run starting at one."""
    if not migrations:
        raise ValidationError("there are no migrations", field="migrations")
    versions = [m.version for m in migrations]
    if versions != sorted(versions):
        raise ValidationError("migrations are out of order", field="migrations")
    if len(set(versions)) != len(versions):
        raise ValidationError("two migrations share a version", field="migrations")
    expected = list(range(1, len(migrations) + 1))
    if versions != expected:
        raise ValidationError(
            f"migration versions are not contiguous: {versions}", field="migrations"
        )
    names = [m.name for m in migrations]
    if len(set(names)) != len(names):
        raise ValidationError("two migrations share a name", field="migrations")


def latest_version(migrations: tuple[Migration, ...] = MIGRATIONS) -> int:
    return max(m.version for m in migrations)


def find(version: int, migrations: tuple[Migration, ...] = MIGRATIONS) -> Migration:
    for migration in migrations:
        if migration.version == version:
            return migration
    raise ValidationError(f"there is no migration {version}", field="version")
