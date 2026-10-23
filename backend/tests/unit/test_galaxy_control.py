import json

import httpx
import pytest
from rainstone.config import Settings
from rainstone.galaxy_control import GalaxyControl, GalaxyControlError


def test_broadcast_requests_a_new_tab_for_rainstone():
    def handler(request):
        action = json.loads(request.content)["content"]["action_links"][0]
        assert action == {"action_name": "Batch spend limit", "link": "https://example.org/costs/", "target": "_blank"}
        return httpx.Response(200, json={"notification": {"id": "notice"}})
    client = GalaxyControl(Settings(guard_galaxy_url="http://galaxy", guard_galaxy_api_key="test"),
                           transport=httpx.MockTransport(handler))
    try:
        assert client.post_broadcast("test", "message", "https://example.org/costs/") == "notice"
    finally:
        client.close()


def test_control_request_scopes_url_and_never_exposes_key_in_errors():
    key = "private-test-key"
    def handler(request):
        assert request.url.path == "/galaxy/api/notifications/broadcast"
        assert request.headers["x-api-key"] == key
        return httpx.Response(403, text="secret body " + key)
    client = GalaxyControl(Settings(guard_galaxy_url="http://galaxy/galaxy", guard_galaxy_api_key=key),
                           transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(GalaxyControlError) as error:
            client.broadcasts()
        assert str(error.value) == "Galaxy returned HTTP 403"
        assert key not in repr(Settings(guard_galaxy_api_key=key))
    finally:
        client.close()


def test_admin_broadcast_listing_excludes_expired_and_scheduled_notices():
    def handler(request):
        return httpx.Response(200, json=[
            {"id": "expired", "expiration_time": "2000-01-01T00:00:00"},
            {"id": "scheduled", "publication_time": "2100-01-01T00:00:00"},
            {"id": "active", "publication_time": "2000-01-01T00:00:00"},
        ])
    client = GalaxyControl(Settings(guard_galaxy_url="http://galaxy", guard_galaxy_api_key="test"),
                           transport=httpx.MockTransport(handler))
    try:
        assert [item["id"] for item in client.broadcasts()] == ["active"]
    finally:
        client.close()


def test_job_that_moved_to_server_is_not_cancelled():
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json={"job_runner_name": "k8s", "external_id": "local", "state": "running"})
    client = GalaxyControl(Settings(guard_galaxy_url="http://galaxy", guard_galaxy_api_key="test"),
                           transport=httpx.MockTransport(handler))
    try:
        assert client.cancel_job("encoded-job", "test-batch") is False
        assert calls == ["GET"]
    finally:
        client.close()
