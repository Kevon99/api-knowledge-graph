"""Tests del adaptador de XML de Burp Suite (export clasico con base64)."""

from __future__ import annotations

import base64
import io

from akg.pipeline.importers.burp_xml import BurpXmlAdapter


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _build_xml(items: list[tuple]) -> bytes:
    body_parts = ["""
<items>
"""]
    for req, resp, method, path, url, host in items:
        body_parts.append(f"""
  <item>
    <time>Mon Aug 03 17:29:09 CST 2026</time>
    <url>{url}</url>
    <host>{host}</host>
    <port>443</port>
    <protocol>https</protocol>
    <method>{method}</method>
    <path>{path}</path>
    <extension>json</extension>
    <request base64="true">{_b64(req)}</request>
    <status>200</status>
    <responselength>{len(resp)}</responselength>
    <mimetype>application/json</mimetype>
    <response base64="true">{_b64(resp)}</response>
    <comment></comment>
  </item>
"""
        )
    body_parts.append("</items>")
    return "".join(body_parts).encode("utf-8")


REQ = "GET /api/config HTTP/1.1\r\nHost: admin.example.com\r\nAuthorization: Bearer abc123\r\n\r\n"
RESP = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"id\":42}"


class TestBurpXmlAdapter:
    def test_parses_single_item(self) -> None:
        xml = _build_xml([(REQ, RESP, "GET", "/api/config", "https://admin.example.com/api/config", "admin.example.com")])
        adapter = BurpXmlAdapter()
        exchanges, errors = adapter.parse(io.BytesIO(xml))

        assert len(exchanges) == 1
        assert errors == []
        ex = exchanges[0]
        assert ex.method == "GET"
        assert ex.host == "admin.example.com"
        assert ex.path == "/api/config"
        assert ex.scheme == "https"
        assert ex.port == 443
        assert ex.response.status_code == 200
        assert ex.request.has_json is False
        assert ex.response.has_json is True
        assert ex.response.body is not None
        assert ex.response.body.data == {"id": 42}

    def test_base64_requests_decoded(self) -> None:
        xml = _build_xml([(REQ, RESP, "GET", "/api/config", "https://admin.example.com/api/config", "admin.example.com")])
        adapter = BurpXmlAdapter()
        exchanges, _ = adapter.parse(io.BytesIO(xml))
        assert [h.name for h in exchanges[0].request.headers] == ["host", "authorization"]

    def test_empty_response_still_builds_exchange(self) -> None:
        xml = _build_xml([(REQ, "", "GET", "/api/config", "https://admin.example.com/api/config", "admin.example.com")])
        adapter = BurpXmlAdapter()
        exchanges, errors = adapter.parse(io.BytesIO(xml))
        assert len(exchanges) == 1
        assert exchanges[0].response.status_code == 200  # status viene del metadata XML
        assert errors == []

    def test_timestamp_parsing(self) -> None:
        xml = _build_xml([(REQ, RESP, "GET", "/api/config", "https://admin.example.com/api/config", "admin.example.com")])
        adapter = BurpXmlAdapter()
        exchanges, _ = adapter.parse(io.BytesIO(xml))
        assert exchanges[0].timestamp.year == 2026
        assert exchanges[0].timestamp.month == 8
        assert exchanges[0].timestamp.day == 3


def test_module_level_import_id() -> None:
    xml = _build_xml([(REQ, RESP, "GET", "/api/config", "https://admin.example.com/api/config", "admin.example.com")])
    adapter = BurpXmlAdapter()
    exchanges, _ = adapter.parse(io.BytesIO(xml), import_id="123e4567-e89b-12d3-a456-426614174000")
    assert str(exchanges[0].import_id) == "123e4567-e89b-12d3-a456-426614174000"
