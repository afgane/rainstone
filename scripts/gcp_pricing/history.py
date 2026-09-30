"""Date each price by when it actually took effect, from the SKUs' price history.

The latest-pricing listing dates every price to the start of the day it was
read, so a catalog built from it alone could price nothing that ran before
that day. The Catalog API lists past pricing versions only one calendar month
(America/Los_Angeles) at a time, so this walks back month by month while a SKU
kept its current price.

Whatever the API does with a version that began before the queried month, the
date published here is never earlier than the evidence: a month counts only
when the current price is its only price and was already in effect when the
month began, a price that began inside a month is dated from when it began,
and a month that cannot be read, no longer lists the SKU, or lists a version
dated after the month ends the walk at the last month that could.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from gcp_pricing.catalog_api import CatalogFetchError
from gcp_pricing.mapping import (
    Component,
    ComponentRates,
    MappingError,
    PricePoint,
    info_rate,
)

PRICING_TIMEZONE = ZoneInfo("America/Los_Angeles")
DEFAULT_HISTORY_MONTHS = 12

# Lists every SKU with its pricing versions in effect in [start, end).
ListSkus = Callable[[datetime, datetime], list[dict]]


@dataclass(frozen=True)
class Month:
    start: datetime
    end: datetime


def months_back(now: datetime, count: int) -> Iterator[Month]:
    """The current Pacific calendar month up to `now`, then `count - 1` before it."""
    local = now.astimezone(PRICING_TIMEZONE)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = now
    for _ in range(count):
        # The API refuses an empty range, which the first instant of a month would give.
        if end > start:
            yield Month(start.astimezone(UTC), end.astimezone(UTC))
        end = start
        year, month = (start.year, start.month - 1) if start.month > 1 else (start.year - 1, 12)
        start = start.replace(year=year, month=month)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _versions(sku: dict, component: Component) -> list[tuple[datetime, Decimal]] | None:
    """(effective time, rate) for each pricing version, oldest first; None if unreadable."""
    versions = []
    for info in sku.get("pricingInfo") or []:
        effective = info.get("effectiveTime")
        if not effective:
            return None
        try:
            versions.append((_parse(effective), info_rate(info, component, sku_id=sku.get("skuId", "?"))))
        except (MappingError, ValueError):
            return None
    return sorted(versions, key=lambda version: version[0]) or None


def _in_effect_since(
    point: PricePoint, component: Component, months: list[Month], listings: list[dict[str, dict] | None]
) -> datetime | None:
    """How far back `point`'s rate is shown in effect without a break, or None."""
    verified: datetime | None = None
    for month, listing in zip(months, listings, strict=True):
        sku = listing.get(point.sku_id) if listing is not None else None
        versions = _versions(sku, component) if sku is not None else None
        # A version dated after the month cannot describe it: the response is
        # not that month's history, however its prices compare.
        if versions is None or any(time >= month.end for time, _rate in versions):
            return verified
        others = [index for index, (_time, rate) in enumerate(versions) if rate != point.rate_per_unit]
        current = versions[others[-1] + 1 :] if others else versions
        if not current:
            return verified
        began = current[0][0]
        if began > month.start:
            return began
        if others:
            return verified
        verified = month.start
    return verified


def date_from_history(
    region_rates: dict[tuple[str, str], ComponentRates],
    list_month: ListSkus,
    *,
    now: datetime,
    months: int = DEFAULT_HISTORY_MONTHS,
) -> tuple[dict[tuple[str, str], ComponentRates], list[str]]:
    """Replace each component's read-day date with when its price took effect.

    Returns the redated rates and a list of problems: a month that could not
    be read is reported, and every price keeps the date it was verified to.
    A price with no verifiable history keeps the listing's own date.
    """
    wanted = {point.sku_id for rates in region_rates.values() for point in rates.points()}
    windows = list(months_back(now, months))
    listings: list[dict[str, dict] | None] = []
    problems: list[str] = []
    for month in windows:
        try:
            skus = list_month(month.start, month.end)
        except CatalogFetchError as error:
            problems.append(f"price history before {month.end.isoformat()} is unavailable: {error}")
            break
        listings.append({sku["skuId"]: sku for sku in skus if sku.get("skuId") in wanted})
    listings.extend([None] * (len(windows) - len(listings)))

    def redate(point: PricePoint, component: Component) -> PricePoint:
        since = _in_effect_since(point, component, windows, listings)
        if since is None:
            return point
        return replace(point, effective_time=since.isoformat().replace("+00:00", "Z"))

    redated = {
        key: ComponentRates(
            cpu=redate(rates.cpu, "cpu"),
            ram=redate(rates.ram, "ram"),
            gpu=redate(rates.gpu, "gpu") if rates.gpu is not None else None,
        )
        for key, rates in region_rates.items()
    }
    return redated, problems
