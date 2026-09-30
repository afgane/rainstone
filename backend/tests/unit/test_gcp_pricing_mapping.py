"""SKU selection and normalization: family/component matching, unit conversion,
ambiguity handling, and rejection of lookalike or malformed SKUs.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from gcp_pricing.mapping import (
    ComponentRates,
    MappingError,
    PricePoint,
    build_region_rates,
    classify_sku,
    price_point,
    shape_hourly_rate,
)
from gcp_pricing.shapes import MachineShape, ShapeGpu

NOW = datetime(2026, 9, 22, tzinfo=UTC)


def sku(
    sku_id: str,
    description: str,
    *,
    resource_family: str = "Compute",
    usage_type: str = "OnDemand",
    regions: list[str] | None = None,
    units: str = "0",
    nanos: int = 31_611_000,
    usage_unit: str = "h",
    currency: str = "USD",
    effective: str | None = "2026-01-01T00:00:00Z",
    start_usage: float = 0,
    tier_count: int = 1,
) -> dict:
    tier = {
        "startUsageAmount": start_usage,
        "unitPrice": {"currencyCode": currency, "units": units, "nanos": nanos},
    }
    return {
        "skuId": sku_id,
        "description": description,
        "category": {"resourceFamily": resource_family, "usageType": usage_type},
        "serviceRegions": regions if regions is not None else ["us-central1"],
        "pricingInfo": [
            {
                "effectiveTime": effective,
                "pricingExpression": {"usageUnit": usage_unit, "tieredRates": [tier] * tier_count},
                "currencyConversionRate": 1,
            }
        ],
    }


def test_n2_core_and_ram_are_classified() -> None:
    assert classify_sku(sku("A", "N2 Instance Core running in Americas")) == ("n2", "cpu")
    assert classify_sku(sku("B", "N2 Instance Ram running in Americas")) == ("n2", "ram")


def test_t2d_core_and_ram_are_classified() -> None:
    assert classify_sku(sku("A", "T2D AMD Instance Core running in Americas")) == ("t2d", "cpu")
    assert classify_sku(sku("B", "T2D AMD Instance Ram running in Americas")) == ("t2d", "ram")


def test_g2_core_ram_and_its_l4_gpu_are_classified() -> None:
    assert classify_sku(sku("A", "G2 Instance Core running in Americas")) == ("g2", "cpu")
    assert classify_sku(sku("B", "G2 Instance Ram running in Americas")) == ("g2", "ram")
    assert classify_sku(sku("C", "Nvidia L4 GPU running in Americas")) == ("g2", "gpu")
    assert classify_sku(sku("D", "NVIDIA L4 GPU running in Virginia")) == ("g2", "gpu")


@pytest.mark.parametrize(
    "description",
    [
        "Nvidia L4 GPU Virtual Workstation running in Americas",
        "Spot Preemptible Nvidia L4 GPU running in Americas",
        "Nvidia Tesla T4 GPU running in Americas",
        "Commitment v1: Nvidia L4 GPU running in Americas",
        "G2 Custom Instance Core running in Americas",
    ],
)
def test_gpu_lookalikes_are_never_classified_as_g2(description: str) -> None:
    assert classify_sku(sku("X", description)) is None


@pytest.mark.parametrize(
    "description",
    [
        "N2D AMD Instance Core running in Americas",
        "N2 Custom Instance Core running in Americas",
        "T2A Instance Core running in Americas",
        "Spot Preemptible N2 Instance Core running in Americas",
        "Commitment v1: N2 Predefined Instance Core",
        "Sole Tenancy N2 Instance Core running in Americas",
        "Premium N2 Instance Core running in Americas",
    ],
)
def test_lookalikes_are_never_classified_as_n2_or_t2d(description: str) -> None:
    assert classify_sku(sku("X", description)) is None


def test_preemptible_usage_type_is_excluded_even_with_a_matching_description() -> None:
    candidate = sku("X", "N2 Instance Core running in Americas", usage_type="Preemptible")
    assert classify_sku(candidate) is None


def test_non_compute_resource_family_is_excluded() -> None:
    candidate = sku("X", "N2 Instance Core running in Americas", resource_family="Storage")
    assert classify_sku(candidate) is None


def test_cpu_unit_conversion_from_units_and_nanos() -> None:
    point = price_point(sku("A", "N2 Instance Core running in Americas", nanos=31_611_000), "cpu", now=NOW)
    assert point.rate_per_unit == Decimal("0.031611")


def test_ram_unit_conversion_from_units_and_nanos() -> None:
    point = price_point(
        sku("B", "N2 Instance Ram running in Americas", nanos=4_237_000, usage_unit="GiBy.h"),
        "ram",
        now=NOW,
    )
    assert point.rate_per_unit == Decimal("0.004237")


def test_a_mismatched_usage_unit_is_rejected() -> None:
    # A RAM SKU that (wrongly) carries the CPU usage unit must fail loudly
    # rather than be normalized as if it were per-vCPU.
    candidate = sku("B", "N2 Instance Ram running in Americas", usage_unit="h")
    with pytest.raises(MappingError, match="usage unit"):
        price_point(candidate, "ram", now=NOW)


def test_a_non_usd_price_is_rejected() -> None:
    with pytest.raises(MappingError, match="USD"):
        price_point(sku("A", "N2 Instance Core running in Americas", currency="EUR"), "cpu", now=NOW)


def test_a_tiered_price_is_rejected_rather_than_guessed() -> None:
    with pytest.raises(MappingError, match="tier"):
        price_point(sku("A", "N2 Instance Core running in Americas", tier_count=2), "cpu", now=NOW)


def test_a_tier_that_does_not_start_at_zero_is_rejected() -> None:
    with pytest.raises(MappingError, match="zero usage"):
        price_point(sku("A", "N2 Instance Core running in Americas", start_usage=100), "cpu", now=NOW)


def test_a_future_dated_price_is_never_selected() -> None:
    candidate = sku("A", "N2 Instance Core running in Americas", effective="2099-01-01T00:00:00Z")
    with pytest.raises(MappingError, match="no pricing effective"):
        price_point(candidate, "cpu", now=NOW)


def test_the_latest_applicable_price_wins_over_an_older_one() -> None:
    candidate = sku("A", "N2 Instance Core running in Americas")
    candidate["pricingInfo"] = [
        {
            "effectiveTime": "2020-01-01T00:00:00Z",
            "pricingExpression": {
                "usageUnit": "h",
                "tieredRates": [
                    {"startUsageAmount": 0, "unitPrice": {"currencyCode": "USD", "units": "0", "nanos": 1}}
                ],
            },
            "currencyConversionRate": 1,
        },
        {
            "effectiveTime": "2026-01-01T00:00:00Z",
            "pricingExpression": {
                "usageUnit": "h",
                "tieredRates": [
                    {
                        "startUsageAmount": 0,
                        "unitPrice": {"currencyCode": "USD", "units": "0", "nanos": 31_611_000},
                    }
                ],
            },
            "currencyConversionRate": 1,
        },
    ]
    point = price_point(candidate, "cpu", now=NOW)
    assert point.rate_per_unit == Decimal("0.031611")
    assert point.effective_time == "2026-01-01T00:00:00Z"


def test_region_rates_pair_cpu_and_ram_by_family_and_region() -> None:
    skus = [
        sku("cpu-n2", "N2 Instance Core running in Americas", regions=["us-central1", "us-east4"]),
        sku(
            "ram-n2",
            "N2 Instance Ram running in Americas",
            regions=["us-central1", "us-east4"],
            nanos=4_237_000,
            usage_unit="GiBy.h",
        ),
    ]
    region_rates, problems = build_region_rates(skus, now=NOW)
    assert problems == []
    assert set(region_rates) == {("n2", "us-central1"), ("n2", "us-east4")}
    assert region_rates[("n2", "us-central1")].cpu.sku_id == "cpu-n2"
    assert region_rates[("n2", "us-central1")].ram.sku_id == "ram-n2"


def test_a_missing_ram_pair_blocks_that_family_region_but_not_others() -> None:
    skus = [
        sku("cpu-n2", "N2 Instance Core running in Americas", regions=["us-central1"]),
        # No matching RAM SKU for N2 at all.
        sku("cpu-t2d", "T2D AMD Instance Core running in Americas", regions=["us-central1"]),
        sku(
            "ram-t2d",
            "T2D AMD Instance Ram running in Americas",
            regions=["us-central1"],
            nanos=3_910_000,
            usage_unit="GiBy.h",
        ),
    ]
    region_rates, problems = build_region_rates(skus, now=NOW)
    assert ("n2", "us-central1") not in region_rates
    assert ("t2d", "us-central1") in region_rates
    assert any("n2 in us-central1 is missing its ram rate" in problem for problem in problems)


def test_duplicate_candidate_skus_for_the_same_family_region_are_ambiguous() -> None:
    skus = [
        sku("cpu-n2-a", "N2 Instance Core running in Americas", regions=["us-central1"]),
        sku("cpu-n2-b", "N2 Instance Core running in Americas", regions=["us-central1"]),
    ]
    region_rates, problems = build_region_rates(skus, now=NOW)
    assert region_rates == {}
    assert any("candidate cpu SKUs" in problem for problem in problems)


def test_no_cross_region_fallback_when_a_region_has_no_candidate_sku() -> None:
    skus = [
        sku("cpu-n2", "N2 Instance Core running in Americas", regions=["us-central1"]),
        sku(
            "ram-n2",
            "N2 Instance Ram running in Americas",
            regions=["us-central1"],
            nanos=4_237_000,
            usage_unit="GiBy.h",
        ),
    ]
    region_rates, _problems = build_region_rates(skus, now=NOW)
    assert "us-east4" not in {region for _family, region in region_rates}


def _g2_skus(regions: list[str], *, with_gpu: bool = True) -> list[dict]:
    skus = [
        sku("cpu-g2", "G2 Instance Core running in Americas", regions=regions, nanos=24_988_000),
        sku("ram-g2", "G2 Instance Ram running in Americas", regions=regions, nanos=2_928_000, usage_unit="GiBy.h"),
    ]
    if with_gpu:
        skus.append(sku("gpu-l4", "Nvidia L4 GPU running in Americas", regions=regions, nanos=560_040_000))
    return skus


def test_g2_rates_carry_its_gpu() -> None:
    region_rates, problems = build_region_rates(_g2_skus(["us-central1"]), now=NOW)
    assert problems == []
    rates = region_rates[("g2", "us-central1")]
    assert rates.gpu is not None
    assert rates.gpu.sku_id == "gpu-l4"
    assert rates.gpu.rate_per_unit == Decimal("0.56004")


def test_g2_without_a_gpu_rate_is_not_priced_at_all() -> None:
    """A G2 rate from vCPU and memory alone would understate what it cost."""
    region_rates, problems = build_region_rates(_g2_skus(["us-central1"], with_gpu=False), now=NOW)
    assert ("g2", "us-central1") not in region_rates
    assert any("g2 in us-central1 is missing its gpu rate" in problem for problem in problems)


def test_a_gpu_with_the_wrong_usage_unit_is_rejected() -> None:
    candidate = sku("gpu-l4", "Nvidia L4 GPU running in Americas", usage_unit="GiBy.h")
    with pytest.raises(MappingError, match="usage unit"):
        price_point(candidate, "gpu", now=NOW)


def test_regions_outside_the_us_are_not_priced_or_reported() -> None:
    skus = [
        sku("cpu-n2", "N2 Instance Core running in Americas", regions=["us-east1", "southamerica-east1"]),
        sku(
            "ram-n2",
            "N2 Instance Ram running in Americas",
            regions=["us-east1", "northamerica-northeast1"],
            nanos=4_237_000,
            usage_unit="GiBy.h",
        ),
    ]
    region_rates, problems = build_region_rates(skus, now=NOW)
    assert set(region_rates) == {("n2", "us-east1")}
    assert problems == []


def _point(rate: str, unit: str) -> PricePoint:
    return PricePoint("sku", "description", Decimal(rate), unit, None)


def test_a_gpu_machine_adds_each_of_its_gpus_to_the_rate() -> None:
    shape = MachineShape(
        "g2-standard-24", "g2", "standard", 24, Decimal("96"), "https://example.invalid", ShapeGpu(2, "NVIDIA L4")
    )
    rates = ComponentRates(_point("0.024988", "h"), _point("0.002928", "GiBy.h"), _point("0.56004", "h"))
    # 24 * 0.024988 + 96 * 0.002928 + 2 * 0.56004
    assert shape_hourly_rate(shape, rates) == Decimal("2.00088")


def test_a_gpu_machine_without_a_gpu_rate_fails_rather_than_underprices() -> None:
    shape = MachineShape(
        "g2-standard-4", "g2", "standard", 4, Decimal("16"), "https://example.invalid", ShapeGpu(1, "NVIDIA L4")
    )
    rates = ComponentRates(_point("0.024988", "h"), _point("0.002928", "GiBy.h"))
    with pytest.raises(MappingError, match="no GPU rate"):
        shape_hourly_rate(shape, rates)
