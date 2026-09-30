import json
from decimal import Decimal

from rainstone import machine_shapes
from rainstone.config import get_settings
from rainstone.machine_shapes import machine_capacity


def test_a_priced_shape_reports_its_published_size() -> None:
    capacity = machine_capacity("gcp", "n2-highmem-8")
    assert capacity == {"vcpu": "8", "memory_mib": "65536", "source": "published_machine_shape"}


def test_memory_follows_the_shape_variant() -> None:
    def memory_gib(machine_type: str) -> Decimal:
        return Decimal(machine_capacity("gcp", machine_type)["memory_mib"]) / 1024

    assert memory_gib("n2-standard-4") == 16
    assert memory_gib("n2-highcpu-4") == 4
    assert memory_gib("t2d-standard-2") == 8


def test_a_shape_the_registry_does_not_list_has_no_capacity() -> None:
    assert machine_capacity("gcp", "e2-standard-4") is None
    assert machine_capacity("gcp", "n2-custom-4-8192") is None
    assert machine_capacity("gcp", None) is None


def test_another_provider_is_not_looked_up_by_a_gcp_name() -> None:
    assert machine_capacity("kubernetes", "n2-standard-8") is None


def test_a_missing_registry_removes_sizes_without_failing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(get_settings(), "machine_shapes_path", tmp_path / "absent.json")
    assert machine_capacity("gcp", "n2-standard-8") is None


def test_the_registry_the_publisher_is_built_on_is_the_one_read(monkeypatch, tmp_path) -> None:
    path = tmp_path / "shapes.json"
    path.write_text(json.dumps({"shapes": [{"machine_type": "x-1", "vcpu": 3, "memory_gib": "1.5"}]}))
    monkeypatch.setattr(get_settings(), "machine_shapes_path", path)
    machine_shapes._shapes.cache_clear()
    try:
        assert machine_capacity("gcp", "x-1")["memory_mib"] == "1536"
    finally:
        machine_shapes._shapes.cache_clear()
