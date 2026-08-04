"""Tests del adaptador de export CSV de Burp Logger (V0.1-06)."""

from __future__ import annotations

import csv
import io

from akg.pipeline.importers import ADAPTER_BY_FORMAT, get_adapter
from akg.pipeline.importers.burp_csv import BurpCsvAdapter

REQ = "GET /api/v1/users?id=5 HTTP/1.1\r\nHost: api.example.com\r\n\r\n"


def _csv_bytes() -> bytes:
    rows = [
        {
            "#": "0",
            "Method": "GET",
            "URL": "https://api.example.com/api/v1/users?id=5",
            "Host": "api.example.com",
            "Path": "/api/v1/users",
            "Request": REQ,
            "Status": "200",
            "Response Length": "120",
        }
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode()


def test_burp_csv_registered() -> None:
    assert "burp_csv" in ADAPTER_BY_FORMAT
    assert isinstance(get_adapter("burp_csv"), BurpCsvAdapter)


def test_burp_csv_parse() -> None:
    exchanges, errors = BurpCsvAdapter().parse(io.BytesIO(_csv_bytes()))
    assert errors == []
    assert len(exchanges) == 1
    ex = exchanges[0]
    assert ex.host == "api.example.com"
    assert ex.method == "GET"
    assert ex.path == "/api/v1/users"
    assert ex.query_string == "id=5"
    assert ex.response.status_code == 200
    assert ex.scheme == "https"


def test_burp_csv_no_request_falls_back_to_url() -> None:
    """Request vacio: el exchange se construye desde URL/metadata (comportamiento leniente)."""
    rows = [
        {
            "#": "0",
            "Method": "GET",
            "URL": "https://x.test/a?q=1",
            "Host": "x.test",
            "Path": "/a",
            "Request": "",
            "Status": "200",
            "Response Length": "10",
        }
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    exchanges, errors = BurpCsvAdapter().parse(io.BytesIO(buf.getvalue().encode()))
    assert errors == []
    assert len(exchanges) == 1
    ex = exchanges[0]
    assert ex.host == "x.test"
    assert ex.path == "/a"
    assert ex.query_string == "q=1"
