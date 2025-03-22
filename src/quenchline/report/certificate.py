"""The certificate of conformance.

This is the piece of paper that leaves the building with the parts, and it is
the only output of this package that anybody outside the shop reads. Two rules
govern what goes on it and both exist because of what a certificate is *for*.

**Nothing goes on it that is not evidenced.** A hardness figure that came from a
converted reading is marked as converted or it is left off. A cycle the load did
not actually meet is not described as met.

**It refuses to be issued rather than issuing something untrue.** A load that
was not certified does not get a certificate, and asking for one raises. Shops
that let the paperwork run ahead of the metal are the reason customers audit
shops.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..errors import StateError, ValidationError
from ..hardness.sampling import LotResult, Specification
from ..loads.record import Load, LoadState
from ..recipes.cycle import Recipe
from .table import Align, Column, Table, render_kv


@dataclass(frozen=True)
class CertificateHeader:
    """Who the certificate is for and who issued it."""

    number: str
    issued_on: date
    shop_name: str
    customer: str = ""
    customer_order: str = ""
    specification: str = ""
    signatory: str = ""

    def __post_init__(self) -> None:
        if not self.number.strip():
            raise ValidationError("a certificate needs a number", field="number")
        if not self.shop_name.strip():
            raise ValidationError("a certificate needs a shop name", field="shop_name")


def cycle_table(recipe: Recipe) -> Table:
    """The cycle as it was written, for the back of the certificate."""
    table = Table(
        columns=[
            Column("step"),
            Column("kind"),
            Column("setpoint", align=Align.RIGHT, places=0),
            Column("band", align=Align.RIGHT, places=0),
            Column("minimum"),
            Column("medium"),
        ],
        title=f"cycle {recipe.identifier}",
    )
    for step in recipe.steps:
        band = step.band
        table.add(
            step.name,
            step.kind.value,
            step.setpoint.degf if step.setpoint is not None else None,
            band.plus.degf if band is not None else None,
            step.minimum_time.format() if step.minimum_time is not None else None,
            step.medium or None,
        )
    return table


def hardness_table(result: LotResult, specification: Specification) -> Table:
    table = Table(
        columns=[
            Column("reading", align=Align.RIGHT, places=1),
            Column("scale"),
            Column("source"),
            Column("verdict"),
        ],
        title=f"hardness against {specification}",
    )
    for reading in result.readings:
        table.add(
            reading.value,
            reading.scale.value,
            "converted" if reading.converted else "measured",
            "in" if specification.contains(reading) else "out",
        )
    return table


def certificate_text(
    header: CertificateHeader,
    load: Load,
    recipe: Recipe,
    hardness: tuple[LotResult, Specification] | None = None,
) -> str:
    """Render the certificate for one certified load."""
    if load.state is not LoadState.CERTIFIED:
        raise StateError(
            f"load {load.lot} is {load.state.value} and cannot be certificated",
            state=load.state.value,
        )
    if load.recipe_code != recipe.code or load.recipe_revision != recipe.revision:
        raise ValidationError(
            f"load {load.lot} ran {load.recipe}, not {recipe.identifier}", field="recipe"
        )

    blocks = [
        render_kv(
            [
                ("certificate", header.number),
                ("issued", header.issued_on.isoformat()),
                ("shop", header.shop_name),
                ("customer", header.customer or None),
                ("customer order", header.customer_order or None),
                ("specification", header.specification or None),
            ],
            title="certificate of conformance",
        ),
        render_kv(
            [
                ("lot", str(load.lot)),
                ("work order", str(load.work_order)),
                ("furnace", str(load.furnace)),
                ("cycle", load.recipe),
                ("pieces", load.piece_count),
                ("weight", str(load.weight) if load.weight is not None else None),
                (
                    "processed",
                    load.finished_at.date().isoformat() if load.finished_at else None,
                ),
            ],
            title="load",
        ),
        _parts_block(load),
        cycle_table(recipe).render(),
    ]

    if hardness is not None:
        result, specification = hardness
        blocks.append(hardness_table(result, specification).render())
        blocks.append(
            render_kv(
                [
                    ("verdict", result.verdict.value),
                    ("readings", len(result.readings)),
                    ("average", round(result.average, 1) if result.average else None),
                ],
                title="hardness result",
            )
        )

    blocks.append(
        render_kv(
            [("signed", header.signatory or None), ("date", header.issued_on.isoformat())],
            title="certification",
        )
    )
    return "\n\n".join(blocks)


def _parts_block(load: Load) -> str:
    table = Table(
        columns=[
            Column("part number"),
            Column("quantity", align=Align.RIGHT),
            Column("material"),
        ],
        title="parts",
    )
    for line in load.parts:
        table.add(line.part_number, line.quantity, line.material or None)
    return table.render()
