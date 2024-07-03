"""The furnace record.

Everything the shop knows about one piece of thermal processing equipment: what
class it holds, how it is instrumented, what work zones it has, which sensors
and instruments are wired to it, and what temperatures it is currently qualified
to run.

The record is where the two independent gradings from :mod:`quenchline.furnaces.classes`
finally meet something physical, and where a furnace can be found to be lying
about itself. A furnace declared type A that has one control sensor wired to it
is not a type A furnace, whatever the sign on the front says.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from ..errors import StateError, ValidationError
from ..identity import FurnaceTag, InstrumentTag, SensorTag
from ..sensors.record import SensorRole
from ..temperature import Temperature, TemperatureDelta
from .classes import (
    FurnaceClass,
    InstrumentationType,
    sensor_requirements,
    uniformity_tolerance,
)
from .zones import QualifiedRange, WorkZone, survey_sensor_count


class FurnaceStatus(Enum):
    IN_SERVICE = "in_service"
    DOWN = "down"
    MOTHBALLED = "mothballed"

    @property
    def can_run_work(self) -> bool:
        return self is FurnaceStatus.IN_SERVICE


class Deficiency(Enum):
    """A way in which a furnace does not match what it claims to be."""

    TOO_FEW_CONTROL_SENSORS = "too_few_control_sensors"
    NO_RECORDER = "no_recorder"
    NO_OVER_TEMPERATURE = "no_over_temperature"
    NO_LOAD_SENSORS = "no_load_sensors"
    NO_WORK_ZONE = "no_work_zone"
    NOT_QUALIFIED = "not_qualified"


@dataclass(frozen=True)
class Furnace:
    """One furnace."""

    tag: FurnaceTag
    furnace_class: FurnaceClass
    instrumentation: InstrumentationType
    zones: tuple[WorkZone, ...] = field(default_factory=tuple)
    sensors: tuple[tuple[SensorRole, SensorTag], ...] = field(default_factory=tuple)
    instruments: tuple[InstrumentTag, ...] = field(default_factory=tuple)
    qualified: QualifiedRange | None = None
    status: FurnaceStatus = FurnaceStatus.IN_SERVICE
    description: str = ""

    def __post_init__(self) -> None:
        names = [z.name for z in self.zones]
        if len(set(names)) != len(names):
            raise ValidationError("two work zones share a name", field="zones")
        tags = [str(tag) for _, tag in self.sensors]
        if len(set(tags)) != len(tags):
            raise ValidationError("the same sensor is wired twice", field="sensors")

    @property
    def tolerance(self) -> TemperatureDelta:
        return uniformity_tolerance(self.furnace_class)

    def zone(self, name: str) -> WorkZone:
        for candidate in self.zones:
            if candidate.name == name:
                return candidate
        raise ValidationError(f"{self.tag} has no work zone named {name!r}", field="zone")

    def sensors_in_role(self, role: SensorRole) -> tuple[SensorTag, ...]:
        return tuple(tag for wired_role, tag in self.sensors if wired_role is role)

    def sensor_count(self, role: SensorRole) -> int:
        return len(self.sensors_in_role(role))

    def survey_sensors_needed(self, zone_name: str) -> int:
        return survey_sensor_count(self.zone(zone_name).volume, self.furnace_class)

    def wire(self, role: SensorRole, tag: SensorTag) -> Furnace:
        if any(str(existing) == str(tag) for _, existing in self.sensors):
            raise ValidationError(f"{tag} is already wired to {self.tag}", field="sensor")
        return replace(self, sensors=(*self.sensors, (role, tag)))

    def unwire(self, tag: SensorTag) -> Furnace:
        remaining = tuple(pair for pair in self.sensors if str(pair[1]) != str(tag))
        if len(remaining) == len(self.sensors):
            raise ValidationError(f"{tag} is not wired to {self.tag}", field="sensor")
        return replace(self, sensors=remaining)

    def add_zone(self, zone: WorkZone) -> Furnace:
        if any(z.name == zone.name for z in self.zones):
            raise ValidationError(f"{self.tag} already has a zone {zone.name!r}", field="zone")
        return replace(self, zones=(*self.zones, zone))

    def qualify(self, qualified: QualifiedRange) -> Furnace:
        return replace(self, qualified=qualified)

    def widen_qualification(self, at: Temperature) -> Furnace:
        if self.qualified is None:
            return replace(self, qualified=QualifiedRange.single(at))
        return replace(self, qualified=self.qualified.extended_to(at))

    def revoke_qualification(self) -> Furnace:
        return replace(self, qualified=None)

    def may_run(self, at: Temperature) -> bool:
        """Whether the furnace may take work at this temperature today."""
        if not self.status.can_run_work:
            return False
        if self.qualified is None:
            return False
        if not self.qualified.covers(at):
            return False
        return any(zone.covers(at) for zone in self.zones)

    def deficiencies(self, at: Temperature | None = None) -> tuple[Deficiency, ...]:
        """Every way the furnace falls short of what it claims to be."""
        required = sensor_requirements(self.instrumentation)
        found: list[Deficiency] = []
        if self.sensor_count(SensorRole.CONTROL) < required.control_sensors:
            found.append(Deficiency.TOO_FEW_CONTROL_SENSORS)
        if required.recording_required and self.sensor_count(SensorRole.RECORD) < 1:
            found.append(Deficiency.NO_RECORDER)
        if required.over_temperature_required and (
            self.sensor_count(SensorRole.OVER_TEMPERATURE) < 1
        ):
            found.append(Deficiency.NO_OVER_TEMPERATURE)
        if required.load_sensors_required and self.sensor_count(SensorRole.LOAD) < 1:
            found.append(Deficiency.NO_LOAD_SENSORS)
        if not self.zones:
            found.append(Deficiency.NO_WORK_ZONE)
        if at is not None and not self.may_run(at):
            found.append(Deficiency.NOT_QUALIFIED)
        return tuple(found)

    def take_down(self, reason: str) -> Furnace:
        if not reason.strip():
            raise ValidationError("give a reason", field="reason")
        return replace(self, status=FurnaceStatus.DOWN)

    def bring_up(self) -> Furnace:
        if self.status is FurnaceStatus.MOTHBALLED:
            raise StateError("recommission a mothballed furnace first", state="mothballed")
        return replace(self, status=FurnaceStatus.IN_SERVICE)

    def mothball(self) -> Furnace:
        return replace(self, status=FurnaceStatus.MOTHBALLED, qualified=None)

    def __str__(self) -> str:
        return f"{self.tag} {self.furnace_class} type {self.instrumentation.value}"
