"""The checked-in registry of machine shapes this publisher prices.

Regional prices are never stored here: the registry names which shapes exist
and how large they are, and the Catalog API supplies the money.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

DEFAULT_PATH = Path("catalog/gcp-machine-shapes.json")


class ShapeRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class ShapeGpu:
    count: int
    model: str


@dataclass(frozen=True)
class MachineShape:
    machine_type: str
    family: str  # "t2d", "n2" or "g2"
    variant: str  # "standard", "highmem" or "highcpu"
    vcpu: int
    memory_gib: Decimal
    source_ref: str
    gpu: ShapeGpu | None = None


def _gpu(entry: dict) -> ShapeGpu | None:
    """The GPUs a shape always comes with, from optional `gpu_count`/`gpu_model`."""
    has_count, has_model = "gpu_count" in entry, "gpu_model" in entry
    if not (has_count or has_model):
        return None
    if not (has_count and has_model):
        raise ShapeRegistryError(f"{entry['machine_type']} needs both gpu_count and gpu_model")
    count = entry["gpu_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ShapeRegistryError(f"{entry['machine_type']} gpu_count must be a positive integer")
    model = entry["gpu_model"]
    if not isinstance(model, str) or not model.strip():
        raise ShapeRegistryError(f"{entry['machine_type']} gpu_model must be a name")
    return ShapeGpu(count=count, model=model)


def load_shapes(path: Path = DEFAULT_PATH) -> tuple[MachineShape, ...]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise ShapeRegistryError(f"machine shape registry not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ShapeRegistryError(f"machine shape registry is not valid JSON: {error}") from error
    shapes: list[MachineShape] = []
    seen: set[str] = set()
    for entry in data.get("shapes", []):
        missing = {"machine_type", "family", "variant", "vcpu", "memory_gib", "source_ref"} - entry.keys()
        if missing:
            raise ShapeRegistryError(f"shape entry is missing fields: {', '.join(sorted(missing))}")
        if entry["machine_type"] in seen:
            raise ShapeRegistryError(f"duplicate machine shape: {entry['machine_type']}")
        seen.add(entry["machine_type"])
        shapes.append(
            MachineShape(
                machine_type=entry["machine_type"],
                family=entry["family"],
                variant=entry["variant"],
                vcpu=int(entry["vcpu"]),
                memory_gib=Decimal(str(entry["memory_gib"])),
                source_ref=entry["source_ref"],
                gpu=_gpu(entry),
            )
        )
    if not shapes:
        raise ShapeRegistryError(f"machine shape registry at {path} has no shapes")
    return tuple(shapes)
