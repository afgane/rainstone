from datetime import UTC, datetime, timedelta
from decimal import Decimal

from rainstone.batch_spend import BatchSpend, RunningResource
from rainstone.config import Settings
from rainstone.spend_guard import margin

NOW = datetime(2026, 10, 21, tzinfo=UTC)


def snapshot(*running: tuple[str, int]):
    resources = tuple(RunningResource(Decimal(rate), NOW - timedelta(seconds=age)) for rate, age in running)
    oldest = min((resource.observed_at for resource in resources), default=NOW)
    return BatchSpend(Decimal("3"), resources, oldest, NOW, "generation", "source", 0, 0, 0)


def test_margin_floor_burn_and_data_age_use_decimal_arithmetic():
    settings = Settings(guard_reaction_seconds=300)
    assert margin(snapshot(), settings, NOW) == Decimal("0.25")
    assert margin(snapshot(("40", 0)), settings, NOW) == Decimal("40") / 12
    assert margin(snapshot(("40", 60)), settings, NOW) == Decimal("4")
    assert margin(snapshot(("0.001", 0)), settings, NOW) == Decimal("0.25")


def test_each_running_vm_widens_the_margin_by_its_own_age():
    settings = Settings(guard_reaction_seconds=300)
    # A VM last seen an hour ago adds its own hour, not an hour for every VM.
    stale = snapshot(("12", 3600), ("12", 0))
    assert stale.data_age(NOW) == Decimal("3600")
    assert margin(stale, settings, NOW) == Decimal("12") * Decimal("3900") / 3600 + Decimal("1")


def test_default_reaction_allowance_covers_measured_slow_provisioning_cleanup():
    settings = Settings()
    assert settings.guard_reaction_seconds == 600
    assert margin(snapshot(("36", 0)), settings, NOW) == Decimal("6")
