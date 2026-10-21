from decimal import Decimal

import pytest
from rainstone.config import Settings, get_settings
from rainstone.db import engine
from rainstone.main import app
from rainstone.models import GuardAudit, SpendGuard, Tenant
from sqlalchemy import delete, select
from sqlalchemy.orm import Session


@pytest.fixture()
def guard_api(client):
    settings = Settings(guard_enabled=True, demo_data=False, auth_mode="anvil-workspace", workspace_owner_source_id="alice",
                        guard_token="dispatch-test-token")
    app.dependency_overrides[get_settings] = lambda: settings
    yield client
    app.dependency_overrides.pop(get_settings, None)
    with Session(engine) as session:
        tenant = session.scalar(select(Tenant).where(Tenant.slug == settings.tenant_slug))
        session.execute(delete(GuardAudit).where(GuardAudit.tenant_id == tenant.id))
        session.execute(delete(SpendGuard).where(SpendGuard.tenant_id == tenant.id))
        session.commit()


def test_dispatch_state_is_authenticated_and_contains_no_cost_or_identity(guard_api):
    assert guard_api.get("/api/internal/batch-dispatch").status_code == 401
    assert guard_api.get("/api/internal/batch-dispatch", headers={"Authorization": "Bearer wrong"}).status_code == 401
    authorization = {"Authorization": "Bearer dispatch-test-token"}
    assert guard_api.get("/api/internal/batch-dispatch", headers=authorization).json() == {"paused": False}
    state = guard_api.get("/api/spend-guard").json()
    limit = (Decimal(state["snapshot"]["amount"]) + Decimal("0.01")).quantize(Decimal("0.01"))
    response = guard_api.put("/api/spend-guard", json={"revision": 0, "limit": str(limit), "stop_jobs": False})
    assert response.status_code == 200, response.text
    assert response.json()["triggered_at"] is not None
    assert guard_api.get("/api/internal/batch-dispatch", headers=authorization).json() == {"paused": True}
    assert guard_api.put("/api/spend-guard", json={"revision": 0, "limit": None, "stop_jobs": False}).status_code == 409
    assert guard_api.put("/api/spend-guard", json={"revision": 1, "limit": None, "stop_jobs": False}).status_code == 200
    assert guard_api.get("/api/internal/batch-dispatch", headers=authorization).json() == {"paused": False}
    assert guard_api.get("/api/spend-guard", headers={"X-Rainstone-User": "bob"}).status_code == 403


def test_multiuser_deployments_cannot_enable_guard(client):
    settings = Settings(guard_enabled=True, auth_mode="trusted-proxy")
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = client.get("/api/spend-guard", headers={"X-Rainstone-Tenant": "anvil-demo", "X-Rainstone-User": "alice"})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_settings, None)
