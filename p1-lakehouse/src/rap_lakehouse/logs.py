"""Structured logging: one JSON object per line, each carrying the run_id.

The run_id travels everywhere (System design §6). Fields passed with extra={...} become JSON
keys. Keys ending in _KEY, _TOKEN or _SECRET are masked, and so are credentials inside values of
keys ending in _URL (System design §12).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET")
URL_CREDENTIALS = re.compile(r"(?<=://)[^/@\s]+@")
# Attributes every LogRecord has; anything else on a record came from extra={...}.
RECORD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def mask(key: str, value: object) -> object:
    name = key.upper()
    if name.endswith(SECRET_SUFFIXES):
        return "***"
    if name.endswith("_URL") and isinstance(value, str):
        return URL_CREDENTIALS.sub("***@", value)
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")
        line: dict[str, object] = {
            "ts": ts.replace("+00:00", "Z"),  # §6 JSON timestamps: UTC with a Z
            "level": record.levelname,
            "logger": record.name,
            "run_id": self.run_id,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in RECORD_ATTRS:
                line[key] = mask(key, value)
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def setup_logging(run_id: str, level: int = logging.INFO) -> None:
    """Send every logger's records to stderr as JSON lines. Call once, at the script's start."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(run_id))
    logging.basicConfig(level=level, handlers=[handler], force=True)
