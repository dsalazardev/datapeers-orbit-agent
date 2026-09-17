"""Structured JSON logging with request correlation (ORB-NFR-015, ORB-FR-019).

Uses only the standard library: a minimal JSON formatter plus a context variable
carrying the request id set by the HTTP middleware. Log records may include
`request_id`, `onboarding_id` and `reason_code`; secrets and credentials are
never logged (ORB-NFR-005).
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": getattr(record, "request_id", None)
            or request_id_var.get(),
        }
        for field_name in ("onboarding_id", "reason_code"):
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_HANDLER_FLAG = "_orbit_json_handler"


def setup_logging(level: str) -> None:
    """Attach a JSON handler to the root logger without clobbering existing ones.

    Idempotent across repeated ``create_app`` calls, and other handlers (host
    application handlers, pytest's caplog, ...) are preserved so tests and
    embedders keep their capture pipeline.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())
    if any(getattr(handler, _HANDLER_FLAG, False) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    setattr(handler, _HANDLER_FLAG, True)
    root.addHandler(handler)
