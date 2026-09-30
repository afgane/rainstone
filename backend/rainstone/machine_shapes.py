"""How large a priced machine type is, from Google's published specifications.

The collector records which machine type a resource was, never its capacity.
The size of a predefined shape is a published fact, so it comes from the
reviewed registry the price publisher is built on. A machine type the registry
does not list has no capacity here rather than a guessed one.
"""

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from rainstone.config import get_settings

MIB_PER_GIB = Decimal(1024)
SOURCE = "published_machine_shape"


@lru_cache(maxsize=4)
def _shapes(path: Path) -> dict[str, tuple[int, Decimal]]:
    try:
        entries = json.loads(path.read_text())["shapes"]
        return {
            entry["machine_type"]: (int(entry["vcpu"]), Decimal(entry["memory_gib"]) * MIB_PER_GIB)
            for entry in entries
        }
    except (OSError, ValueError, KeyError, TypeError):
        # A report is still useful without sizes, so a missing registry only removes them.
        return {}


def machine_capacity(provider: str, machine_type: str | None) -> dict | None:
    """The machine's own vCPUs and memory, never what a job asked of it."""
    if provider != "gcp" or not machine_type:
        return None
    shape = _shapes(get_settings().machine_shapes_path).get(machine_type)
    if shape is None:
        return None
    vcpu, memory_mib = shape
    return {"vcpu": str(vcpu), "memory_mib": format(memory_mib.normalize(), "f"), "source": SOURCE}
