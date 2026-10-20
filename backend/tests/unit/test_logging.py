import io
import json
import logging
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from rainstone.config import Settings
from rainstone.logging import AlreadyLogged, Failures, JsonFormatter, configure_logging, error_fields
from rainstone.request_logging import RequestLogging
from sqlalchemy.exc import StatementError


def test_timestamp_and_traceback_do_not_copy_exception_values_or_source_lines():
    try:
        raise StatementError("private value", "select secret", {"password": "hidden"}, ValueError("secret"))
    except StatementError:
        import sys
        record = logging.LogRecord("rainstone", logging.ERROR, __file__, 1, "request_failed", (), sys.exc_info())
    record.created = datetime(2026, 10, 20, 13, 14, 47, 855000, tzinfo=UTC).timestamp()
    output = JsonFormatter("web").format(record)
    event = json.loads(output)
    assert event["timestamp"] == "2026-10-20 13:14:47,855"
    assert event["traceback"][0]["function"] == "test_timestamp_and_traceback_do_not_copy_exception_values_or_source_lines"
    assert event["error_type"] == "StatementError"
    assert all(value not in output for value in ("private value", "select secret", "password", "hidden"))


def test_failures_are_coalesced_and_recovery_is_logged_once():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter("collector"))
    logger = logging.Logger("test", level=logging.DEBUG)
    logger.addHandler(handler)
    now = [0]
    failures = Failures(logger, 300, lambda: now[0])
    for _ in range(100):
        failures.failed("galaxy_db", TimeoutError("private URL"))
    assert len(stream.getvalue().splitlines()) == 1
    now[0] = 300
    failures.failed("galaxy_db", TimeoutError("private URL"))
    failures.failed("galaxy_db", ConnectionError("credentials"))
    failures.recovered("galaxy_db")
    failures.recovered("galaxy_db")
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [event["event"] for event in events] == ["operation_failed"] * 3 + ["operation_recovered"]
    assert events[1]["consecutive_failures"] == 101
    assert "private URL" not in stream.getvalue()
    assert "credentials" not in stream.getvalue()
    assert error_fields(TimeoutError())["message"] == "Operation timed out"


def test_configuring_logging_makes_info_visible_without_duplicate_handlers(capsys):
    loggers = [logging.getLogger(name) for name in ("rainstone", "uvicorn", "uvicorn.error", "uvicorn.access")]
    original = [(logger.handlers[:], logger.level, logger.propagate, logger.disabled) for logger in loggers]
    try:
        settings = Settings(auth_mode="development", demo_data=True)
        configure_logging("collector", settings)
        configure_logging("collector", settings)
        logging.getLogger("rainstone.collector").info("collector_started")
        logging.getLogger("rainstone.collector").debug("hidden")
        events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
        assert len(events) == 1
        assert events[0]["component"] == "collector"
        assert events[0]["event"] == "collector_started"
        assert logging.getLogger("uvicorn.access").disabled
    finally:
        for logger, (handlers, level, propagate, disabled) in zip(loggers, original, strict=True):
            logger.handlers, logger.level, logger.propagate, logger.disabled = handlers, level, propagate, disabled


def application(clock=None):
    app = FastAPI()
    app.add_middleware(RequestLogging, slow_seconds=2, **({"clock": clock} if clock else {}))
    status = [200]

    @app.get("/api/ready")
    def ready():
        return JSONResponse({}, status_code=status[0])

    @app.get("/api/health")
    @app.get("/api/freshness")
    def health():
        return {}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return {}

    @app.get("/api/fail")
    def fail():
        raise ValueError("private error contents")

    return app, status


def test_request_logs_hide_paths_queries_and_successful_polling(caplog, monkeypatch):
    logger = logging.getLogger("rainstone.web")
    monkeypatch.setattr(logger, "propagate", False)
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="rainstone.web"):
            app, status = application()
            with TestClient(app, raise_server_exceptions=False) as client:
                for _ in range(10):
                    for path in ("ready", "health", "freshness"):
                        assert client.get(f"/api/{path}").status_code == 200
                assert not caplog.records
                response = client.get("/api/jobs/private-job?search=private-search")
                assert response.headers["x-request-id"]
                record = caplog.records[-1]
                assert record.fields["route"] == "/api/jobs/{job_id}"
                assert "private" not in str(record.fields)
                status[0] = 503
                client.get("/api/ready")
                client.get("/api/ready")
                status[0] = 200
                client.get("/api/ready")
                assert [record.getMessage() for record in caplog.records] == [
                    "request_completed", "probe_failed", "probe_recovered",
                ]
                response = client.get("/api/fail")
                assert response.status_code == 500
                assert response.headers["x-request-id"]
                error = caplog.records[-1]
                assert error.getMessage() == "request_failed"
                assert error.exc_info
                assert not AlreadyLogged().filter(error)
                assert "private error contents" not in JsonFormatter("web").format(error)
    finally:
        logger.removeHandler(caplog.handler)


def test_slow_successful_report_requests_are_warnings(caplog, monkeypatch):
    logger = logging.getLogger("rainstone.web")
    monkeypatch.setattr(logger, "propagate", False)
    logger.addHandler(caplog.handler)
    try:
        app, _ = application(clock=iter([0, 2.5]).__next__)
        with TestClient(app) as client:
            client.get("/api/jobs/123")
        record = caplog.records[-1]
        assert record.levelno == logging.WARNING
        assert record.fields["duration_ms"] == 2500
    finally:
        logger.removeHandler(caplog.handler)
