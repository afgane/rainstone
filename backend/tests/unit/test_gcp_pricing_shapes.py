"""The machine shape registry the publisher prices: catalog/gcp-machine-shapes.json."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from gcp_pricing.shapes import ShapeRegistryError, load_shapes

REGISTRY = Path("catalog/gcp-machine-shapes.json")


def test_the_registry_has_exactly_the_45_verified_shapes() -> None:
    shapes = load_shapes(REGISTRY)
    assert len(shapes) == 45
    assert len({shape.machine_type for shape in shapes}) == 45


def test_highcpu_memory_is_the_official_1_gib_per_vcpu_not_the_runner_heuristic() -> None:
    """The GCP Batch runner's 0.9 GB/vCPU is a selection heuristic, not the
    machine's billable RAM; the catalog must price the real 1 GiB/vCPU.
    """
    shapes = {shape.machine_type: shape for shape in load_shapes(REGISTRY)}
    assert shapes["n2-highcpu-8"].memory_gib == Decimal("8")


def test_n2_highcpu_128_is_absent_from_the_registry() -> None:
    """The runner's common-size list can construct n2-highcpu-128, which is not
    in the official N2 highcpu table; the publisher must not invent a rate for it.
    """
    machine_types = {shape.machine_type for shape in load_shapes(REGISTRY)}
    assert "n2-highcpu-128" not in machine_types
    assert "n2-highcpu-96" in machine_types


def test_family_and_variant_vcpu_sizes_match_the_published_specification() -> None:
    shapes = load_shapes(REGISTRY)
    by_variant: dict[tuple[str, str], list[int]] = {}
    for shape in shapes:
        by_variant.setdefault((shape.family, shape.variant), []).append(shape.vcpu)
    common = [1, 2, 4, 8, 16, 32, 48, 60]
    n2_sizes = [2, 4, 8, 16, 32, 48, 64, 80, 96, 128]
    assert sorted(by_variant[("t2d", "standard")]) == common
    assert sorted(by_variant[("n2", "standard")]) == n2_sizes
    assert sorted(by_variant[("n2", "highmem")]) == n2_sizes
    assert sorted(by_variant[("n2", "highcpu")]) == [v for v in n2_sizes if v != 128]
    assert sorted(by_variant[("g2", "standard")]) == [4, 8, 12, 16, 24, 32, 48, 96]


def test_memory_per_vcpu_ratio_holds_for_every_shape() -> None:
    ratios = {"standard": Decimal("4"), "highmem": Decimal("8"), "highcpu": Decimal("1")}
    for shape in load_shapes(REGISTRY):
        assert shape.memory_gib == shape.vcpu * ratios[shape.variant]


def test_every_g2_shape_comes_with_its_published_l4_gpu_count() -> None:
    gpus = {
        shape.machine_type: shape.gpu.count
        for shape in load_shapes(REGISTRY)
        if shape.family == "g2"
    }
    assert gpus == {
        "g2-standard-4": 1,
        "g2-standard-8": 1,
        "g2-standard-12": 1,
        "g2-standard-16": 1,
        "g2-standard-24": 2,
        "g2-standard-32": 1,
        "g2-standard-48": 4,
        "g2-standard-96": 8,
    }
    assert {shape.gpu.model for shape in load_shapes(REGISTRY) if shape.gpu} == {"NVIDIA L4"}


def test_shapes_without_gpus_carry_none() -> None:
    assert all(shape.gpu is None for shape in load_shapes(REGISTRY) if shape.family != "g2")


def _registry_with(tmp_path, **extra) -> Path:
    path = tmp_path / "shapes.json"
    entry = {
        "machine_type": "g2-standard-4",
        "family": "g2",
        "variant": "standard",
        "vcpu": 4,
        "memory_gib": "16",
        "source_ref": "https://example.invalid",
        **extra,
    }
    path.write_text(json.dumps({"shapes": [entry]}))
    return path


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"gpu_count": 1}, "both gpu_count and gpu_model"),
        ({"gpu_model": "NVIDIA L4"}, "both gpu_count and gpu_model"),
        ({"gpu_count": 0, "gpu_model": "NVIDIA L4"}, "positive integer"),
        ({"gpu_count": "1", "gpu_model": "NVIDIA L4"}, "positive integer"),
        ({"gpu_count": 1, "gpu_model": " "}, "must be a name"),
    ],
)
def test_an_incomplete_or_malformed_gpu_is_rejected(tmp_path, extra, message) -> None:
    with pytest.raises(ShapeRegistryError, match=message):
        load_shapes(_registry_with(tmp_path, **extra))


def test_a_duplicate_machine_type_is_rejected(tmp_path) -> None:
    bad = tmp_path / "shapes.json"
    bad.write_text(
        json.dumps(
            {
                "shapes": [
                    {
                        "machine_type": "n2-standard-2",
                        "family": "n2",
                        "variant": "standard",
                        "vcpu": 2,
                        "memory_gib": "8",
                        "source_ref": "https://example.invalid",
                    }
                ]
                * 2
            }
        )
    )
    with pytest.raises(ShapeRegistryError, match="duplicate"):
        load_shapes(bad)


def test_a_missing_registry_file_is_rejected(tmp_path) -> None:
    with pytest.raises(ShapeRegistryError, match="not found"):
        load_shapes(tmp_path / "missing.json")
