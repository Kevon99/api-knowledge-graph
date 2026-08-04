"""Adaptador de importacion para export de Burp Suite Logger.

Soporta los formatos mas comunes del export del Logger de Burp:
  - Entradas con `request`/`response` como strings raw HTTP.
  - Entradas con `request`/`response` como objetos que contienen `text`/`raw`.
  - Encoding base64 para mensajes crudos.
  - Metadatos a nivel superior: host, url, method, status, time.

El resultado son objetos `RawExchange` del modelo canonico.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
import uuid
from datetime import UTC, datetime
from typing import Any, BinaryIO

from akg.pipeline.httpparser import parse_raw_request, parse_raw_response
from akg.schemas import RawExchange, RequestPayload, ResponsePayload

# Str cases 'GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|CONNECT|TRACE'


def _maybe_b64decode(text: str) -> str:
    """Detecta y decodifica un payload codificado en base64 si procede."""
    if not text:
        return text
    cleaned = text.strip()
    if len(cleaned) < 8:
        return text
    # Si contiene saltos de linea y espacios tipo HTTP, no es b64 puro
    if "\n" in cleaned:
        return text
    try:
        decoded = base64.b64decode(cleaned, validate=True)
        out = decoded.decode("utf-8", errors="strict")
    except Exception:
        return text
    stripped = out.lstrip()
    if stripped.startswith(
        (
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
    ):
        return out
    return text


def _find_list(data: Any) -> list[Any] | None:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("entries", "items", "logs", "events", "requests", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        # puede ser { "results": [...], "pagination": {...} }
        for v in data.values():
            if isinstance(v, list):
                return v
    return None


def _extract_field(entry: dict, *names: str) -> Any:
    for n in names:
        if n in entry:
            return entry[n]
        if isinstance(entry.get("request"), dict):
            pass
    # buscar en subobjetos request/response
    for wrapper in ("request", "response", "req", "res"):
        if isinstance(entry.get(wrapper), dict):
            for n in names:
                if n in entry[wrapper]:
                    return entry[wrapper][n]
    return None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        for k in ("text", "raw", "payload", "content", "base64"):
            if k in value:
                v = value[k]
                if k == "base64":
                    return _maybe_b64decode(v) if isinstance(v, str) else v
                if isinstance(v, dict):
                    inner = _as_text(v)
                    if inner is not None:
                        return inner
                elif v is not None:
                    if isinstance(v, str):
                        if k in ("raw", "payload", "content") and value.get("_encoding") in (
                            None,
                            "",
                            "base64",
                        ):
                            return _maybe_b64decode(v)
                        if value.get("_encoding") == "base64":
                            return _maybe_b64decode(v)
                        return v
                    return str(v)
        return None
    return str(value)


def _parse_timestamp(val: Any) -> datetime:
    if val is None:
        return datetime.now(UTC)
    if isinstance(val, (int, float)):
        f = float(val)
        if f > 10_000_000_000:
            f = f / 1000.0
        return datetime.fromtimestamp(f, tz=UTC)
    # intentar parsear ISO
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)


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


def _parse_entry(
    entry: Any,
    order: int,
    errors: list[dict],
) -> RawExchange | None:
    if not isinstance(entry, dict):
        return None

    request_raw = _extract_field(entry, "request", "req")
    response_raw = _extract_field(entry, "response", "res")
    method = _extract_field(entry, "method")
    url = _extract_field(entry, "url", "path")
    host_field = _extract_field(entry, "host")
    ts = _extract_field(entry, "time", "timestamp", "timeMs")

    req_text = _as_text(request_raw) if request_raw is not None else None
    resp_text = _as_text(response_raw) if response_raw is not None else None

    resp_payload: ResponsePayload | None = None
    if resp_text:
        try:
            parsed_resp = parse_raw_response(resp_text)
            resp_payload = parsed_resp["payload"]
        except Exception:
            resp_payload = None

    parsed_req = None
    if req_text:
        try:
            parsed_req = parse_raw_request(req_text)
        except Exception as exc:
            errors.append(
                {"line": order, "error": f"request parse: {exc}", "method": method, "url": url}
            )
            return None
    else:
        # entrada sin request crudo: construimos solo con url/metadata
        path_q = urllib.parse.urlsplit(url or "").path
        query_s = urllib.parse.urlsplit(url or "").query or None
        parsed_req = {
            "method": method or "GET",
            "host": "",
            "full_path": path_q,
            "query": query_s,
            "payload": None,
        }

    resolved_host = parsed_req["host"] or host_field or _host_from_url(url or "")
    scheme = "https" if "https" in (url or "") else "http"
    timestamp = _parse_timestamp(ts)

    try:
        exchange = RawExchange(
            order=order,
            timestamp=timestamp,
            host=resolved_host,
            port=443 if scheme == "https" else 80,
            scheme=scheme,
            method=parsed_req["method"],
            path=parsed_req.get("full_path", ""),
            query_string=parsed_req.get("query"),
            request=parsed_req["payload"] or RequestPayload(headers=[], cookies=[]),
            response=resp_payload or ResponsePayload(status_code=0, headers=[], cookies=[]),
        )
        return exchange
    except Exception as exc:
        errors.append({"line": order, "error": f"schema: {exc}", "method": method, "url": url})
        return None


class BurpJsonAdapter:
    """Adaptador que lee un export JSON de Burp Logger."""

    format_name = "burp_json"

    def parse(
        self,
        stream: BinaryIO,
        import_id: str | None = None,
    ) -> tuple[list[RawExchange], list[dict]]:
        import_uuid = _coerce_uuid(import_id)
        try:
            data = json.load(stream)
        except json.JSONDecodeError as exc:
            raise ValueError(f"no es JSON de Burp Logger valido: {exc}") from exc

        entries = _find_list(data)
        if entries is None:
            raise ValueError("formato no reconocido: no se encontro lista de eventos")

        exchanges: list[RawExchange] = []
        errors: list[dict] = []
        for idx, entry in enumerate(entries):
            result = _parse_entry(entry, idx, errors)
            if result is not None:
                if import_uuid is not None:
                    result.import_id = import_uuid
                exchanges.append(result)
        return exchanges, errors
