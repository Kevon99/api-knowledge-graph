"""Normalizacion: de RawExchange a NormalizedExchange.

Etapa 2 del pipeline (SAD capitulo 7). Convierte los datos brutos en un
modelo canonico enriquecido:
  - `template`: plantilla de path (p.ej. `/api/v1/users/{id}`) derivada de
    segmentos dinamicos detectados por heuristica.
  - `path_params`: mapeo de placeholder -> valor extraido del path real.
  - `detect_secrets`: marca headers/cookies/cuerpos que parecen credenciales.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from akg.schemas import NormalizedExchange, RawExchange

_DYNAMIC_SEGMENT = re.compile(
    r"(?:0x[0-9a-fA-F]+)|"
    r"(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})|"
    r"(?:[0-9a-fA-F]{16,})|"
    r"\d+"
)

_PARAM_HINTS = {"id", "uid", "user", "userid", "orderid", "page", "slug"}

# Segmentos que nunca se templatizan (SAD 4.3.3, V0.1-10)
DEFAULT_PROTECTED_SEGMENTS = frozenset(
    {"api", "v1", "v2", "v3", "admin", "health", "auth", "oauth", "public"}
)


@dataclass
class NormalizeConfig:
    """Configuracion de normalizacion (V0.1-10): umbral de cardinalidad + segmentos protegidos."""

    cardinality_threshold: int = 0
    protected_segments: frozenset[str] = field(default_factory=lambda: DEFAULT_PROTECTED_SEGMENTS)


def _segment_is_param(seg: str) -> bool:
    if not seg:
        return False
    if seg.lower() in DEFAULT_PROTECTED_SEGMENTS:
        return False
    if re.fullmatch(r"\{[^}]+\}", seg):
        return True
    if _DYNAMIC_SEGMENT.fullmatch(seg):
        return True
    return seg.lower() in _PARAM_HINTS


def _param_name(seg: str) -> str:
    """Nombre de placeholder: '{uuid}' para UUIDs, '{int}' para numeros, del hint en otro caso."""
    if re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", seg
    ):
        return "uuid"
    if re.fullmatch(r"0x[0-9a-fA-F]+", seg):
        return "hex"
    if re.fullmatch(r"\[\d+\]", seg):
        return "array_index"
    if seg.isdigit():
        return "int"
    if seg.lower() in _PARAM_HINTS:
        return seg.lower()
    if re.fullmatch(r"\{[^}]+\}", seg):
        return seg[1:-1]
    return seg


def build_template(path: str, protected_segments: frozenset[str] = DEFAULT_PROTECTED_SEGMENTS) -> str:
    """Convierte un path real en un template con `{param}` en segmentos dinamicos.

    Los segmentos en `protected_segments` (p.ej. `api`, `v1`) nunca se templatizan.
    """
    if not path or path == "/":
        return path or "/"
    segs = path.split("/")
    for i, s in enumerate(segs):
        if s.lower() in protected_segments:
            continue
        if _segment_is_param(s):
            segs[i] = f"{{{_param_name(s)}}}"
    return "/".join(segs)


def _values_at(path_freq: dict[str, int], index: int) -> list[str]:
    """Valores reales (ordenados por frecuencia desc) en la posicion `index` del path."""
    counts: dict[str, int] = {}
    for path, freq in path_freq.items():
        segs = path.lstrip("/").split("/")
        if index < len(segs):
            counts[segs[index]] = counts.get(segs[index], 0) + freq
    return [v for v, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def _placeholder_positions(template: str) -> list[tuple[int, str]]:
    """Devuelve [(index, placeholder)] de cada `{param}` en el template."""
    out: list[tuple[int, str]] = []
    for i, seg in enumerate(template.lstrip("/").split("/")):
        m = re.fullmatch(r"\{([^}]+)\}", seg)
        if m:
            out.append((i, m.group(1)))
    return out


def _template_segments(template: str) -> dict:
    """Devuelve la lista de segmentos clasificados (SAD 4.3.4) como dict JSON."""
    segments = []
    for i, seg in enumerate(template.lstrip("/").split("/")):
        m = re.fullmatch(r"\{([^}]+)\}", seg)
        if m:
            segments.append({"index": i, "class": "param", "param": m.group(1)})
        elif seg:
            segments.append({"index": i, "class": "fixed", "value": seg})
    return {"segments": segments}


def build_restricted_template(
    path_freq: dict[str, int],
    template: str,
    *,
    cardinality_threshold: int = 0,
    protected_segments: frozenset[str] = DEFAULT_PROTECTED_SEGMENTS,
) -> str:
    """Devuelve el template 'restringido' (SAD 4.3.3).

    Reemplaza por su valor mas frecuente los placeholders cuya cardinalidad de
    valores observados es menor o igual a `cardinality_threshold`, evitando la
    sobre-normalizacion de segmentos que en realidad son fijos. Los segmentos
    protegidos nunca se templatizan de todas formas.
    """
    if cardinality_threshold <= 0 or not path_freq or not template:
        return template
    leading = "/" if template.startswith("/") else ""
    t = template.lstrip("/").split("/")
    for i, seg in enumerate(t):
        m = re.fullmatch(r"\{([^}]+)\}", seg)
        if not m:
            continue
        param = m.group(1)
        if param in protected_segments:
            continue
        values = _values_at(path_freq, i)
        if len(values) <= cardinality_threshold:
            t[i] = values[0]
    return leading + "/".join(t)


def extract_path_params(path: str, template: str) -> dict[str, str]:
    """Extrae los valores reales de los placeholders del template."""
    p = path.lstrip("/").split("/")
    t = template.lstrip("/").split("/")
    out: dict[str, str] = {}
    for idx, seg in enumerate(t):
        m = re.fullmatch(r"\{([^}]+)\}", seg)
        if m and idx < len(p):
            out[m.group(1)] = p[idx]
    return out


# ── deteccion de credenciales ───────────────────────────────────────────────────

_AUTH_HEADERS = {"authorization", "x-api-key", "x-auth-token", "proxy-authorization"}
_SECRET_NAME = re.compile(r"(?i)(secret|token|key|password|cred)")
_SECRET_BODY = re.compile(r'(?i)"[a-z0-9_]*?(secret|token|password|api[_-]?key)[a-z0-9_]*"\s*:')


def detect_secrets(raw: RawExchange) -> dict[str, list[str]]:
    """Devuelve headers, cookies y cuerpos que parecen contener credenciales."""
    found: dict[str, list[str]] = {"headers": [], "cookies": [], "bodies": []}

    for h in raw.request.headers:
        low = h.name.lower()
        if low in _AUTH_HEADERS or _SECRET_NAME.search(low):
            found["headers"].append(h.name)

    for c in raw.request.cookies:
        if _SECRET_NAME.search(c.name.lower()):
            found["cookies"].append(c.name)

    if raw.request.body and raw.request.body.text and _SECRET_BODY.search(raw.request.body.text):
        found["bodies"].append("request")
    if raw.response.body and raw.response.body.text and _SECRET_BODY.search(raw.response.body.text):
        found["bodies"].append("response")

    return found


def normalize(raw: RawExchange, config: NormalizeConfig | None = None) -> NormalizedExchange:
    """Convierte un RawExchange en NormalizedExchange."""
    config = config or NormalizeConfig()
    path = raw.path
    template = build_template(path, config.protected_segments)
    params = extract_path_params(path, template)
    return NormalizedExchange(
        exchange_id=_uuid(raw.exchange_id),
        import_id=raw.import_id,
        order=raw.order,
        timestamp=raw.timestamp,
        host=raw.host,
        port=raw.port,
        scheme=raw.scheme,
        method=raw.method,
        path=path,
        query_string=raw.query_string,
        template=template,
        path_params=params,
        client_ip=raw.client_ip,
        request=raw.request,
        response=raw.response,
        timings=raw.timings,
    )


def _uuid(value: Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


__all__ = [
    "build_template",
    "build_restricted_template",
    "extract_path_params",
    "detect_secrets",
    "normalize",
    "NormalizeConfig",
    "DEFAULT_PROTECTED_SEGMENTS",
]
