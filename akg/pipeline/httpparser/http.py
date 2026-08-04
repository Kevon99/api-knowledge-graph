"""Parsing de mensajes HTTP crudos (request/response) a estructuras canonicas.

El adaptador de Burp exporta request y response como strings crudos (con forma
HTTP/1.x). Este modulo los convierte en las estructuras Pydantic del modelo
canonico (Header, Cookie, RequestPayload, ResponsePayload).
"""

from __future__ import annotations

import json
from typing import Any

from akg.schemas import BodyPayload, Cookie, Header, RequestPayload, ResponsePayload


def _split_head_and_body(raw: str) -> tuple[list[str], str]:
    """Divide un mensaje HTTP crudo en (lineas_de_cabecera, cuerpo)."""
    if "\r\n\r\n" in raw:
        head, body = raw.split("\r\n\r\n", 1)
        return head.split("\r\n"), body
    if "\n\n" in raw:
        head, body = raw.split("\n\n", 1)
        return head.split("\n"), body
    return raw.split("\n"), ""


def _parse_header_lines(lines: list[str]) -> list[Header]:
    headers: list[Header] = []
    for line in lines:
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        headers.append(Header(name=name.strip().lower(), value=value.strip()))
    return headers


def _try_json_body(body: str, content_type: str | None) -> tuple[dict | None, bool, str | None]:
    if not body.strip():
        return None, False, None
    is_json = (
        content_type is not None
        and ("json" in content_type.lower() or "javascript" in content_type.lower())
        or body.lstrip().startswith(("{", "["))
    )
    if is_json:
        try:
            obj = json.loads(body)
            return obj, True, None
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, False, None
    return None, False, None


def parse_raw_request(raw: str) -> dict[str, Any]:
    """Convierte un request HTTP crudo en un diccionario canonico.

    Devuelve: { method, path, query_string, host, headers, cookies, body,
                req_payload }.
    """
    lines = raw.splitlines()
    if not lines:
        raise ValueError("empty request")

    request_line = lines[0].rstrip("\r")
    parts = request_line.split(" ")
    if len(parts) < 2:
        raise ValueError(f"malformed request-line: {request_line!r}")
    method = parts[0]
    target = parts[1]

    # separar host de path en el target
    full_path = target
    query_string = None
    if "?" in target:
        full_path, query_string = target.split("?", 1)

    head_lines, body_text = _split_head_and_body("\n".join(lines[1:]))
    headers = _parse_header_lines(head_lines)

    # encontrar host
    host = ""
    for h in headers:
        if h.name == "host":
            host = h.value
            break

    # cookies de request
    cookies: list[Cookie] = []
    for h in headers:
        if h.name == "cookie":
            for part in h.value.split(";"):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    cookies.append(Cookie(name=k.strip(), value=v.strip()))
                elif part:
                    cookies.append(Cookie(name=part, value=""))

    content_type = None
    for h in headers:
        if h.name == "content-type":
            content_type = h.value
            break

    data, has_json, _ = _try_json_body(body_text, content_type)

    body = BodyPayload(data=data, text=None if has_json else body_text, content_type=content_type)

    payload = RequestPayload(
        headers=headers,
        cookies=cookies,
        query_params={},
        body=body,
        has_json=has_json,
    )
    return {
        "method": method,
        "host": host,
        "full_path": full_path,
        "query": query_string,
        "payload": payload,
    }


def parse_raw_response(raw: str) -> dict[str, Any]:
    """Convierte una respuesta HTTP cruda en un diccionario canonico.

    Devuelve: { status_code, status_text, headers, cookies, payload }.
    """
    lines = raw.splitlines()
    if not lines:
        raise ValueError("empty response")

    status_line = lines[0].strip("\r")
    status_code: int = 0
    status_text: str | None = None
    # "HTTP/1.1 200 OK"
    parts = status_line.split(" ", 2)
    if len(parts) >= 2:
        try:
            status_code = int(parts[1])
        except ValueError:
            status_code = 0
    if len(parts) >= 3:
        status_text = parts[2]

    head_lines, body_text = _split_head_and_body("\n".join(lines[1:]))
    headers = _parse_header_lines(head_lines)

    cookies: list[Cookie] = []
    for h in headers:
        if h.name == "set-cookie":
            name = ""
            value = ""
            attributes: dict[str, str] = {}
            first_cookie_part = h.value
            if ";" in first_cookie_part:
                first_cookie_part = first_cookie_part.split(";", 1)[0]
            if "=" in first_cookie_part:
                name, value = first_cookie_part.split("=", 1)
            for attr in h.value.split(";"):
                attr = attr.strip()
                if not attr or attr == first_cookie_part or "=" not in attr:
                    if attr and attr not in (name, first_cookie_part):
                        attributes[attr] = ""
                    continue
                k, v = attr.split("=", 1)
                attributes[k.strip()] = v.strip()
            cookies.append(Cookie(name=name.strip(), value=value, attributes=attributes))
        elif h.name == "cookie":
            for part in h.value.split(";"):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    cookies.append(Cookie(name=k.strip(), value=v.strip()))
                elif part:
                    cookies.append(Cookie(name=part, value=""))

    content_type = None
    for h in headers:
        if h.name == "content-type":
            content_type = h.value
            break

    data, has_json, _ = _try_json_body(body_text, content_type)
    response_body: BodyPayload | None = None
    if body_text:
        response_body = BodyPayload(
            data=data if has_json else None,
            text=None if has_json else body_text,
            content_type=content_type,
        )
    payload = ResponsePayload(
        status_code=status_code,
        status_text=status_text,
        headers=headers,
        cookies=cookies,
        body=response_body,
        has_json=has_json,
    )
    return {
        "status_code": status_code,
        "status_text": status_text,
        "payload": payload,
    }
