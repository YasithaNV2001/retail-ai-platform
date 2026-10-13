import json
import logging

import pytest

from rap_lakehouse.logs import JsonFormatter, mask


def format_line(**extra: object) -> dict:
    record = logging.makeLogRecord({"name": "t", "levelname": "INFO", "msg": "hi %s", "args": (1,)})
    record.__dict__.update(extra)
    return json.loads(JsonFormatter("local-20261013140000").format(record))


def test_line_is_json_with_run_id_and_extras() -> None:
    line = format_line(source="sales", rows=3)
    assert line["run_id"] == "local-20261013140000"
    assert (line["msg"], line["level"], line["logger"]) == ("hi 1", "INFO", "t")
    assert (line["source"], line["rows"]) == ("sales", 3)
    assert line["ts"].endswith("Z")  # UTC


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("DATABRICKS_TOKEN", "dapi123", "***"),
        ("example_api_key", "abc", "***"),
        ("EXAMPLE_SECRET", "s", "***"),
        ("EXAMPLE_URL", "postgresql://user:pw@host/db", "postgresql://***@host/db"),
        ("EXAMPLE_URL", "https://host/db", "https://host/db"),  # no credentials, nothing to hide
        ("source", "sales", "sales"),
    ],
)
def test_mask(key: str, value: str, expected: str) -> None:
    assert mask(key, value) == expected


def test_secrets_are_masked_in_the_line() -> None:
    assert format_line(DATABRICKS_TOKEN="dapi123")["DATABRICKS_TOKEN"] == "***"
