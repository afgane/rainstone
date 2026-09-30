"""End-to-end publisher run: fetch (fixtures) -> normalize -> validate -> sign -> write."""

import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import publish_gcp_catalog as cli
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from gcp_pricing import catalog_api
from gcp_pricing.output import PublishError
from rainstone.catalog import validate

FIXTURES = Path("scripts/fixtures/gcp_billing")
SHAPES_PATH = Path("catalog/gcp-machine-shapes.json")
NOW = datetime(2026, 9, 22, tzinfo=UTC)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def fixture_opener(request, _timeout):
    url = request.full_url
    if "/services?" in url:
        return FakeResponse(json.loads((FIXTURES / "services.json").read_text()))
    if "pageToken=page-2-token" in url:
        return FakeResponse(json.loads((FIXTURES / "skus_page2.json").read_text()))
    return FakeResponse(json.loads((FIXTURES / "skus_page1.json").read_text()))


@pytest.fixture(autouse=True)
def fake_http(monkeypatch) -> None:
    # `_open` is a default-argument value bound at function-definition time, so
    # patching the module attribute directly would not reach already-bound
    # defaults; patching the urlopen call it wraps does.
    monkeypatch.setattr(catalog_api.urllib.request, "urlopen", lambda request, timeout=None: fixture_opener(request, timeout))


@pytest.fixture()
def key_pair() -> tuple[Ed25519PrivateKey, bytes]:
    key = Ed25519PrivateKey.generate()
    return key, key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def test_a_full_run_produces_a_catalog_rainstone_can_verify_and_import(tmp_path, key_pair) -> None:
    key, public = key_pair
    document = cli.run(
        api_key="fake-key",
        key_id="release-2026",
        private_key=key,
        shapes_path=SHAPES_PATH,
        output_dir=tmp_path,
        previous_catalog=None,
        now=NOW,
    )
    validated = validate(
        json.dumps(document).encode(),
        source="local",
        require_signature=True,
        trusted_keys={"release-2026": public},
    )
    assert validated.signature_verified is True
    assert len(validated.rates) > 0
    regions = {rate["region"] for rate in validated.rates}
    assert {"us-central1", "us-east1", "us-east4"} <= regions
    assert all(region.startswith("us-") for region in regions)
    machine_types = {rate["machine_type"] for rate in validated.rates}
    assert "n2-highcpu-128" not in machine_types

    latest = json.loads((tmp_path / "gcp" / "latest.json").read_text())
    assert latest["catalog_id"] == document["catalog_id"]
    version_files = list((tmp_path / "gcp" / "versions").glob("*.json"))
    assert len(version_files) == 1


def test_dry_run_signs_but_writes_nothing(tmp_path, key_pair) -> None:
    key, _public = key_pair
    cli.run(
        api_key="fake-key",
        key_id="release-2026",
        private_key=key,
        shapes_path=SHAPES_PATH,
        output_dir=None,
        previous_catalog=None,
        now=NOW,
    )
    assert not (tmp_path / "gcp").exists()


def test_a_representative_t2d_and_n2_rate_round_trips_exactly(key_pair) -> None:
    key, _public = key_pair
    document = cli.run(
        api_key="fake-key",
        key_id="release-2026",
        private_key=key,
        shapes_path=SHAPES_PATH,
        output_dir=None,
        previous_catalog=None,
        now=NOW,
    )
    by_key = {(rate["machine_type"], rate["region"]): rate for rate in document["rates"]}
    # These reproduce backend/rainstone/catalog.py's fixture bundled catalog
    # exactly, from independently-specified fixture CPU/RAM component rates.
    assert by_key[("n2-standard-2", "us-central1")]["hourly_rate"] == "0.097118"
    assert by_key[("n2-highmem-4", "us-central1")]["hourly_rate"] == "0.262028"
    assert by_key[("n2-highcpu-2", "us-central1")]["hourly_rate"] == "0.071696"


def test_a_g2_rate_includes_its_l4_gpus_and_skips_the_workstation_sku(key_pair) -> None:
    key, _public = key_pair
    document = cli.run(
        api_key="fake-key",
        key_id="release-2026",
        private_key=key,
        shapes_path=SHAPES_PATH,
        output_dir=None,
        previous_catalog=None,
        now=NOW,
    )
    by_key = {(rate["machine_type"], rate["region"]): rate for rate in document["rates"]}
    # From the fixture component rates, which are illustrative rather than
    # Google's: 4 * 0.024988 + 16 * 0.002928 + 1 * 0.56004.
    assert by_key[("g2-standard-4", "us-east1")]["hourly_rate"] == "0.706840"
    # 48 * 0.024988 + 192 * 0.002928 + 4 * 0.56004
    assert by_key[("g2-standard-48", "us-east1")]["hourly_rate"] == "4.001760"
    assert by_key[("g2-standard-4", "us-east1")]["provenance"]["gpu_sku_id"] == "L4G1-0000-0003"


def test_prices_unchanged_through_their_history_are_dated_to_its_start(key_pair) -> None:
    """The fixtures list the same prices for every month asked about, so each
    rate is in effect for the whole default twelve months: from 1 October 2025
    in Pacific time, not from the day the catalog was read.
    """
    key, _public = key_pair
    document = cli.run(
        api_key="fake-key",
        key_id="release-2026",
        private_key=key,
        shapes_path=SHAPES_PATH,
        output_dir=None,
        previous_catalog=None,
        now=NOW,
    )
    assert {rate["effective_from"] for rate in document["rates"]} == {"2025-10-01T07:00:00Z"}
    assert document["historical_effective_time_available"] is True


def test_a_coverage_regression_blocks_the_run(tmp_path, key_pair) -> None:
    key, _public = key_pair
    previous = tmp_path / "previous-latest.json"
    previous.write_text(
        json.dumps({"rates": [{"machine_type": "n2-standard-2", "region": "us-west2"}]})
    )
    with pytest.raises(PublishError, match="us-west2"):
        cli.run(
            api_key="fake-key",
            key_id="release-2026",
            private_key=key,
            shapes_path=SHAPES_PATH,
            output_dir=None,
            previous_catalog=str(previous),
            now=NOW,
        )


def test_main_requires_the_configured_env_vars(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GCP_CATALOG_API_KEY", raising=False)
    with pytest.raises(cli.CliError, match="GCP_CATALOG_API_KEY"):
        cli.main(["--key-id", "release-2026"])


def test_main_end_to_end_via_argv(tmp_path, monkeypatch, key_pair, capsys) -> None:
    key, public = key_pair
    seed = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    monkeypatch.setenv("GCP_CATALOG_API_KEY", "fake-key")
    monkeypatch.setenv("GCP_CATALOG_SIGNING_KEY", base64.b64encode(seed).decode())
    exit_code = cli.main(
        [
            "--key-id",
            "release-2026",
            "--shapes-path",
            str(SHAPES_PATH),
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    latest = json.loads((tmp_path / "gcp" / "latest.json").read_text())
    validated = validate(
        json.dumps(latest).encode(),
        source="local",
        require_signature=True,
        trusted_keys={"release-2026": public},
    )
    assert validated.signature_verified is True
    output = capsys.readouterr().out
    assert "catalog_id=" in output
