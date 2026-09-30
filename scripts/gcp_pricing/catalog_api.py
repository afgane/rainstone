"""Cloud Billing Catalog API access: service discovery and SKU pagination.

https://docs.cloud.google.com/billing/v1/how-tos/catalog-api

The API key travels only in the ``X-Goog-Api-Key`` header, never in a URL or
query string, so it cannot end up in a logged or saved request URL.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

BASE_URL = "https://cloudbilling.googleapis.com/v1"
COMPUTE_ENGINE_DISPLAY_NAME = "Compute Engine"


class CatalogFetchError(RuntimeError):
    """The Catalog API could not be read completely and reliably."""


def _request(
    path: str,
    api_key: str,
    params: dict[str, Any],
    *,
    timeout: int,
    retries: int,
    opener: Callable[[urllib.request.Request, int], Any],
) -> dict:
    url = f"{BASE_URL}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"X-Goog-Api-Key": api_key})
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout) as response:
                payload = json.load(response)
            break
        except urllib.error.HTTPError as error:
            # 4xx is a request problem a retry cannot fix; only back off on 5xx.
            if error.code < 500:
                raise CatalogFetchError(f"Catalog API request failed ({error.code}): {path}") from error
            last_error = error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
        if attempt < retries:
            time.sleep(min(2**attempt, 8))
    else:
        raise CatalogFetchError(f"Catalog API request failed after {retries + 1} attempts: {path}") from last_error
    if not isinstance(payload, dict):
        raise CatalogFetchError(f"Catalog API returned a non-object response for {path}")
    return payload


def _rfc3339(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _open(request: urllib.request.Request, timeout: int):
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310


def discover_compute_engine_service(
    api_key: str,
    *,
    timeout: int = 30,
    retries: int = 3,
    opener: Callable[[urllib.request.Request, int], Any] = _open,
) -> str:
    """Return the Compute Engine service resource name, e.g. ``services/6F81-...``.

    A cached service identifier is fine to reuse across runs, but it must be
    reverified here rather than hardcoded: the identifier is only trustworthy
    once its display name has been confirmed.
    """
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"pageSize": 200}
        if page_token:
            params["pageToken"] = page_token
        payload = _request("services", api_key, params, timeout=timeout, retries=retries, opener=opener)
        services = payload.get("services")
        if services is None:
            raise CatalogFetchError("services listing response had no 'services' field")
        for service in services:
            if service.get("displayName") == COMPUTE_ENGINE_DISPLAY_NAME:
                name = service.get("name")
                if not name:
                    raise CatalogFetchError("Compute Engine service entry had no 'name'")
                return name
        page_token = payload.get("nextPageToken")
        if not page_token:
            raise CatalogFetchError(
                f"no service named '{COMPUTE_ENGINE_DISPLAY_NAME}' was found in the services listing"
            )


def list_skus(
    service_name: str,
    api_key: str,
    *,
    currency_code: str = "USD",
    page_size: int = 5000,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    timeout: int = 30,
    retries: int = 3,
    opener: Callable[[urllib.request.Request, int], Any] = _open,
) -> list[dict]:
    """Paginate a service's complete SKU listing.

    Without a time range this is the latest pricing. With one, each SKU lists
    every pricing version in effect during that range, which the API only
    accepts within one calendar month in America/Los_Angeles and not in the
    future.

    A page with a ``nextPageToken`` but no ``skus`` is an incomplete response,
    not an empty page, and is rejected rather than silently truncating the
    catalog.
    """
    time_range: dict[str, str] = {}
    if (start_time is None) != (end_time is None):
        raise ValueError("a SKU time range needs both start_time and end_time")
    if start_time is not None and end_time is not None:
        time_range = {"startTime": _rfc3339(start_time), "endTime": _rfc3339(end_time)}
    skus: list[dict] = []
    page_token: str | None = None
    seen_tokens: set[str] = set()
    while True:
        params: dict[str, Any] = {"currencyCode": currency_code, "pageSize": page_size, **time_range}
        if page_token:
            params["pageToken"] = page_token
        payload = _request(
            f"{service_name}/skus", api_key, params, timeout=timeout, retries=retries, opener=opener
        )
        page = payload.get("skus")
        next_token = payload.get("nextPageToken")
        if page is None:
            raise CatalogFetchError(f"SKU page for {service_name} had no 'skus' field")
        if not page and next_token:
            raise CatalogFetchError(f"SKU page for {service_name} was empty but claimed a next page")
        skus.extend(page)
        if not next_token:
            return skus
        if next_token in seen_tokens:
            raise CatalogFetchError(f"SKU pagination for {service_name} looped on a repeated page token")
        seen_tokens.add(next_token)
        page_token = next_token
