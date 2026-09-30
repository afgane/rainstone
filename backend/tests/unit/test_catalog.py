import json
from pathlib import Path

import pytest
from rainstone.catalog import CatalogError, parse_trusted_keys, published_url, validate
from rainstone.config import Settings
from rainstone.models import CatalogVersion

PILOT = Path("fixtures/price-catalog-pilot.json")
BUNDLED = Path("catalog/gcp-2026-09-30.json")


def artifact(**overrides) -> bytes:
    payload = {
        "schema_version": 2,
        "catalog_id": "test-catalog-1",
        "observed_at": "2026-09-19T13:32:03Z",
        "currency": "USD",
        "source_urls": ["https://example.invalid/pricing"],
        "rates": [
            {
                "provider": "gcp",
                "region": "us-central1",
                "purchase_model": "on_demand",
                "machine_type": "n2-standard-2",
                "hourly_rate": "0.097118",
            }
        ],
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


def test_an_unsigned_hand_captured_catalog_validates() -> None:
    catalog = validate(PILOT.read_bytes(), source=str(PILOT))
    assert catalog.rates
    assert catalog.currency == "USD"
    assert catalog.provenance["historical_effective_time_available"] is False


def test_the_bundled_catalog_is_the_signed_published_one() -> None:
    catalog = validate(
        BUNDLED.read_bytes(),
        source=str(BUNDLED),
        require_signature=True,
        trusted_keys=parse_trusted_keys(Settings().catalog_trusted_keys),
    )
    assert catalog.signature_verified is True
    assert catalog.provenance["historical_effective_time_available"] is True
    assert catalog.coverage["machine_families"] == ["t2d", "n2", "g2"]
    assert all(rate["region"].startswith("us-") for rate in catalog.rates)
    assert all(rate["effective_from"] for rate in catalog.rates)
    assert {"g2-standard-4", "n2-standard-2", "t2d-standard-4"} <= {rate["machine_type"] for rate in catalog.rates}


def test_duplicate_resolver_keys_are_rejected() -> None:
    rates = [
        {
            "provider": "gcp",
            "region": "us-central1",
            "purchase_model": "on_demand",
            "machine_type": "n2-standard-2",
            "hourly_rate": "0.09",
        }
    ] * 2
    with pytest.raises(CatalogError, match="duplicate"):
        validate(artifact(rates=rates), source="test")


def test_unsupported_currency_is_rejected_rather_than_relabelled() -> None:
    with pytest.raises(CatalogError, match="currency"):
        validate(artifact(currency="EUR"), source="test")


def test_newer_schema_versions_are_refused() -> None:
    with pytest.raises(CatalogError, match="newer"):
        validate(artifact(schema_version=99), source="test")


def test_a_declared_digest_that_disagrees_with_the_content_is_refused() -> None:
    with pytest.raises(CatalogError, match="digest does not match"):
        validate(
            artifact(signature={"key_id": "release-1", "content_digest": "0" * 64}),
            source="test",
            trusted_keys={"release-1": b"x" * 32},
        )


def test_required_signature_is_enforced_when_configured() -> None:
    with pytest.raises(CatalogError, match="signature is required"):
        validate(
            artifact(), source="test", require_signature=True, trusted_keys={"k": b"x" * 32}
        )


def test_non_positive_rates_are_refused() -> None:
    rates = [
        {
            "provider": "gcp",
            "region": "us-central1",
            "purchase_model": "on_demand",
            "machine_type": "n2-standard-2",
            "hourly_rate": "0",
        }
    ]
    with pytest.raises(CatalogError, match="not positive"):
        validate(artifact(rates=rates), source="test")


def test_a_fetched_catalog_links_its_own_published_version() -> None:
    fetched = CatalogVersion(
        catalog_id="gcp-t2d-n2-20260923T004653Z",
        source="https://example.github.io/rainstone/gcp/latest.json",
    )
    assert published_url(fetched) == (
        "https://example.github.io/rainstone/gcp/versions/gcp-t2d-n2-20260923T004653Z.json"
    )
    bundled = CatalogVersion(catalog_id="bundled", source="catalog/gcp-2026-09-30.json")
    assert published_url(bundled) is None
