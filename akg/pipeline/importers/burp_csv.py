"""Adaptador de importacion para export CSV del Burp Suite Logger (V0.1-06).

Burp Logger puede exportar a CSV con columnas tipo:
`#`, `Method`, `URL`, `Host`, `IP`, `Path`, `Request`, `Status`,
`Response Length`, `Comment`. Los campos `Request`/`Response` suelen llevar el
mensaje HTTP crudo (a veces base64). Este adaptador reutiliza el parser HTTP
para obtener el modelo canonico RawExchange.
"""

from __future__ import annotations

import base64
import csv
import io
import urllib.parse
import uuid
from datetime import UTC, datetime
from typing import BinaryIO

from akg.pipeline.httpparser import parse_raw_request, parse_raw_response
from akg.schemas import RawExchange, RequestPayload, ResponsePayload

# alias de columnas posibles segun la version del export
_METHOD_COLS = ("Method", "method", "METODO")
_URL_COLS = ("URL", "Url", "url")
_HOST_COLS = ("Host", "host")
_PATH_COLS = ("Path", "path")
_REQ_COLS = ("Request", "request", "req")
_RESP_COLS = ("Response", "response", "res")
_STATUS_COLS = ("Status", "status", "StatusCode")
_TIME_COLS = ("Timestamp", "Time", "time", "Date")


def _col(row: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for c in candidates:
        if c in row and row[c] is not None:
            val = row[c].strip()
            if val:
                return val
    return None


def _maybe_b64decode(text: str) -> str:
    cleaned = text.strip()
    if not cleaned or len(cleaned) < 8 or "\n" in cleaned:
        return text
    try:
        decoded = base64.b64decode(cleaned, validate=True).decode("utf-8", errors="strict")
    except Exception:
        return text
    if decoded.lstrip().startswith(("GET ", "POST ", "PUT ", "DELETE ", "PATCH ", "HEAD ", "OPTIONS ", "HTTP/")):
        return decoded
    return text


def _parse_timestamp(val: str | None) -> datetime:
    if not val:
        return datetime.now(UTC)
    v = val.strip()
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return datetime.now(UTC)


def _coerce_uuid(val: str | None) -> uuid.UUID | None:
    if not val:
        return None
    try:
        return uuid.UUID(val)
    except (ValueError, TypeError, AttributeError):
        return None


class BurpCsvAdapter:
    """Adaptador que lee un export CSV de Burp Logger."""

    format_name = "burp_csv"

    def parse(
        self,
        stream: BinaryIO,
        import_id: str | None = None,
    ) -> tuple[list[RawExchange], list[dict]]:
        import_uuid = _coerce_uuid(import_id)
        text = stream.read().decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))

        exchanges: list[RawExchange] = []
        errors: list[dict] = []
        for idx, row in enumerate(reader):
            method = (_col(row, _METHOD_COLS) or "GET").upper()
            url = _col(row, _URL_COLS) or ""
            host = _col(row, _HOST_COLS) or ""
            path = _col(row, _PATH_COLS) or ""
            req_raw = _col(row, _REQ_COLS)
            resp_raw = _col(row, _RESP_COLS)
            status = _col(row, _STATUS_COLS)
            ts = _parse_timestamp(_col(row, _TIME_COLS))

            if req_raw:
                req_raw = _maybe_b64decode(req_raw)
                try:
                    parsed = parse_raw_request(req_raw)
                except Exception as exc:
                    errors.append({"line": idx, "error": f"request parse: {exc}", "method": method, "url": url})
                    continue
                resolved_host = parsed["host"] or host or _host_from_url(url)
                full_path = parsed.get("full_path", "") or path or _path_from_url(url)
                payload = parsed["payload"] or RequestPayload(headers=[], cookies=[])
                req_method = parsed["method"]
            else:
                resolved_host = host or _host_from_url(url)
                full_path = path or _path_from_url(url)
                payload = RequestPayload(headers=[], cookies=[])
                req_method = method

            resp_payload: ResponsePayload | None = None
            if resp_raw:
                resp_raw = _maybe_b64decode(resp_raw)
                try:
                    resp_payload = parse_raw_response(resp_raw)["payload"]
                except Exception:
                    resp_payload = None

            if resp_payload is None:
                try:
                    resp_payload = ResponsePayload(status_code=int(status) if status and status.isdigit() else 0, headers=[], cookies=[])
                except ValueError:
                    resp_payload = ResponsePayload(status_code=0, headers=[], cookies=[])

            scheme = "https" if "https" in url else "http"
            try:
                exchange = RawExchange(
                    order=idx,
                    timestamp=ts,
                    host=resolved_host,
                    port=443 if scheme == "https" else 80,
                    scheme=scheme,
                    method=req_method,
                    path=full_path,
                    query_string=urllib.parse.urlsplit(url).query or None,
                    request=payload,
                    response=resp_payload,
                )
                if import_uuid is not None:
                    exchange.import_id = import_uuid
                exchanges.append(exchange)
            except Exception as exc:
                errors.append({"line": idx, "error": f"schema: {exc}", "method": method, "url": url})
        return exchanges, errors


def _host_from_url(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).hostname or ""
    except Exception:
        return ""


def _path_from_url(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).path or ""
    except Exception:
        return ""
