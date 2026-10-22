# ruff: noqa: F811
from decimal import Decimal
from unittest.mock import Mock

from rainstone.batch_spend import batch_spend
from rainstone.config import Settings
from rainstone.galaxy_control import GalaxyControlError, broadcast_source, reconcile_notifications
from rainstone.models import GuardNotification
from rainstone.spend_guard import set_policy

from .test_batch_spend import spend_source  # noqa: F401


def test_notifications_recover_post_commit_loss_and_withdraw_on_disable(spend_source):
    session, tenant, owner, job, resource = spend_source
    settings = Settings()
    guard = set_policy(session, tenant.id, owner.id, 0, Decimal("2.10"), False, settings, "owner")
    client = Mock()
    client.post_broadcast.return_value = "new-broadcast"
    existing = {"source": broadcast_source(tenant.id, "triggered"), "id": "existing-broadcast"}
    client.broadcasts.return_value = [existing]
    reconcile_notifications(session, guard, batch_spend(session, tenant.id, owner.id), settings, client)
    session.flush()
    assert session.get(GuardNotification, (tenant.id, "triggered")).notification_id == "existing-broadcast"
    # The stale-data notice is separate; recovery must not create another
    # triggered notice when the POST response or local commit was lost.
    assert not any(call.args[0] == existing["source"] for call in client.post_broadcast.call_args_list)
    guard = set_policy(session, tenant.id, owner.id, 1, None, False, settings, "owner")
    reconcile_notifications(session, guard, batch_spend(session, tenant.id, owner.id), settings, client)
    client.withdraw_broadcast.assert_called_with("existing-broadcast")


def test_failed_notification_is_recorded_with_bounded_retry(spend_source):
    session, tenant, owner, job, resource = spend_source
    settings = Settings()
    guard = set_policy(session, tenant.id, owner.id, 0, Decimal("2.10"), False, settings, "owner")
    client = Mock()
    client.post_broadcast.return_value = "new-broadcast"
    client.broadcasts.side_effect = GalaxyControlError("Galaxy returned HTTP 503")
    reconcile_notifications(session, guard, batch_spend(session, tenant.id, owner.id), settings, client)
    session.flush()
    notice = session.get(GuardNotification, (tenant.id, "triggered"))
    assert notice.error == "Galaxy returned HTTP 503"
    assert notice.attempts == 1
    count = client.broadcasts.call_count
    reconcile_notifications(session, guard, batch_spend(session, tenant.id, owner.id), settings, client)
    assert client.broadcasts.call_count == count


def test_notice_links_to_the_page_the_browser_used_and_replaces_an_outdated_link(spend_source):
    session, tenant, owner, job, resource = spend_source
    settings = Settings()
    page = "https://example.org/proxy/app/galaxy/costs/?view=limit"
    guard = set_policy(session, tenant.id, owner.id, 0, Decimal("2.10"), False, settings, "owner", page)
    client = Mock()
    client.post_broadcast.return_value = "new-broadcast"
    outdated = {"source": broadcast_source(tenant.id, "triggered"), "id": "outdated",
                "content": {"action_links": [{"link": "/galaxy/costs/?view=limit"}]}}
    client.broadcasts.return_value = [outdated]
    reconcile_notifications(session, guard, batch_spend(session, tenant.id, owner.id), settings, client)
    client.withdraw_broadcast.assert_any_call("outdated")
    links = {call.args[0]: call.args[2] for call in client.post_broadcast.call_args_list}
    assert links[broadcast_source(tenant.id, "triggered")] == page


def test_unreachable_galaxy_costs_one_request_per_pass(spend_source):
    session, tenant, owner, job, resource = spend_source
    settings = Settings()
    guard = set_policy(session, tenant.id, owner.id, 0, Decimal("2.10"), False, settings, "owner")
    client = Mock()
    client.broadcasts.side_effect = GalaxyControlError("Galaxy did not return a valid response")
    reconcile_notifications(session, guard, batch_spend(session, tenant.id, owner.id), settings, client)
    assert client.broadcasts.call_count == 1
    assert all(session.get(GuardNotification, (tenant.id, condition)).error
               for condition in ("triggered", "stale", "unpriced"))
