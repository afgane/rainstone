"""Dating each price from the SKUs' month-by-month price history."""

from datetime import UTC, datetime
from decimal import Decimal

from gcp_pricing.catalog_api import CatalogFetchError
from gcp_pricing.history import Month, date_from_history, months_back
from gcp_pricing.mapping import ComponentRates, PricePoint

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
SEPTEMBER = datetime(2026, 9, 1, 7, tzinfo=UTC)
AUGUST = datetime(2026, 8, 1, 7, tzinfo=UTC)
JULY = datetime(2026, 7, 1, 7, tzinfo=UTC)
LISTING_DAY = "2026-09-22T07:00:00Z"


def point(sku_id: str, rate: str, unit: str = "h") -> PricePoint:
    return PricePoint(sku_id, "description", Decimal(rate), unit, LISTING_DAY)


def sku(sku_id: str, *versions: tuple[str, str], unit: str = "h") -> dict:
    return {
        "skuId": sku_id,
        "pricingInfo": [
            {
                "effectiveTime": effective,
                "pricingExpression": {
                    "usageUnit": unit,
                    "tieredRates": [
                        {
                            "startUsageAmount": 0,
                            "unitPrice": {"currencyCode": "USD", "units": "0", "nanos": int(Decimal(rate) * 10**9)},
                        }
                    ],
                },
                "currencyConversionRate": 1,
            }
            for effective, rate in versions
        ],
    }


def history(months: dict[datetime, list[dict] | Exception]):
    """A month lister keyed by each month's start; a missing month lists nothing."""

    def list_month(start: datetime, _end: datetime) -> list[dict]:
        outcome = months.get(start, [])
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return list_month


def n2_rates(cpu_rate: str = "0.031611") -> dict:
    return {
        ("n2", "us-central1"): ComponentRates(point("cpu", cpu_rate), point("ram", "0.004237", "GiBy.h"))
    }


def ram_unchanged(*months: datetime) -> dict[datetime, list[dict]]:
    return {month: [sku("ram", (month.isoformat(), "0.004237"), unit="GiBy.h")] for month in months}


def dated(rates: dict) -> tuple[str | None, str | None]:
    component = rates[("n2", "us-central1")]
    return component.cpu.effective_time, component.ram.effective_time


def test_months_follow_pacific_calendar_months_back_from_now() -> None:
    months = list(months_back(NOW, 3))
    assert months == [Month(SEPTEMBER, NOW), Month(AUGUST, SEPTEMBER), Month(JULY, AUGUST)]


def test_month_boundaries_follow_pacific_daylight_saving_and_the_year() -> None:
    months = list(months_back(datetime(2026, 1, 10, tzinfo=UTC), 3))
    assert [month.start for month in months] == [
        datetime(2026, 1, 1, 8, tzinfo=UTC),
        datetime(2025, 12, 1, 8, tzinfo=UTC),
        datetime(2025, 11, 1, 7, tzinfo=UTC),
    ]


def test_the_first_instant_of_a_month_does_not_ask_for_an_empty_range() -> None:
    months = list(months_back(SEPTEMBER, 2))
    assert months == [Month(AUGUST, SEPTEMBER)]


def test_a_price_unchanged_throughout_is_dated_to_the_oldest_month_read() -> None:
    listing = {
        month: [sku("cpu", (month.isoformat(), "0.031611")), *ram_unchanged(month)[month]]
        for month in (SEPTEMBER, AUGUST, JULY)
    }
    rates, problems = date_from_history(n2_rates(), history(listing), now=NOW, months=3)
    assert problems == []
    assert dated(rates) == ("2026-07-01T07:00:00Z", "2026-07-01T07:00:00Z")


def test_a_change_dated_inside_a_month_is_when_the_price_took_effect() -> None:
    change = "2026-08-15T07:00:00Z"
    listing = ram_unchanged(SEPTEMBER, AUGUST, JULY)
    listing[SEPTEMBER] = listing[SEPTEMBER] + [sku("cpu", ("2026-09-01T07:00:00Z", "0.031611"))]
    listing[AUGUST] = listing[AUGUST] + [sku("cpu", ("2026-08-01T07:00:00Z", "0.030000"), (change, "0.031611"))]
    rates, _problems = date_from_history(n2_rates(), history(listing), now=NOW, months=3)
    assert dated(rates)[0] == change


def test_a_change_not_dated_after_the_month_began_ends_at_the_next_month() -> None:
    """An API that dates a version to the range start says nothing about when
    inside the month it began, so only the following month is certain.
    """
    listing = ram_unchanged(SEPTEMBER, AUGUST, JULY)
    listing[SEPTEMBER] = listing[SEPTEMBER] + [sku("cpu", ("2026-09-01T07:00:00Z", "0.031611"))]
    listing[AUGUST] = listing[AUGUST] + [
        sku("cpu", ("2026-08-01T07:00:00Z", "0.031611"), ("2026-08-01T07:00:00Z", "0.030000"))
    ]
    rates, _problems = date_from_history(n2_rates(), history(listing), now=NOW, months=3)
    assert dated(rates)[0] == "2026-09-01T07:00:00Z"


def test_a_price_that_changed_back_is_dated_from_its_latest_return() -> None:
    back = "2026-09-10T07:00:00Z"
    listing = ram_unchanged(SEPTEMBER)
    listing[SEPTEMBER] = listing[SEPTEMBER] + [
        sku("cpu", ("2026-09-01T07:00:00Z", "0.031611"), ("2026-09-05T07:00:00Z", "0.030000"), (back, "0.031611"))
    ]
    rates, _problems = date_from_history(n2_rates(), history(listing), now=NOW, months=3)
    assert dated(rates)[0] == back


def test_a_month_that_no_longer_lists_the_sku_ends_the_walk() -> None:
    listing = ram_unchanged(SEPTEMBER, AUGUST, JULY)
    listing[SEPTEMBER] = listing[SEPTEMBER] + [sku("cpu", ("2026-09-01T07:00:00Z", "0.031611"))]
    listing[JULY] = listing[JULY] + [sku("cpu", ("2026-07-01T07:00:00Z", "0.031611"))]
    rates, _problems = date_from_history(n2_rates(), history(listing), now=NOW, months=3)
    assert dated(rates) == ("2026-09-01T07:00:00Z", "2026-07-01T07:00:00Z")


def test_a_listing_dated_after_the_month_asked_for_is_not_its_history() -> None:
    """Latest pricing returned for a past month would show the current price
    dated today, which says nothing about that month.
    """
    listing = ram_unchanged(SEPTEMBER, AUGUST)
    listing[SEPTEMBER] = listing[SEPTEMBER] + [sku("cpu", ("2026-09-01T07:00:00Z", "0.031611"))]
    listing[AUGUST] = listing[AUGUST] + [sku("cpu", (LISTING_DAY, "0.031611"))]
    rates, _problems = date_from_history(n2_rates(), history(listing), now=NOW, months=2)
    assert dated(rates) == ("2026-09-01T07:00:00Z", "2026-08-01T07:00:00Z")


def test_a_price_that_began_late_in_a_month_is_not_credited_for_all_of_it() -> None:
    began = "2026-08-31T20:00:00Z"
    listing = ram_unchanged(SEPTEMBER, AUGUST)
    listing[SEPTEMBER] = listing[SEPTEMBER] + [sku("cpu", ("2026-09-01T07:00:00Z", "0.031611"))]
    listing[AUGUST] = listing[AUGUST] + [sku("cpu", (began, "0.031611"))]
    rates, _problems = date_from_history(n2_rates(), history(listing), now=NOW, months=2)
    assert dated(rates)[0] == began


def test_a_price_dated_long_before_the_month_counts_the_whole_month() -> None:
    listing = ram_unchanged(SEPTEMBER, AUGUST)
    listing[SEPTEMBER] = listing[SEPTEMBER] + [sku("cpu", ("2024-03-01T08:00:00Z", "0.031611"))]
    listing[AUGUST] = listing[AUGUST] + [sku("cpu", ("2024-03-01T08:00:00Z", "0.031611"))]
    rates, _problems = date_from_history(n2_rates(), history(listing), now=NOW, months=2)
    assert dated(rates)[0] == "2026-08-01T07:00:00Z"


def test_a_month_that_cannot_be_read_is_reported_and_ends_the_walk() -> None:
    listing: dict = {
        SEPTEMBER: [sku("cpu", ("2026-09-01T07:00:00Z", "0.031611")), *ram_unchanged(SEPTEMBER)[SEPTEMBER]],
        AUGUST: CatalogFetchError("Catalog API request failed (400)"),
    }
    rates, problems = date_from_history(n2_rates(), history(listing), now=NOW, months=3)
    assert dated(rates) == ("2026-09-01T07:00:00Z", "2026-09-01T07:00:00Z")
    assert len(problems) == 1 and "unavailable" in problems[0]


def test_without_any_readable_history_a_price_keeps_its_listing_date() -> None:
    listing = {SEPTEMBER: CatalogFetchError("Catalog API request failed (400)")}
    rates, problems = date_from_history(n2_rates(), history(listing), now=NOW, months=3)
    assert dated(rates) == (LISTING_DAY, LISTING_DAY)
    assert problems


def test_a_malformed_history_entry_ends_the_walk_rather_than_guessing() -> None:
    listing = ram_unchanged(SEPTEMBER, AUGUST)
    listing[SEPTEMBER] = listing[SEPTEMBER] + [sku("cpu", ("2026-09-01T07:00:00Z", "0.031611"))]
    listing[AUGUST] = listing[AUGUST] + [sku("cpu", ("2026-08-01T07:00:00Z", "0.031611"), unit="GiBy.h")]
    rates, _problems = date_from_history(n2_rates(), history(listing), now=NOW, months=2)
    assert dated(rates)[0] == "2026-09-01T07:00:00Z"


def test_no_history_months_leaves_listing_dates() -> None:
    rates, problems = date_from_history(n2_rates(), history({}), now=NOW, months=0)
    assert dated(rates) == (LISTING_DAY, LISTING_DAY)
    assert problems == []


def test_a_gpu_is_dated_like_any_other_component() -> None:
    region_rates = {
        ("g2", "us-central1"): ComponentRates(
            point("cpu", "0.024988"), point("ram", "0.002928", "GiBy.h"), point("gpu", "0.56004")
        )
    }
    listing = {
        SEPTEMBER: [
            sku("cpu", ("2026-09-01T07:00:00Z", "0.024988")),
            sku("ram", ("2026-09-01T07:00:00Z", "0.002928"), unit="GiBy.h"),
            sku("gpu", ("2026-09-01T07:00:00Z", "0.56004")),
        ]
    }
    rates, _problems = date_from_history(region_rates, history(listing), now=NOW, months=1)
    assert rates[("g2", "us-central1")].gpu.effective_time == "2026-09-01T07:00:00Z"
