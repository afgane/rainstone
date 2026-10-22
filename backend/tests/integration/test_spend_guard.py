# ruff: noqa: F811
from datetime import timedelta
from decimal import Decimal

import pytest
from rainstone.config import Settings
from rainstone.models import GuardAudit, SpendGuard
from rainstone.spend_guard import PolicyConflict, evaluate, set_policy
from sqlalchemy import select

from .test_batch_spend import START, spend_source  # noqa: F401


def configure(source, amount="5", revision=0):
    session, tenant, owner, job, resource = source
    return set_policy(session, tenant.id, owner.id, revision, Decimal(amount) if amount else None,
                      False, Settings(guard_enabled=True), owner.source_id)


def test_activation_includes_prior_spend_and_revision_conflicts(spend_source, monkeypatch):
    monkeypatch.setattr("rainstone.spend_guard.utcnow", lambda: START + timedelta(hours=1))
    for amount in ("1", "2"):
        with pytest.raises(ValueError, match="greater than"):
            configure(spend_source, amount)
    guard = configure(spend_source)
    assert guard.revision == 1
    assert guard.triggered_at is None
    with pytest.raises(PolicyConflict):
        configure(spend_source, "6")
    assert configure(spend_source, "6", revision=1).revision == 2


def test_immediate_trigger_latches_and_disable_releases(spend_source):
    from rainstone.batch_spend import batch_spend

    session, tenant, owner, job, resource = spend_source
    guard = configure(spend_source, "2.10")
    assert guard.triggered_at is not None
    resource.observed_end = START + timedelta(minutes=1)
    session.flush()
    evaluate(session, guard, batch_spend(session, tenant.id, owner.id), Settings(), START)
    assert guard.triggered_at is not None
    assert session.scalar(select(GuardAudit).where(GuardAudit.action == "triggered"))
    assert configure(spend_source, None, revision=1).amount is None
    assert session.get(SpendGuard, tenant.id).triggered_at is None


def test_latch_survives_session_reload_and_raising_limit(spend_source):
    session, tenant, owner, job, resource = spend_source
    configure(spend_source, "2.10")
    session.flush()
    session.expire_all()
    assert session.get(SpendGuard, tenant.id).triggered_at is not None
    # Margin from an old observation may trigger immediately, so use a frozen
    # policy clock when checking explicit release below.
    from unittest.mock import patch
    with patch("rainstone.spend_guard.utcnow", return_value=START + timedelta(hours=1)):
        raised = configure(spend_source, "100", revision=1)
    assert raised.triggered_at is None


def test_replacing_source_cannot_silently_reset_an_active_guard(spend_source):
    from rainstone.enrollment import SourceReplacementDetected, ensure_enrollment

    session, tenant, owner, job, resource = spend_source
    configure(spend_source, "100")
    with pytest.raises(SourceReplacementDetected, match="Turn off the Batch spend limit"):
        ensure_enrollment(session, Settings(tenant_slug=tenant.slug), None, None, reenroll=True)


def test_triggered_guard_accepts_a_new_stop_choice_without_resuming(spend_source):
    session, tenant, owner, job, resource = spend_source
    guard = configure(spend_source, "2.10")
    triggered_at = guard.triggered_at
    assert triggered_at is not None
    changed = set_policy(session, tenant.id, owner.id, 1, Decimal("2.10"), True,
                         Settings(guard_enabled=True), owner.source_id)
    assert changed.stop_jobs and changed.triggered_at == triggered_at
    lowered = set_policy(session, tenant.id, owner.id, 2, Decimal("2.05"), True,
                         Settings(guard_enabled=True), owner.source_id)
    assert lowered.triggered_at == triggered_at
