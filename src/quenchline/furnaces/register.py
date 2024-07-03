"""The furnace register."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import ConflictError, NotFoundError
from ..identity import FurnaceTag, SensorTag
from ..temperature import Temperature
from .classes import FurnaceClass, InstrumentationType
from .record import Deficiency, Furnace, FurnaceStatus


@dataclass
class FurnaceRegister:
    """Every furnace in the shop."""

    furnaces: dict[str, Furnace] = field(default_factory=dict)

    def add(self, furnace: Furnace) -> None:
        key = str(furnace.tag)
        if key in self.furnaces:
            raise ConflictError("furnace", key)
        self.furnaces[key] = furnace

    def get(self, tag: FurnaceTag | str) -> Furnace:
        key = str(tag)
        if key not in self.furnaces:
            raise NotFoundError("furnace", key)
        return self.furnaces[key]

    def replace(self, furnace: Furnace) -> None:
        key = str(furnace.tag)
        if key not in self.furnaces:
            raise NotFoundError("furnace", key)
        self.furnaces[key] = furnace

    def __len__(self) -> int:
        return len(self.furnaces)

    def __contains__(self, tag: object) -> bool:
        return str(tag) in self.furnaces

    def all(self) -> list[Furnace]:
        return [self.furnaces[key] for key in sorted(self.furnaces)]

    def in_service(self) -> list[Furnace]:
        return [f for f in self.all() if f.status is FurnaceStatus.IN_SERVICE]

    def of_class(self, furnace_class: FurnaceClass) -> list[Furnace]:
        return [f for f in self.all() if f.furnace_class is furnace_class]

    def with_instrumentation(self, instrumentation: InstrumentationType) -> list[Furnace]:
        return [f for f in self.all() if f.instrumentation is instrumentation]

    def able_to_run(self, at: Temperature) -> list[Furnace]:
        """Every furnace that could take a job at this temperature right now."""
        return [f for f in self.all() if f.may_run(at)]

    def deficient(self) -> list[tuple[Furnace, tuple[Deficiency, ...]]]:
        """Every furnace that does not match what it claims to be."""
        out: list[tuple[Furnace, tuple[Deficiency, ...]]] = []
        for furnace in self.all():
            found = furnace.deficiencies()
            if found:
                out.append((furnace, found))
        return out

    def find_sensor(self, tag: SensorTag | str) -> Furnace | None:
        """Which furnace a sensor is wired to, if any."""
        wanted = str(tag)
        for furnace in self.all():
            if any(str(sensor) == wanted for _, sensor in furnace.sensors):
                return furnace
        return None

    def tightest_tolerance(self) -> Furnace | None:
        """The furnace holding the tightest uniformity band."""
        furnaces = self.all()
        if not furnaces:
            return None
        return min(furnaces, key=lambda f: f.tolerance.degf)


def build_register(furnaces: list[Furnace]) -> FurnaceRegister:
    register = FurnaceRegister()
    for furnace in furnaces:
        register.add(furnace)
    return register
