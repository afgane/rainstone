"""Collector-only Galaxy control, with sanitized errors and bounded requests."""

from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from rainstone.batch_spend import batch_spend, utcnow
from rainstone.config import Settings
from rainstone.models import GuardNotification, SpendGuard
from rainstone.spend_guard import audit

MESSAGES = {
    "triggered": "New Batch jobs are paused because your spend limit was reached. Jobs that fit on your Galaxy server still run.",
    "stale": "Cost data is out of date, so your spend limit may not be enforced.",
    "unpriced": "Some Batch compute can't be priced, so your spend limit may be exceeded.",
}


class GalaxyControlError(RuntimeError):
    pass


class GalaxyControl:
    def __init__(self, settings: Settings, *, transport=None):
        self.client = httpx.Client(
            base_url=(settings.guard_galaxy_url or "http://unconfigured.invalid").rstrip("/") + "/api/",
            headers={"x-api-key": settings.guard_galaxy_api_key.get_secret_value()},
            timeout=httpx.Timeout(5), transport=transport,
        )
        self.configured = bool(settings.guard_galaxy_url and settings.guard_galaxy_api_key.get_secret_value())

    def close(self):
        self.client.close()

    def request(self, method: str, path: str, **kwargs):
        if not self.configured:
            raise GalaxyControlError("Galaxy control access is not configured")
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else None
        except httpx.HTTPStatusError as error:
            raise GalaxyControlError(f"Galaxy returned HTTP {error.response.status_code}") from None
        except (httpx.RequestError, ValueError):
            raise GalaxyControlError("Galaxy did not return a valid response") from None

    def owner_id(self, username: str) -> str:
        users = self.request("GET", "users", params={"f_name": username})
        matches = [user for user in users if user.get("username") == username]
        if len(matches) != 1:
            raise GalaxyControlError("The configured Galaxy account could not be resolved")
        return matches[0]["id"]

    def outstanding_batch_jobs(self) -> list[dict]:
        result = self.request("GET", "jobs", params={
            "view": "admin_job_list", "search": "runner:gcp_batch",
            "state": ["new", "queued", "running", "resubmitted", "waiting"],
            "limit": 100, "offset": 0, "order_by": "create_time",
        })
        if not isinstance(result, list):
            raise GalaxyControlError("Galaxy returned invalid jobs")
        return result

    def cancel_job(self, encoded_id: str, external_id: str) -> bool:
        # A resubmission may have moved to the server since target discovery.
        current = self.request("GET", f"jobs/{encoded_id}")
        if current.get("job_runner_name") != "gcp_batch" or current.get("external_id") != external_id:
            return False
        if current.get("state") in {"ok", "error", "deleted", "deleting", "failed", "cancelled"}:
            return False
        return bool(self.request("DELETE", f"jobs/{encoded_id}", json={
            "message": "Stopped because the Batch spend limit was reached.",
        }))

    def broadcasts(self) -> list[dict]:
        result = self.request("GET", "notifications/broadcast")
        if not isinstance(result, list) or any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in result):
            raise GalaxyControlError("Galaxy returned invalid broadcasts")
        now = datetime.now(UTC)
        def instant(value):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
            return parsed.replace(tzinfo=UTC) if parsed and parsed.tzinfo is None else parsed
        # Galaxy returns inactive broadcasts to admins as well as active ones.
        try:
            return [item for item in result
                    if (not item.get("expiration_time") or instant(item["expiration_time"]) > now)
                    and (not item.get("publication_time") or instant(item["publication_time"]) <= now)]
        except (ValueError, TypeError):
            raise GalaxyControlError("Galaxy returned invalid broadcast times") from None

    def post_broadcast(self, source: str, message: str, link: str) -> str:
        result = self.request("POST", "notifications/broadcast", json={
            "source": source, "category": "broadcast", "variant": "warning",
            "content": {"category": "broadcast", "subject": "Batch spend limit", "message": message,
                        "action_links": [{"action_name": "Batch spend limit", "link": link}]},
        })
        try:
            return result["notification"]["id"]
        except (KeyError, TypeError):
            raise GalaxyControlError("Galaxy returned an invalid broadcast identity") from None

    def withdraw_broadcast(self, notification_id: str):
        self.request("PUT", f"notifications/broadcast/{notification_id}", json={
            "expiration_time": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        })


def broadcast_source(tenant_id, condition: str) -> str:
    # Galaxy stores source in VARCHAR(32); retain the full deployment UUID.
    identity = urlsafe_b64encode(tenant_id.bytes).decode().rstrip("=")
    return f"rs:{identity}:{condition[0]}"


def retry_delay(attempts: int) -> int:
    return min(300, 2 ** min(attempts, 8))


def reconcile_notifications(session: Session, guard: SpendGuard, settings: Settings, client: GalaxyControl) -> None:
    now = utcnow()
    snapshot = batch_spend(session, guard.tenant_id, guard.owner_id)
    active = guard.amount is not None and guard.enrollment == snapshot.enrollment
    desired = {
        "triggered": active and guard.triggered_at is not None,
        "stale": active and (snapshot.observed_at is None or snapshot.data_age(now) > settings.guard_stale_seconds),
        "unpriced": active and snapshot.unpriced_running_resources > 0,
    }
    rows = {row.condition: row for row in session.scalars(select(GuardNotification).where(
        GuardNotification.tenant_id == guard.tenant_id,
    ))}
    broadcasts = None
    for condition, needed in desired.items():
        row = rows.get(condition)
        if row is None:
            row = GuardNotification(tenant_id=guard.tenant_id, condition=condition, attempts=0)
            session.add(row)
        if row.retry_at and row.retry_at > now:
            continue
        source = broadcast_source(guard.tenant_id, condition)
        try:
            if broadcasts is None:
                broadcasts = client.broadcasts()
            # Recover a successful POST whose response or local commit was lost.
            matching = [item for item in broadcasts if item.get("source") == source]
            if needed:
                if matching:
                    row.notification_id = matching[0]["id"]
                    for duplicate in matching[1:]:
                        client.withdraw_broadcast(duplicate["id"])
                else:
                    row.notification_id = client.post_broadcast(source, MESSAGES[condition], settings.guard_page_url)
                    audit(session, guard, "notification_posted", "collector", condition=condition)
            else:
                for item in matching:
                    client.withdraw_broadcast(item["id"])
                if row.notification_id or matching:
                    audit(session, guard, "notification_withdrawn", "collector", condition=condition)
                row.notification_id = None
            row.error, row.retry_at, row.attempts = None, None, 0
        except GalaxyControlError as error:
            row.attempts += 1
            row.error = str(error)
            row.retry_at = now + timedelta(seconds=retry_delay(row.attempts))
            audit(session, guard, "notification_failed", "collector", condition=condition, error=row.error)
