"""Assemble, sign and write the publisher's catalog artifact.

Reuses `rainstone.catalog.canonical_content` for the exact bytes that get
signed, so the publisher and the application never disagree about what a
signature covers.
"""

import base64
import hashlib
import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from rainstone.catalog import canonical_content

from gcp_pricing.mapping import PRICED_REGION_PREFIX, ComponentRates
from gcp_pricing.mapping import shape_hourly_rate as _shape_hourly_rate
from gcp_pricing.shapes import MachineShape

# The regions each family must price or the run fails: where AnVIL runs that
# kind of work. Other US regions are priced when they resolve, never required.
REQUIRED_REGIONS: dict[str, tuple[str, ...]] = {
    "t2d": ("us-central1", "us-east4"),
    "n2": ("us-central1", "us-east4"),
    "g2": ("us-central1", "us-east1", "us-east4"),
}
MACHINE_FAMILIES = tuple(REQUIRED_REGIONS)
SOURCE_URLS = (
    "https://docs.cloud.google.com/billing/v1/how-tos/catalog-api",
    "https://docs.cloud.google.com/compute/docs/general-purpose-machines",
    "https://docs.cloud.google.com/compute/docs/accelerator-optimized-machines",
)
COVERAGE_NOTE = (
    "T2D standard, N2 standard/highmem/highcpu and G2 standard on-demand "
    "compute prices only, for the US regions listed above. A G2 price "
    "includes the NVIDIA L4 GPUs that come with the machine. Excludes Spot, "
    "custom machines, other families and providers, commitments, premium OS "
    "licenses, GPUs attached to other machines, disk and network. Not a "
    "complete GCP price list."
)


class PublishError(ValueError):
    """The run has a problem that must block publication."""


def _combined_effective_time(rates: ComponentRates) -> str | None:
    """When the derived machine rate took effect: its latest component's time.

    A predefined shape's hourly rate is assembled from a vCPU rate, a memory
    rate and, for a GPU machine, a GPU rate, so the combined rate was not in
    effect until all of its components were. Publishing the retrieval time instead would date every rate to the
    moment the catalog was built, and the application only applies a rate whose
    effective time precedes the work being priced — so a freshly published
    catalog could price nothing that had already finished.

    The provider's own spelling is kept. When any component does not say,
    the rate carries no effective time rather than a guessed one, which the
    application reads as always-applicable.
    """
    times = [point.effective_time for point in rates.points()]
    if not all(times):
        return None
    return max(times, key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")))


def _gpu_provenance(shape: MachineShape, rates: ComponentRates) -> dict:
    if shape.gpu is None or rates.gpu is None:
        return {}
    return {
        "gpu_sku_id": rates.gpu.sku_id,
        "gpu_sku_description": rates.gpu.description,
        "gpu_rate_per_gpu_hour": str(rates.gpu.rate_per_unit),
        "gpu_usage_unit": rates.gpu.usage_unit,
        "gpu_effective_time": rates.gpu.effective_time,
        "gpu_count": shape.gpu.count,
        "gpu_model": shape.gpu.model,
    }


def build_rates(
    shapes: tuple[MachineShape, ...],
    region_rates: dict[tuple[str, str], ComponentRates],
    *,
    observed_at: datetime,
    mapping_version: str,
) -> list[dict]:
    observed_iso = observed_at.isoformat().replace("+00:00", "Z")
    rates: list[dict] = []
    for (family, region), component_rates in sorted(region_rates.items()):
        for shape in shapes:
            if shape.family != family:
                continue
            rate = _shape_hourly_rate(shape, component_rates)
            rates.append(
                {
                    "provider": "gcp",
                    "region": region,
                    "purchase_model": "on_demand",
                    "machine_type": shape.machine_type,
                    "hourly_rate": str(rate),
                    "effective_from": _combined_effective_time(component_rates),
                    "provenance": {
                        "cpu_sku_id": component_rates.cpu.sku_id,
                        "cpu_sku_description": component_rates.cpu.description,
                        "cpu_rate_per_vcpu_hour": str(component_rates.cpu.rate_per_unit),
                        "cpu_usage_unit": component_rates.cpu.usage_unit,
                        "cpu_effective_time": component_rates.cpu.effective_time,
                        "ram_sku_id": component_rates.ram.sku_id,
                        "ram_sku_description": component_rates.ram.description,
                        "ram_rate_per_gib_hour": str(component_rates.ram.rate_per_unit),
                        "ram_usage_unit": component_rates.ram.usage_unit,
                        "ram_effective_time": component_rates.ram.effective_time,
                        "vcpu_count": shape.vcpu,
                        "memory_gib": str(shape.memory_gib),
                        **_gpu_provenance(shape, component_rates),
                        "mapping_version": mapping_version,
                        "retrieved_at": observed_iso,
                    },
                }
            )
    return rates


def check_required_regions(
    region_rates: dict[tuple[str, str], ComponentRates],
    *,
    required: dict[str, tuple[str, ...]] = REQUIRED_REGIONS,
) -> None:
    missing = [
        f"{family}/{region}"
        for family, regions in required.items()
        for region in regions
        if (family, region) not in region_rates
    ]
    if missing:
        raise PublishError("required regions are not priced: " + ", ".join(missing))


def _family_region_pairs(rates: list[dict]) -> set[tuple[str, str]]:
    return {(rate["machine_type"].split("-", 1)[0], rate["region"]) for rate in rates}


def check_no_regression(
    previous_rates: list[dict], new_rates: list[dict], *, acknowledged: tuple[tuple[str, str], ...] = ()
) -> None:
    """Refuse to silently drop a previously priced family/region.

    Coverage is compared by (family, region), not exact machine type: a
    family losing an entire region is the regression this guards against.
    Losing one shape while the family/region pair still prices other shapes
    is visible directly in the rates list, not flagged as a regression here.
    A previous region outside `PRICED_REGION_PREFIX` is out of scope, not lost.
    """
    in_scope = [rate for rate in previous_rates if rate["region"].startswith(PRICED_REGION_PREFIX)]
    lost = _family_region_pairs(in_scope) - _family_region_pairs(new_rates) - set(acknowledged)
    if lost:
        raise PublishError(
            "coverage regression: previously priced but now missing: "
            + ", ".join(f"{family}/{region}" for family, region in sorted(lost))
        )


def catalog_id_for(observed_at: datetime) -> str:
    return f"gcp-compute-{observed_at.strftime('%Y%m%dT%H%M%SZ')}"


def build_catalog_document(
    rates: list[dict],
    *,
    observed_at: datetime,
    key_id: str,
    private_key: Ed25519PrivateKey,
    catalog_id: str | None = None,
) -> dict:
    if not rates:
        raise PublishError("refusing to publish a catalog with no priced rates")
    document = {
        "schema_version": 2,
        "catalog_id": catalog_id or catalog_id_for(observed_at),
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "currency": "USD",
        "kind": "official_catalog_api",
        # True when every rate carries the provider's own effective time, so the
        # catalog can price work that finished before it was published.
        "historical_effective_time_available": all(
            rate.get("effective_from") for rate in rates
        ),
        "source_urls": list(SOURCE_URLS),
        "coverage": {
            "regions": sorted({rate["region"] for rate in rates}),
            "machine_families": list(MACHINE_FAMILIES),
            "purchase_models": ["on_demand"],
            "complete": False,
            "note": COVERAGE_NOTE,
        },
        "rates": rates,
    }
    content = canonical_content(document)
    signature = private_key.sign(content)
    document["signature"] = {
        "algorithm": "ed25519",
        "key_id": key_id,
        "signature": base64.b64encode(signature).decode(),
        "content_digest": hashlib.sha256(content).hexdigest(),
    }
    return document


def write_local(document: dict, output_dir: Path) -> tuple[Path, Path]:
    """Write the write-once version file and the refreshed `latest.json`.

    A rerun with the same `catalog_id` (the same publish minute) refuses to
    overwrite a version file that already exists, since published versions
    are immutable; `latest.json` is the only file this ever replaces.
    """
    versions_dir = output_dir / "gcp" / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    version_path = versions_dir / f"{document['catalog_id']}.json"
    latest_path = output_dir / "gcp" / "latest.json"
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if version_path.exists():
        raise PublishError(f"{version_path} already exists; published catalog versions are write-once")
    version_path.write_text(payload)
    latest_path.write_text(payload)
    return version_path, latest_path


def load_previous_rates(source: str | None, *, timeout: int = 30) -> list[dict]:
    """Best-effort read of a previously published catalog's rates, for the
    regression check only. A missing prior artifact (first run, or a typo'd
    path the maintainer will notice from the warning) is not fatal by itself;
    an unreadable *existing* remote artifact is, since a silent empty read
    would defeat the entire regression check.
    """
    if not source:
        return []
    path = Path(source)
    if path.exists():
        return json.loads(path.read_text()).get("rates", [])
    if not source.startswith(("http://", "https://")):
        return []
    request = urllib.request.Request(source, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read()).get("rates", [])
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return []
        raise PublishError(f"could not read previous catalog at {source}: {error}") from error
    except urllib.error.URLError as error:
        raise PublishError(f"could not read previous catalog at {source}: {error}") from error
