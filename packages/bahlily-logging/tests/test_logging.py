import json

import structlog

from bahlily_logging import configure_logging


def test_configure_logging_emits_structured_json_with_service_and_code(capsys: object) -> None:
    configure_logging(service="test-service")
    logger = structlog.get_logger()

    logger.info("hello", code="TEST_CODE")

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out.strip().splitlines()[-1])

    assert payload["event"] == "hello"
    assert payload["code"] == "TEST_CODE"
    assert payload["service"] == "test-service"
    assert payload["level"] == "info"
    assert "timestamp" in payload


def test_configure_logging_bound_trace_id_appears_in_every_event(capsys: object) -> None:
    configure_logging(service="test-service")
    structlog.contextvars.bind_contextvars(trace_id="0af7651916cd43dd8448eb211c80319c")
    logger = structlog.get_logger()

    logger.info("with trace")

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out.strip().splitlines()[-1])

    assert payload["trace_id"] == "0af7651916cd43dd8448eb211c80319c"
    structlog.contextvars.clear_contextvars()
