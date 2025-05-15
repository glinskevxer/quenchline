"""Which furnace should take this job.

The scheduler asks this a dozen times a shift and the wrong answer is expensive
in two different directions. Putting a job on a furnace that cannot hold the
band scraps the metal. Putting a job that needs plus or minus fifty on the one
class 1 vacuum furnace ties up the only machine that can do the tight work.

So a candidate is scored on two things that pull against each other:

* it must be **able**, which is a hard gate: in service, qualified at the
  temperature, a zone that reaches it, a zone big enough for the load, and no
  outstanding instrumentation shortfall.
* among the able ones it is ranked by **fit**, and a furnace whose band is much
  tighter than the job needs is ranked *worse*, not better. That is the part
  that surprises people, and it is the whole point of having six furnaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import ValidationError
from ..furnaces.classes import uniformity_tolerance
from ..furnaces.record import Deficiency, Furnace
from ..measure import Volume
from ..temperature import Temperature, TemperatureDelta


class Refusal(Enum):
    """Why a furnace cannot take a job."""

    OUT_OF_SERVICE = "out_of_service"
    NOT_QUALIFIED = "not_qualified"
    NO_ZONE_AT_TEMPERATURE = "no_zone_at_temperature"
    ZONE_TOO_SMALL = "zone_too_small"
    BAND_TOO_WIDE = "band_too_wide"
    INSTRUMENTATION_SHORT = "instrumentation_short"


@dataclass(frozen=True)
class Job:
    """What a job needs from a furnace."""

    at: Temperature
    band: TemperatureDelta
    volume: Volume | None = None

    def __post_init__(self) -> None:
        if self.band.degf <= 0:
            raise ValidationError("a job needs a positive band", field="band")


@dataclass(frozen=True)
class Candidate:
    """One furnace measured against one job."""

    furnace: Furnace
    refusals: tuple[Refusal, ...]
    slack: float
    spare_volume: float | None

    @property
    def is_able(self) -> bool:
        return not self.refusals

    @property
    def tag(self) -> str:
        return str(self.furnace.tag)

    def __str__(self) -> str:
        if self.is_able:
            return f"{self.tag} fits with {self.slack:.2f} of the band to spare"
        return f"{self.tag} refused: " + ", ".join(r.value for r in self.refusals)


def assess(furnace: Furnace, job: Job) -> Candidate:
    """Measure one furnace against one job."""
    refusals: list[Refusal] = []

    if not furnace.status.can_run_work:
        refusals.append(Refusal.OUT_OF_SERVICE)
    if furnace.qualified is None or not furnace.qualified.covers(job.at):
        refusals.append(Refusal.NOT_QUALIFIED)

    reaching = [zone for zone in furnace.zones if zone.covers(job.at)]
    if not reaching:
        refusals.append(Refusal.NO_ZONE_AT_TEMPERATURE)

    spare: float | None = None
    if job.volume is not None:
        big_enough = [
            zone for zone in reaching if zone.volume.cubic_feet >= job.volume.cubic_feet
        ]
        if reaching and not big_enough:
            refusals.append(Refusal.ZONE_TOO_SMALL)
        if big_enough:
            largest = max(z.volume.cubic_feet for z in big_enough)
            spare = largest - job.volume.cubic_feet

    tolerance = uniformity_tolerance(furnace.furnace_class)
    if tolerance.degf > job.band.degf + 1e-9:
        refusals.append(Refusal.BAND_TOO_WIDE)
    if Deficiency.NO_WORK_ZONE not in furnace.deficiencies() and furnace.deficiencies():
        refusals.append(Refusal.INSTRUMENTATION_SHORT)

    slack = (job.band.degf - tolerance.degf) / job.band.degf
    return Candidate(furnace, tuple(refusals), slack, spare)


def rank(furnaces: list[Furnace], job: Job) -> list[Candidate]:
    """Every furnace measured, best fit first, refusals last."""
    candidates = [assess(furnace, job) for furnace in furnaces]

    def key(candidate: Candidate) -> tuple[int, float, str]:
        return (0 if candidate.is_able else 1, candidate.slack, candidate.tag)

    return sorted(candidates, key=key)


def choose(furnaces: list[Furnace], job: Job) -> Candidate:
    """The furnace to put the job on, or an error naming why there is none."""
    ranked = rank(furnaces, job)
    able = [candidate for candidate in ranked if candidate.is_able]
    if not able:
        raise ValidationError(
            f"no furnace can hold {job.band.format()} at {job.at.format()}", field="job"
        )
    return able[0]


def able_count(furnaces: list[Furnace], job: Job) -> int:
    return sum(1 for candidate in rank(furnaces, job) if candidate.is_able)
