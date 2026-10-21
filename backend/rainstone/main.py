import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from rainstone.api.guard import internal_router
from rainstone.api.guard import router as guard_router
from rainstone.api.routes import router
from rainstone.config import get_settings
from rainstone.logging import configure_logging
from rainstone.request_logging import RequestLogging

settings = get_settings()
configure_logging("web", settings)
logger = logging.getLogger("rainstone.web")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("web_started", extra={"fields": {"version": app.version}})
    yield
    logger.info("web_stopped")


app = FastAPI(title="Rainstone", version="2.0.0b1", root_path=settings.root_path, lifespan=lifespan)
app.add_middleware(RequestLogging, slow_seconds=settings.log_slow_request_seconds)
app.include_router(router)
app.include_router(guard_router)
app.include_router(internal_router)

static_dir = settings.static_dir


def _meta(html: str, name: str, value: str) -> str:
    return re.sub(
        rf'(<meta name="{name}" content=")[^"]*(")', rf"\g<1>{value}\g<2>", html, count=1
    )


if static_dir.exists():
    assets = static_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request):
        candidate = static_dir / path
        if candidate.is_file() and static_dir.resolve() in candidate.resolve().parents:
            return FileResponse(candidate)
        prefix = request.headers.get("x-forwarded-prefix", settings.root_path).rstrip("/")
        html = (static_dir / "index.html").read_text()
        html = _meta(html, "rainstone-base", prefix or "/")
        # The browser only sends fixture identity headers in development mode.
        html = _meta(html, "rainstone-auth-mode", settings.auth_mode)
        return HTMLResponse(html)
