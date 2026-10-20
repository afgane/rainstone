"""Bounded operational events, without request values or provider payloads."""

import errno
import json
import logging
import re
import time
import traceback
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from http import HTTPStatus

from rainstone.config import Settings

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def __init__(self, component: str):
        super().__init__()
        self.component = component

    def format(self, record: logging.LogRecord) -> str:
        instant = datetime.fromtimestamp(record.created, UTC)
        event = {
            "timestamp": instant.strftime("%Y-%m-%d %H:%M:%S,") + f"{instant.microsecond // 1000:03d}",
            "level": record.levelname, "component": self.component,
            "event": record.getMessage(), **getattr(record, "fields", {}),
        }
        if request_id.get():
            event["request_id"] = request_id.get()
        if record.exc_info:
            error = record.exc_info[1]
            event.update(error_fields(error))
            # Exception messages and source lines can contain SQL values or secrets.
            event["traceback"] = [
                {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
        return json.dumps(event, default=str)


class AlreadyLogged(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.exc_info and getattr(record.exc_info[1], "_rainstone_logged", False))


def configure_logging(component: str, settings: Settings) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(component))
    handler.addFilter(AlreadyLogged())
    for name in ("rainstone", "uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.setLevel(settings.log_level)
        logger.propagate = False
    # The application emits timed requests and failure events instead.
    logging.getLogger("uvicorn.access").disabled = True


def error_fields(error: Exception) -> dict:
    fields = {"error_type": type(error).__name__}
    if isinstance(error, TimeoutError):
        fields["message"] = "Operation timed out"
    elif isinstance(error, ConnectionError):
        fields["message"] = "Connection failed"
    elif isinstance(error, OSError) and error.errno is not None:
        fields["system_error"] = errno.errorcode.get(error.errno, "UNKNOWN")
    # HTTP status and operation names explain external failures without copying
    # URLs, database statements, response bodies or credentials into logs.
    operation = getattr(error, "operation", None)
    if isinstance(operation, str) and re.fullmatch(r"[A-Za-z0-9_. -]{1,100}", operation):
        fields["operation"] = operation
    code = getattr(error, "code", None)
    if isinstance(code, int):
        fields["http_status"] = code
        try:
            fields["message"] = HTTPStatus(code).phrase
        except ValueError:
            pass
    original = getattr(error, "orig", error)
    sqlstate = getattr(original, "sqlstate", None)
    if isinstance(sqlstate, str) and re.fullmatch(r"[A-Z0-9]{5}", sqlstate):
        fields["sqlstate"] = sqlstate
    cause = getattr(error, "reason", None)
    if isinstance(cause, OSError):
        fields["cause_type"] = type(cause).__name__
        if cause.errno is not None:
            fields["system_errno"] = cause.errno
            fields["system_error"] = errno.errorcode.get(cause.errno, "UNKNOWN")
    return fields


class Failures:
    """Log transitions immediately and summarize unchanged failures periodically."""

    def __init__(self, logger: logging.Logger, repeat_seconds: float, clock: Callable = time.monotonic):
        self.logger, self.repeat_seconds, self.clock = logger, repeat_seconds, clock
        self.states: dict[str, dict] = {}

    def failed(self, key: str, error: Exception, **fields) -> None:
        now = self.clock()
        reason = {**error_fields(error), **{name: fields[name] for name in ("status", "gap_types") if name in fields}}
        previous = self.states.get(key)
        count = previous["count"] + 1 if previous else 1
        if previous is None or previous["reason"] != reason or now - previous["logged"] >= self.repeat_seconds:
            self.logger.warning("operation_failed", extra={"fields": {
                "operation_key": key, **reason, **fields, "consecutive_failures": count,
            }})
            logged = now
        else:
            logged = previous["logged"]
        self.states[key] = {"count": count, "reason": reason, "logged": logged}

    def recovered(self, key: str, **fields) -> None:
        previous = self.states.pop(key, None)
        if previous:
            self.logger.info("operation_recovered", extra={"fields": {
                "operation_key": key, "failures": previous["count"], **fields,
            }})
