"""The committed demonstration runs are exactly what their generator produces."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_run_demo", ROOT / "scripts" / "generate_run_demo.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_fixture_matches_the_generator() -> None:
    generator = load_generator()
    committed = (ROOT / "fixtures" / "runs-demo.json").read_text()
    assert generator.render(generator.build()) == committed, (
        "fixtures/runs-demo.json is stale: run scripts/generate_run_demo.py"
    )


def test_the_demonstration_covers_what_the_run_pages_need() -> None:
    data = json.loads((ROOT / "fixtures" / "runs-demo.json").read_text())
    roots = [run for run in data["invocations"] if run["parent_source_id"] is None]
    assert 140 <= len(roots) <= 160
    assert len({run["workflow_family_id"] for run in roots}) == 8
    states = {job["state"] for job in data["jobs"]}
    assert {"ok", "error", "running"} <= states
    # Nothing states an amount: costs come from ingestion and the price catalog.
    assert "amount" not in json.dumps(data["jobs"])
