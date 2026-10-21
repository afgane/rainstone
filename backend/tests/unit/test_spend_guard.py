from datetime import UTC, datetime, timedelta
from decimal import Decimal

from rainstone.batch_spend import BatchSpend
from rainstone.config import Settings
from rainstone.spend_guard import margin

NOW = datetime(2026, 10, 21, tzinfo=UTC)


def snapshot(rate="0", age=0):
    return BatchSpend(Decimal("3"), Decimal(rate), NOW - timedelta(seconds=age),
                      NOW, "generation", "source", 0, 0, 0)


def test_margin_floor_burn_and_data_age_use_decimal_arithmetic():
    settings = Settings(guard_reaction_seconds=300)
    assert margin(snapshot(), settings, NOW) == Decimal("0.25")
    assert margin(snapshot("40"), settings, NOW) == Decimal("40") / 12
    assert margin(snapshot("40", age=60), settings, NOW) == Decimal("4")
    assert margin(snapshot("0.001"), settings, NOW) == Decimal("0.25")


def test_default_reaction_allowance_covers_measured_slow_provisioning_cleanup():
    settings = Settings()
    assert settings.guard_reaction_seconds == 600
    assert margin(snapshot("36"), settings, NOW) == Decimal("6")
