import logging
import time
import uuid

from rainstone.logging import request_id

logger = logging.getLogger("rainstone.web")
QUIET = {"/api/health", "/api/ready", "/api/freshness"}


class RequestLogging:
    def __init__(self, app, slow_seconds: float, clock=time.monotonic):
        self.app, self.slow_seconds = app, slow_seconds
        self.clock = clock
        self.ready: bool | None = None
        self.health: bool | None = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        token = request_id.set(uuid.uuid4().hex)
        started, status, sent = self.clock(), 500, False

        async def response(message):
            nonlocal status, sent
            if message["type"] == "http.response.start":
                status = message["status"]
                sent = True
                message = {**message, "headers": [
                    *message.get("headers", []), (b"x-request-id", request_id.get().encode()),
                ]}
            await send(message)

        try:
            await self.app(scope, receive, response)
        except Exception as error:
            route = self.route(scope)
            probe = "ready" if route == "/api/ready" else "health" if route == "/api/health" else None
            if probe is None or getattr(self, probe) is not False:
                logger.exception("probe_failed" if probe else "request_failed", extra={"fields": {
                    "method": scope["method"], "route": route, "status": 500,
                    "request_id": request_id.get(),
                    "duration_ms": round((self.clock() - started) * 1000, 1),
                }})
            if probe:
                setattr(self, probe, False)
            error._rainstone_logged = True
            if not sent:
                await response({"type": "http.response.start", "status": 500,
                                "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
                await response({"type": "http.response.body", "body": b"Internal Server Error"})
            raise
        else:
            elapsed = self.clock() - started
            route = self.route(scope)
            fields = {"method": scope["method"], "route": route, "status": status,
                      "request_id": request_id.get(),
                      "duration_ms": round(elapsed * 1000, 1)}
            if route in {"/api/ready", "/api/health"}:
                attribute = "ready" if route == "/api/ready" else "health"
                healthy = status < 400
                previous = getattr(self, attribute)
                if (previous is None and not healthy) or (previous is not None and previous != healthy):
                    logger.log(logging.INFO if healthy else logging.WARNING,
                               "probe_recovered" if healthy else "probe_failed", extra={"fields": fields})
                setattr(self, attribute, healthy)
            elif status >= 400 or elapsed >= self.slow_seconds:
                logger.log(logging.ERROR if status >= 500 else logging.WARNING,
                           "request_completed", extra={"fields": fields})
            elif route not in QUIET | {"/assets", "/{path:path}", "<unmatched>"}:
                logger.info("request_completed", extra={"fields": fields})
        finally:
            request_id.reset(token)

    @staticmethod
    def route(scope) -> str:
        # Route templates preserve endpoint identity without user-supplied paths.
        return getattr(scope.get("route"), "path", "<unmatched>")
