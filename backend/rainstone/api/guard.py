import secrets
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from rainstone.auth import Identity, current_identity
from rainstone.batch_spend import enrollment
from rainstone.config import Settings, get_settings
from rainstone.db import get_session
from rainstone.enrollment import active_tenant
from rainstone.models import SpendGuard
from rainstone.spend_guard import PolicyConflict, set_policy, status

router = APIRouter(prefix="/api/spend-guard", tags=["spend-guard"])


class GuardPolicy(BaseModel):
    revision: int = Field(ge=0)
    limit: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    stop_jobs: bool


def guard_identity(identity: Identity = Depends(current_identity),
                   settings: Settings = Depends(get_settings),
                   session: Session = Depends(get_session)) -> Identity:
    if not settings.guard_enabled or settings.auth_mode not in {"anvil-workspace", "development"}:
        raise HTTPException(404, "Batch spend limits are not available on this deployment")
    guard = session.get(SpendGuard, identity.tenant_id)
    if guard and guard.owner_id != identity.owner_id:
        raise HTTPException(403, "This limit belongs to another Galaxy account")
    return identity


def limit_page_url(referer: str | None) -> str | None:
    """The limit page as the browser saw it, for links posted to Galaxy."""
    parts = urlsplit(referer or "")
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "view=limit", ""))


@router.get("")
def get_guard(session: Session = Depends(get_session), identity: Identity = Depends(guard_identity),
              settings: Settings = Depends(get_settings)) -> dict:
    return status(session, identity.tenant_id, identity.owner_id, settings)


@router.put("")
def update_guard(payload: GuardPolicy, session: Session = Depends(get_session),
                 identity: Identity = Depends(guard_identity), settings: Settings = Depends(get_settings),
                 referer: str | None = Header(default=None)) -> dict:
    try:
        set_policy(session, identity.tenant_id, identity.owner_id, payload.revision,
                   payload.limit, payload.stop_jobs, settings, identity.source_id, limit_page_url(referer))
        session.commit()
    except PolicyConflict as error:
        session.rollback()
        raise HTTPException(409, str(error)) from None
    except ValueError as error:
        session.rollback()
        raise HTTPException(422, str(error)) from None
    except DBAPIError as error:
        session.rollback()
        if getattr(error.orig, "sqlstate", None) in {"40001", "40P01", "23505"}:
            raise HTTPException(409, "The limit changed. Reload it before saving again.") from None
        raise
    return status(session, identity.tenant_id, identity.owner_id, settings)


internal_router = APIRouter(prefix="/api/internal", tags=["internal"])


@internal_router.get("/batch-dispatch")
def batch_dispatch(authorization: str | None = Header(default=None),
                   session: Session = Depends(get_session),
                   settings: Settings = Depends(get_settings)) -> dict:
    token = settings.guard_token.get_secret_value()
    if not token or not secrets.compare_digest(authorization or "", f"Bearer {token}"):
        raise HTTPException(401, "Dispatch credential required")
    if not settings.guard_enabled or settings.auth_mode != "anvil-workspace":
        return {"paused": False}
    tenant = active_tenant(session, settings)
    if tenant is None:
        return {"paused": False}
    guard = session.get(SpendGuard, tenant.id)
    return {"paused": bool(guard and guard.amount is not None and guard.triggered_at
                           and guard.enrollment == enrollment(session, tenant.id))}
