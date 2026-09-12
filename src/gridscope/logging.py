"""Small JSON formatter for safe application events; no request bodies or headers."""

import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for key in ("attempt", "status", "error_code"):
            if key in record.__dict__:
                event[key] = record.__dict__[key]
        return json.dumps(event)


def configure_logging() -> None:
    logger = logging.getLogger("gridscope")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
