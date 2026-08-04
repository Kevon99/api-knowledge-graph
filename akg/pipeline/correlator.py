"""Motor de correlacion (etapa 4 del pipeline, SAD capitulo 7).

A partir de exchanges normalizados agrupa sesiones y construye relaciones
sobre el grafo:

  * Sesiones: se agrupan por clave estable derivada de cookies de sesion o
    del header `Authorization` (Bearer). Se preserva el orden temporal.
  * `CONSUMES`: Session -> Endpoint (el portador consume el endpoint).
  * `FLOW_NEXT`: Session -> Session de la misma sesion se encadena; se
    materializan como relacionados dentro de la sesion (work flow).

Nota: los identificadores de sesion se reportan como hash para no exponer
credenciales (SAD capitulo 11). Solo se correlacionan exchanges que
comparten la misma clave.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import defaultdict
from typing import Any

from akg.schemas import NormalizedExchange

_SESSION_COOKIE_NAMES = ("session", "sessionid", "jsessionid", "phpsessid", "auth", "sid", "jwtid")

_AUTH_HEADERS = ("authorization", "authorisation")

# endpoints de autenticacion (V0.1-23)
_LOGIN_RE = re.compile(
    r"(/(login|signin|authenticate|auth/token|oauth/token|session|sessions|connect/token))"
    r"(/|$)",
    re.IGNORECASE,
)


def _cookie_session_hint(ex: NormalizedExchange) -> str | None:
    for c in ex.request.cookies:
        name = c.name.lower().replace("_", "").replace("-", "")
        if name in _SESSION_COOKIE_NAMES:
            vh = c.value_hash or hashlib.sha256(c.value.encode()).hexdigest()
            return f"c:{name}:{vh}"
    return None


def _is_login(ex: NormalizedExchange) -> bool:
    return ex.method.upper() == "POST" and bool(_LOGIN_RE.search(ex.path))


def _auth_session_hint(ex: NormalizedExchange) -> str | None:
    for h in ex.request.headers:
        if h.name.lower() in _AUTH_HEADERS and h.value:
            digest = hashlib.sha256(h.value.encode()).hexdigest()
            return f"t:{digest}"
    return None


def session_key_of(ex: NormalizedExchange) -> str:
    """Devuelve la clave de sesion estable del exchange, o `orphan` si no hay sesion."""
    return _cookie_session_hint(ex) or _auth_session_hint(ex) or "orphan"


def group_by_session(
    exchanges: list[NormalizedExchange],
) -> dict[str, list[NormalizedExchange]]:
    """Agrupa exchanges en sesiones por clave estable, manteniendo orden temporal."""
    buckets: dict[str, list[NormalizedExchange]] = defaultdict(list)
    for ex in sorted(exchanges, key=lambda e: e.timestamp):
        buckets[session_key_of(ex)].append(ex)
    return dict(buckets)


def correlate_exchanges(
    exchanges: list[NormalizedExchange],
    *,
    project: str,
    import_id: uuid.UUID,
    graph: Any | None = None,
) -> dict[str, int]:
    """Correlaciona exchanges en sesiones y materializa relaciones en Neo4j."""
    from engine.graph.repository import graph_repo

    repo = graph or graph_repo
    result = {"sessions": 0, "consumes": 0, "flows": 0, "exchanges_in_session": 0}

    buckets = group_by_session(exchanges)
    for session_key, members in buckets.items():
        if session_key == "orphan":
            continue
        result["sessions"] += 1
        result["exchanges_in_session"] += len(members)

        session_hash = hashlib.sha256(session_key.encode()).hexdigest()[:12]
        repo.upsert_node(
            "Session",
            {"session_hash": session_hash, "project": project},
            key_properties=["session_hash"],
            import_id=import_id,
        )

        ordered = sorted(members, key=lambda m: (m.order, m.timestamp))

        # CONSUMES: cada exchange de la sesion consume su endpoint
        for m in ordered:
            repo.upsert_relationship(
                "Session",
                {"session_hash": session_hash},
                "Endpoint",
                {"method": m.method.upper(), "pattern": m.template, "host": m.host},
                "CONSUMES",
                rel_properties={
                    "import_id": import_id,
                    "confidence": "EVIDENCIA",
                    "score": 1.0,
                },
            )
            result["consumes"] += 1

        # # AuthFlow (V0.1-23): login -> token -> uso
        # _materialize_auth_flow(repo, ordered, session_hash, import_id, project, result)

        # flujo temporal: encadenar NEXT entre endpoints de la sesion
        for i in range(len(ordered) - 1):
            _upsert_flow(repo, ordered[i], ordered[i + 1], session_key, session_hash, import_id)
            # relacion semantica Endpoint -> Endpoint (navegacion dentro de la sesion)
            a = ordered[i]
            b = ordered[i + 1]
            repo.upsert_relationship(
                "Endpoint",
                {"method": a.method.upper(), "pattern": a.template, "host": a.host},
                "Endpoint",
                {"method": b.method.upper(), "pattern": b.template, "host": b.host},
                "NEXT",
                rel_properties={
                    "import_id": import_id,
                    "confidence": "EVIDENCIA",
                    "score": 1.0,
                },
            )
            result["flows"] += 1

    # AuthFlow por host (V0.1-23): login -> consumers en el mismo host
    _materialize_auth_flows(repo, exchanges, import_id, project, result)

    return result


def _materialize_auth_flows(
    repo: Any,
    exchanges: list[NormalizedExchange],
    import_id: uuid.UUID,
    project: str,
    result: dict[str, int],
) -> None:
    """Detecta logins y materializa AuthFlow por host (login -> uso).

    Un flujo de autenticacion comienza en un endpoint de login y se extiende a
    los endpoints consumidos en el mismo host despues de ese login. Se trabaja
    por host para cubrir tambien logins sin token propio (primer request de la
    sesion, tipicamente orphan en el agrupamiento por sesion).
    """
    by_host: dict[str, list[NormalizedExchange]] = {}
    for ex in exchanges:
        by_host.setdefault(ex.host, []).append(ex)

    for host, members in by_host.items():
        logins = [m for m in members if _is_login(m)]
        if not logins:
            continue

        ordered = sorted(members, key=lambda m: (m.order, m.timestamp))
        first_login = min(logins, key=lambda m: (m.order, m.timestamp))
        login_idx = ordered.index(first_login)
        flow_key = f"auth:{hashlib.sha256(host.encode()).hexdigest()[:12]}"
        repo.upsert_node(
            "AuthFlow",
            {
                "flow_hash": flow_key,
                "host": host,
                "login_method": first_login.method.upper(),
                "login_pattern": first_login.template,
            },
            key_properties=["flow_hash"],
            import_id=import_id,
        )
        result.setdefault("auth_flows", 0)
        result["auth_flows"] += 1

        # login -> AuthFlow
        repo.upsert_relationship(
            "Endpoint",
            {
                "method": first_login.method.upper(),
                "pattern": first_login.template,
                "host": host,
            },
            "AuthFlow",
            {"flow_hash": flow_key},
            "STARTS_AUTH",
            rel_properties={"import_id": import_id, "confidence": "INFERENCIA", "score": 0.8},
        )

        # AuthFlow -> endpoints consumidos despues del login en el mismo host
        for m in ordered[login_idx + 1 :]:
            repo.upsert_relationship(
                "AuthFlow",
                {"flow_hash": flow_key},
                "Endpoint",
                {"method": m.method.upper(), "pattern": m.template, "host": m.host},
                "AUTHENTICATES",
                rel_properties={"import_id": import_id, "confidence": "INFERENCIA", "score": 0.8},
            )
            result.setdefault("auth_uses", 0)
            result["auth_uses"] += 1


def _upsert_flow(
    repo: Any,
    a: NormalizedExchange,
    b: NormalizedExchange,
    session_key: str,
    session_hash: str,
    import_id: uuid.UUID,
) -> None:
    """Crea una transicion de flujo entre dos exchanges de la misma sesion."""
    repo.upsert_node(
        "Flow",
        {
            "key": f"{session_hash}:{a.order}:{b.order}",
            "from_order": a.order,
            "to_order": b.order,
            "from": f"{a.method.upper()} {a.template}",
            "to": f"{b.method.upper()} {b.template}",
        },
        key_properties=["key"],
        import_id=import_id,
    )


__all__ = ["session_key_of", "group_by_session", "correlate_exchanges"]
