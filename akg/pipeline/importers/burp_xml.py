"""Adaptador de importacion para export XML estandar de Burp Suite.

El export clasico de Burp (contexto "Save items") genera un XML con esta
estructura:

    <items>
      <item>
        <time>Mon Aug 03 17:29:09 CST 2026</time>
        <url>https://host/path?a=b</url>
        <host>host</host>
        <port>443</port>
        <protocol>https</protocol>
        <method>POST</method>
        <path>/path</path>
        <extension>json</extension>
        <request base64="true">SGVsbG8=</request>
        <status>200</status>
        <responselength>123</responselength>
        <mimetype></mimetype>
        <response base64="true">SFRUUC8xLjEgMjAw...</response>
        <comment></comment>
      </item>
      ...
    </items>

Se procesa de forma iterativa (`lxml.iterparse`) para soportar archivos de
cientos de megabytes sin cargar el XML completo en memoria: cada `<item>` se
convierte en un `RawExchange` y se libera inmediatamente.

El resultado son objetos `RawExchange` del modelo canonico.
"""

from __future__ import annotations

import base64
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any, BinaryIO

from akg.pipeline.httpparser import parse_raw_request, parse_raw_response
from akg.schemas import RawExchange, RequestPayload, ResponsePayload

ITEM_TAG = "item"

_HTTP_STARTS = (
    "GET ",
    "POST ",
    "PUT ",
    "DELETE ",
    "PATCH ",
    "HEAD ",
    "OPTIONS ",
    "CONNECT ",
    "TRACE ",
    "HTTP/",
    "{",
)


def _maybe_b64decode(text: str) -> str:
    """Decodifica un payload base64 puro si el resultado parece HTTP/JSON."""
    if not text:
        return text
    cleaned = text.strip()
    if len(cleaned) < 8 or "\n" in cleaned:
        return text
    try:
        decoded = base64.b64decode(cleaned, validate=True)
        out = decoded.decode("utf-8", errors="strict")
    except Exception:
        return text
    if out.lstrip().startswith(_HTTP_STARTS):
        return out
    return text


def _coerce_uuid(val: str | None) -> uuid.UUID | None:
    if not val:
        return None
    try:
        return uuid.UUID(val)
    except (ValueError, TypeError, AttributeError):
        return None


def _host_from_url(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).hostname or ""
    except Exception:
        return ""


def _parse_timestamp(val: str | None) -> datetime:
    if not val:
        return datetime.now(UTC)
    candidate = val.strip()
    # Formato de Burp: "Mon Aug 03 14:29:09 CST 2026"
    try:
        return datetime.strptime(candidate, "%a %b %d %H:%M:%S %Z %Y").replace(tzinfo=UTC)
    except ValueError:
        pass
    # ISO 8601 (algunos proxies)
    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)


def _read_item(elem: ET.Element) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for child in elem:
        text = child.text or ""
        if child.get("base64") == "true":
            text = _maybe_b64decode(text)
        item[child.tag] = text
    return item


def _build_exchange(
    order: int,
    item: dict[str, Any],
    errors: list[dict],
) -> RawExchange | None:
    url = item.get("url") or ""
    method = item.get("method")
    scheme = (item.get("protocol") or ("https" if "https" in url else "http")).lower()
    try:
        port = int(item.get("port") or (443 if scheme == "https" else 80))
    except (TypeError, ValueError):
        port = 443 if scheme == "https" else 80
    timestamp = _parse_timestamp(item.get("time"))
    try:
        status_code = int(item.get("status") or 0)
    except (TypeError, ValueError):
        status_code = 0

    req_text = item.get("request")
    resp_text = item.get("response")

    # ── response ─────────────────────────────────────────────
    resp_payload: ResponsePayload | None = None
    if resp_text:
        try:
            resp_payload = parse_raw_response(resp_text)["payload"]
        except Exception:
            resp_payload = None

    # ── request ──────────────────────────────────────────────
    parsed_req: dict[str, Any]
    if req_text:
        try:
            parsed_req = parse_raw_request(req_text)
        except Exception:
            parsed_req = {}
    if not parsed_req:
        parts = urllib.parse.urlsplit(url)
        parsed_req = {
            "method": method or "GET",
            "host": "",
            "full_path": parts.path,
            "query": parts.query or None,
            "payload": None,
        }

    resolved_host = parsed_req.get("host") or item.get("host") or _host_from_url(url) or ""
    if not resolved_host and req_text:
        host_header = _extract_host_header(req_text)
        resolved_host = host_header

    try:
        return RawExchange(
            order=order,
            timestamp=timestamp,
            host=resolved_host,
            port=port,
            scheme=scheme,
            method=parsed_req.get("method") or method or "GET",
            path=parsed_req.get("full_path", ""),
            query_string=parsed_req.get("query"),
            request=parsed_req.get("payload") or RequestPayload(headers=[], cookies=[]),
            response=resp_payload or ResponsePayload(status_code=status_code, headers=[], cookies=[]),
        )
    except Exception as exc:
        errors.append({"line": order, "error": f"schema: {exc}", "method": method, "url": url})
        return None


def _extract_host_header(raw: str) -> str:
    for line in raw.splitlines():
        line = line.strip()
        if line.lower().startswith("host:"):
            return line.split(":", 1)[1].strip()
    return ""


class BurpXmlAdapter:
    """Adaptador que lee un export XML estandar de Burp Suite."""

    format_name = "burp_xml"

    def parse(
        self,
        stream: BinaryIO,
        import_id: str | None = None,
    ) -> tuple[list[RawExchange], list[dict]]:
        import_uuid = _coerce_uuid(import_id)

        exchanges: list[RawExchange] = []
        errors: list[dict] = []

        context = ET.iterparse(stream, events=("end",))
        order = 0
        for _, elem in context:
            if elem.tag != ITEM_TAG:
                continue
            item = _read_item(elem)
            result = _build_exchange(order, item, errors)
            if result is not None:
                if import_uuid is not None:
                    result.import_id = import_uuid
                exchanges.append(result)
            order += 1
            # liberar memoria: el item ya no se necesita
            elem.clear()

        return exchanges, errors


__all__ = ["BurpXmlAdapter"]
