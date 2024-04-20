"""The thermocouple record.

One row per physical couple in the shop, from the day it comes out of the box to
the day somebody cuts the tag off and bins it.

Two properties drive almost every rule that follows and they are not the same
thing, however often they get used as if they were:

**construction** is what the couple physically is. An expendable couple is a
short length of wire with a welded bead, made to be thrown away. A nonexpendable
one lives in a protection tube and gets recalibrated.

**role** is what the couple is being used for on a given day. The same
nonexpendable type N couple can be the furnace control couple this month and a
survey couple next month, and the usage limits are different for each.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum

from ..errors import StateError, ValidationError
from ..identity import SensorTag
from ..temperature import Temperature
from .calibration import Certificate
from .types import ThermocoupleType, ToleranceClass


class Construction(Enum):
    EXPENDABLE = "expendable"
    NONEXPENDABLE = "nonexpendable"

    @property
    def is_expendable(self) -> bool:
        return self is Construction.EXPENDABLE


class SensorRole(Enum):
    """What a couple is being used for."""

    CONTROL = "control"
    RECORD = "record"
    OVER_TEMPERATURE = "over_temperature"
    LOAD = "load"
    SURVEY = "survey"
    TEST = "test"

    @property
    def is_permanent(self) -> bool:
        """A permanently installed couple, as opposed to one placed per load."""
        return self in {SensorRole.CONTROL, SensorRole.RECORD, SensorRole.OVER_TEMPERATURE}


class SensorStatus(Enum):
    IN_STOCK = "in_stock"
    IN_SERVICE = "in_service"
    QUARANTINED = "quarantined"
    SCRAPPED = "scrapped"

    @property
    def is_usable(self) -> bool:
        return self in {SensorStatus.IN_STOCK, SensorStatus.IN_SERVICE}


@dataclass(frozen=True)
class Thermocouple:
    """One physical thermocouple."""

    tag: SensorTag
    kind: ThermocoupleType
    construction: Construction
    role: SensorRole
    grade: ToleranceClass = ToleranceClass.STANDARD
    status: SensorStatus = SensorStatus.IN_STOCK
    received: date | None = None
    certificate: Certificate | None = None
    location: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.grade is ToleranceClass.SPECIAL and not self.kind.has_special_limits():
            raise ValidationError(
                f"type {self.kind.value} is not made to special limits", field="grade"
            )
        if self.construction.is_expendable and self.role in {
            SensorRole.CONTROL,
            SensorRole.OVER_TEMPERATURE,
        }:
            raise ValidationError(
                "an expendable couple cannot be the control or over temperature sensor",
                field="role",
            )

    @property
    def is_calibrated(self) -> bool:
        return self.certificate is not None

    def certificate_or_raise(self) -> Certificate:
        if self.certificate is None:
            raise StateError(
                f"{self.tag} has no calibration certificate", state=self.status.value
            )
        return self.certificate

    def corrected(self, indicated: Temperature) -> Temperature:
        """Apply this couple's calibration to a reading it produced.

        An uncalibrated couple returns the reading untouched rather than
        raising, because an expendable couple used as a load sensor is allowed
        to be uncalibrated and the caller should not have to special case it.
        """
        if self.certificate is None:
            return indicated
        return self.certificate.apply(indicated)

    def with_certificate(self, certificate: Certificate) -> Thermocouple:
        return replace(self, certificate=certificate)

    def put_in_service(self, location: str) -> Thermocouple:
        if self.status is SensorStatus.SCRAPPED:
            raise StateError("a scrapped couple cannot go back in service", state="scrapped")
        if self.status is SensorStatus.QUARANTINED:
            raise StateError("release the couple from quarantine first", state="quarantined")
        if not location.strip():
            raise ValidationError("a couple in service needs a location", field="location")
        return replace(self, status=SensorStatus.IN_SERVICE, location=location.strip())

    def quarantine(self, reason: str) -> Thermocouple:
        if self.status is SensorStatus.SCRAPPED:
            raise StateError("a scrapped couple is already gone", state="scrapped")
        return replace(
            self,
            status=SensorStatus.QUARANTINED,
            notes=(*self.notes, reason),
        )

    def release(self) -> Thermocouple:
        if self.status is not SensorStatus.QUARANTINED:
            raise StateError(
                "only a quarantined couple can be released", state=self.status.value
            )
        return replace(self, status=SensorStatus.IN_STOCK, location="")

    def scrap(self, reason: str) -> Thermocouple:
        return replace(
            self,
            status=SensorStatus.SCRAPPED,
            location="",
            notes=(*self.notes, reason),
        )

    def __str__(self) -> str:
        return f"{self.tag} type {self.kind.value} {self.role.value}"
