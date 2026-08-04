"""Extraccion de entidades (etapa 3 del pipeline, SAD cap. 4.4 y 15.3).

Detecta y canoniza entidades de seguridad relevantes a partir de un exchange:

  * `jwt`: tokens JWT (estructura + claims descodificados).
  * `cookie_session`: cookies de sesion detectadas en request/response.
  * `api_key`: claves de API en headers (x-api-key, x-auth-token).
  * `json_id`: identificadores extraidos de cuerpos JSON con paths canonicos.
  * `role` / `scope`: roles y scopes declarados en claims de JWT.

Cada ocurrencia se normaliza (valor limpio), se hashea con SHA-256 estable y se
etiqueta como sensible. Los valores sinteticos de baja entropia se descartan.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from akg.schemas import EntityOccurrenceSchema, NormalizedExchange, RawExchange

# ── tipos de entidad ───────────────────────────────────────────────────────────

ENTITY_JWT = "jwt"
ENTITY_COOKIE_SESSION = "cookie_session"
ENTITY_API_KEY = "api_key"
ENTITY_JSON_ID = "json_id"
ENTITY_ROLE = "role"
ENTITY_SCOPE = "scope"

ENTITY_TYPES = (ENTITY_JWT, ENTITY_COOKIE_SESSION, ENTITY_API_KEY, ENTITY_JSON_ID, ENTITY_ROLE, ENTITY_SCOPE)

# ── sesiones y auth ────────────────────────────────────────────────────────────

_SESSION_COOKIE_NAMES = ("session", "sessionid", "jsessionid", "phpsessid", "auth", "sid", "jwtid")

_API_KEY_HEADERS = ("x-api-key", "x-auth-token", "proxy-authorization")

_AUTH_HEADERS = ("authorization", "authorisation")

_JWT_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")

_ROLE_KEYS = {"role", "roles", "permission", "permissions"}
_SCOPE_KEYS = {"scope", "scopes"}

# ── ids canonicos en JSON (V0.1-14) ───────────────────────────────────────────

_ID_KEY_RE = re.compile(r"^(id|uid|uuid|guid)$|^[a-z0-9]+[-_.]id$", re.IGNORECASE)

# ── baja entropia (V0.1-18) ────────────────────────────────────────────────────

_LOW_ENTROPY_VALUES = {
    "",
    "0",
    "1",
    "2",
    "3",
    "null",
    "none",
    "true",
    "false",
    "test",
    "demo",
    "sample",
    "example",
    "admin",
    "unknown",
}


def stable_hash(value: str) -> str:
    """Hash SHA-256 estable del valor normalizado."""
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def is_low_entropy(value: str | None) -> bool:
    """True para valores sinteticos o demasiado cortos como para ser un id real."""
    if value is None:
        return True
    v = value.strip()
    if v.lower() in _LOW_ENTROPY_VALUES:
        return True
    if len(v) < 3:
        return True
    return False


def decode_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Descodifica un JWT (header + claims) sin verificar firma. None si no es JWT."""
    if not _JWT_RE.match(token.strip()):
        return None
    try:
        header_part, payload_part, _ = token.split(".")
        header = json.loads(_b64decode(header_part))
        payload = json.loads(_b64decode(payload_part))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(header, dict) or not isinstance(payload, dict):
        return None
    return header, payload


def _b64decode(part: str) -> bytes:
    padding = "=" * (-len(part) % 4)
    return base64.urlsafe_b64decode(part + padding)


# ── claims (roles/scopes) ──────────────────────────────────────────────────────


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, (str, int)):
        return [str(value)]
    return []


def _scopes_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [v for v in value.split() if v]
    return []


def claims_entities(payload: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Renditella (tipo, valor) para roles y scopes declarados en los claims."""
    for key, value in payload.items():
        lk = key.lower()
        if lk in _ROLE_KEYS:
            for v in _as_list(value):
                yield ENTITY_ROLE, v
        elif lk in _SCOPE_KEYS:
            for v in _scopes_list(value):
                yield ENTITY_SCOPE, v


# ── ids canonicos en JSON ──────────────────────────────────────────────────────


def json_ids(data: Any, prefix: str = "", _path: str = "") -> Iterator[tuple[str, str]]:
    """Renditella (path_canonico, valor) de ids en un documento JSON.

    Recorre el JSON con un prefijo de ruta canonico (p.ej. `data.contact.id`) y
    emite las claves que parecen identificadores con su valor escalar.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            key_path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                yield from json_ids(value, key_path, _path)
            elif _is_id_key(key) and not is_low_entropy(str(value)):
                yield key_path, str(value)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            yield from json_ids(item, prefix, f"{_path}[{i}]")


def _is_id_key(key: str) -> bool:
    low = key.lower()
    if low in ("id", "uid", "uuid", "guid") or low.endswith("_id") or low.endswith("-id"):
        return True
    return bool(re.fullmatch(r"[a-z0-9]+[Ii][Dd]", key))


# ── construccion de ocurrencias ────────────────────────────────────────────────


def extract_entities(
    exchange: RawExchange,
    *,
    import_id: uuid.UUID | None = None,
) -> list[EntityOccurrenceSchema]:
    """Extrae todas las entidades detectables de un exchange."""
    ts = exchange.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    out: list[EntityOccurrenceSchema] = []
    exchange_id = exchange.exchange_id

    # ── headers de request ──────────────────────────────────────────────
    for h in exchange.request.headers:
        low = h.name.lower()
        value = h.value or ""
        if low in _AUTH_HEADERS:
            _handle_auth_header(out, exchange_id, import_id, ts, h.name, value, "request.header")
        elif low in _API_KEY_HEADERS and value:
            out.append(
                _occ(
                    exchange_id,
                    import_id,
                    ENTITY_API_KEY,
                    h.name,
                    value,
                    "request.header",
                    ts,
                    sensitive=True,
                )
            )

    # ── cookies de request ──────────────────────────────────────────────
    for c in exchange.request.cookies:
        if _is_session_cookie(c.name):
            out.append(
                _occ(
                    exchange_id,
                    import_id,
                    ENTITY_COOKIE_SESSION,
                    c.name,
                    c.value,
                    "request.cookie",
                    ts,
                    sensitive=True,
                )
            )
    for c in exchange.response.cookies:
        if _is_session_cookie(c.name):
            out.append(
                _occ(
                    exchange_id,
                    import_id,
                    ENTITY_COOKIE_SESSION,
                    c.name,
                    c.value,
                    "response.cookie",
                    ts,
                    sensitive=True,
                )
            )

    # ── cuerpos JSON ────────────────────────────────────────────────────
    if exchange.request.body and exchange.request.body.data:
        for path, value in json_ids(exchange.request.body.data):
            out.append(
                _occ(
                    exchange_id, import_id, ENTITY_JSON_ID, None, value, "request.body", ts,
                    sensitive=False, path=path,
                )
            )
    if exchange.response.body and exchange.response.body.data:
        for path, value in json_ids(exchange.response.body.data):
            out.append(
                _occ(
                    exchange_id, import_id, ENTITY_JSON_ID, None, value, "response.body", ts,
                    sensitive=False, path=path,
                )
            )

    # ── ids de path (parametros normalizados) ───────────────────────────
    for name, value in (exchange.path_params or {}).items():
        if is_low_entropy(value):
            continue
        out.append(
            _occ(
                exchange_id,
                import_id,
                ENTITY_JSON_ID,
                name,
                value,
                "path",
                ts,
                sensitive=False,
                path=f"path.{name}",
            )
        )

    return out


def _handle_auth_header(
    out: list[EntityOccurrenceSchema],
    exchange_id: uuid.UUID,
    import_id: uuid.UUID | None,
    ts: datetime,
    name: str,
    value: str,
    location: str,
) -> None:
    stripped = value.strip()
    token = stripped
    if " " in stripped:
        scheme, _, rest = stripped.partition(" ")
        if scheme.upper() in {"BEARER", "JWT", "TOKEN"} and rest:
            token = rest
    decoded = decode_jwt(token)
    if decoded is not None:
        header, payload = decoded
        out.append(
            _occ(
                exchange_id,
                import_id,
                ENTITY_JWT,
                name,
                token,
                location,
                ts,
                sensitive=True,
            )
        )
        for ent_type, ent_value in claims_entities(payload):
            out.append(
                _occ(
                    exchange_id,
                    import_id,
                    ent_type,
                    ent_value,
                    ent_value,
                    location,
                    ts,
                    sensitive=False,
                )
            )
    elif stripped and not is_low_entropy(token):
        out.append(
            _occ(exchange_id, import_id, ENTITY_API_KEY, name, token, location, ts, sensitive=True)
        )


def _is_session_cookie(name: str) -> bool:
    return name.lower().replace("_", "").replace("-", "") in _SESSION_COOKIE_NAMES


def _occ(
    exchange_id: uuid.UUID,
    import_id: uuid.UUID | None,
    entity_type: str,
    entity_label: str | None,
    value: str,
    location: str,
    ts: datetime,
    *,
    sensitive: bool,
    path: str | None = None,
) -> EntityOccurrenceSchema:
    return EntityOccurrenceSchema(
        import_id=import_id,
        exchange_id=exchange_id,
        entity_type=entity_type,
        entity_label=entity_label,
        value=value,
        value_hash=stable_hash(value),
        path=path,
        location=location,
        sensitive=sensitive,
        timestamp=ts,
    )


def extract_from_exchanges(
    exchanges: list[NormalizedExchange],
    *,
    import_id: uuid.UUID,
) -> list[tuple[uuid.UUID, EntityOccurrenceSchema]]:
    """Extrae entidades de una lista de exchanges normalizados.

    Devuelve pares (exchange_id canonico, ocurrencia) para persistencia.
    """
    result: list[tuple[uuid.UUID, EntityOccurrenceSchema]] = []
    for ex in exchanges:
        for occ in extract_entities(ex, import_id=import_id):
            result.append((ex.exchange_id, occ))
    return result


__all__ = [
    "ENTITY_API_KEY",
    "ENTITY_COOKIE_SESSION",
    "ENTITY_JSON_ID",
    "ENTITY_JWT",
    "ENTITY_ROLE",
    "ENTITY_SCOPE",
    "claims_entities",
    "decode_jwt",
    "extract_entities",
    "extract_from_exchanges",
    "is_low_entropy",
    "json_ids",
    "stable_hash",
]
