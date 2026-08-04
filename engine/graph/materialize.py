"""Materializacion de exchanges en el grafo de conocimiento (Neo4j).

Lee los exchanges canonizados (RawExchange) y los vuelca en el grafo siguiendo
el esquema v1 (schemas/neo4j/v1.cypher): nodos Host, Endpoint, Cookie, Token,
Resource, Exchange y Workspace, con sus relaciones entre ellos.

Las operaciones son idempotentes (MERGE por clave natural).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from engine.graph.repository import GraphRepository, graph_repo


def _token_key(value: str) -> tuple[str, str]:
    """Devuelve (token_type, value_hash) heuristico para un header de autorizacion."""
    stripped = value.strip()
    if " " in stripped:
        scheme, _, rest = stripped.partition(" ")
        token_type = scheme.upper()
        token_value = rest
    else:
        token_type = "BEARER"
        token_value = stripped
    return token_type, hashlib.sha256(token_value.encode()).hexdigest()


def _upsert_host(repo: GraphRepository, host: str, project: str, import_id: uuid.UUID) -> None:
    repo.upsert_node(
        "Host",
        {"name": host, "project": project},
        key_properties=["name"],
        import_id=import_id,
    )


def _upsert_endpoint(
    repo: GraphRepository,
    host: str,
    method: str,
    pattern: str,
    scheme: str,
    port: int,
    import_id: uuid.UUID,
) -> None:
    repo.upsert_node(
        "Endpoint",
        {
            "method": method,
            "pattern": pattern,
            "host": host,
            "scheme": scheme,
            "port": port,
        },
        key_properties=["method", "pattern", "host"],
        import_id=import_id,
    )
    # relacion semantica: el host sirve el endpoint (no via Exchange)
    repo.upsert_relationship(
        "Host",
        {"name": host},
        "Endpoint",
        {"method": method, "pattern": pattern, "host": host},
        "HOSTS",
        rel_properties={"import_id": import_id},
    )


def materialize_exchanges(
    exchanges: list[Any],
    *,
    project: str,
    import_id: uuid.UUID,
    graph: GraphRepository | None = None,
) -> dict[str, int]:
    """Materializa una lista de exchanges en Neo4j. Devuelve conteos.

    `project` es el workspace/namespace donde vivir el grafo (p.ej. el nombre
    del workspace). Cada `exchange` es un dict con al menos los campos del
    modelo canonico.
    """
    counts = {
        "hosts": 0,
        "endpoints": 0,
        "exchanges": 0,
        "tokens": 0,
        "cookies": 0,
        "resources": 0,
        "accepts": 0,
        "returns": 0,
    }
    repo = graph or graph_repo

    for ex in exchanges:
        # ── nodo raiz Host ──
        _upsert_host(repo, ex["host"], project, import_id)
        counts["hosts"] += 1

        pattern = ex.get("template") or ex["path"].split("?")[0]
        method = ex["method"].upper()
        _upsert_endpoint(
            repo,
            ex["host"],
            method,
            pattern,
            ex.get("scheme", "https"),
            ex.get("port", 443),
            import_id,
        )
        counts["endpoints"] += 1

        request = ex.get("request", {}) or {}
        response = ex.get("response") or {}
        ep_meta = {"method": method, "pattern": pattern, "host": ex["host"]}

        # ── recursos derivados del template (V0.1-20/26) ──────────────────
        res_accepts, res_returns = _link_resources(
            repo, ep_meta, pattern, method, request, response, import_id
        )
        counts["resources"] += res_accepts[0] + res_returns[0]
        counts["accepts"] += res_accepts[1]
        counts["returns"] += res_returns[1]

        # ── nodo Exchange ───────────────────────────────────────────────
        exchange_id = str(ex["exchange_id"])
        timestamp = ex.get("timestamp")
        if timestamp is not None and hasattr(timestamp, "isoformat"):
            timestamp = timestamp.isoformat()
        repo.upsert_node(
            "Exchange",
            {
                "exchange_id": exchange_id,
                "method": method,
                "path": ex["path"],
                "scheme": ex.get("scheme", "https"),
                "port": ex.get("port", 443),
                "timestamp": timestamp,
            },
            key_properties=["exchange_id"],
            import_id=import_id,
        )
        counts["exchanges"] += 1

        # ── relaciones Exchange-esde-hasta Host/Endpoint ───────────────
        _link_exchange(repo, exchange_id, ex["host"], method, pattern, import_id)

        # ── tokens de autorizacion ─────────────────────────────────────
        for h in ex.get("request", {}).get("headers", []):
            name = h.get("name", "").lower()
            if name == "authorization" and h.get("value"):
                t_type, t_hash = _token_key(h["value"])
                repo.upsert_node(
                    "Token",
                    {"token_type": t_type, "value_hash": t_hash},
                    key_properties=["token_type", "value_hash"],
                    import_id=import_id,
                )
                counts["tokens"] += 1
                repo.upsert_relationship(
                    "Exchange",
                    {"exchange_id": exchange_id},
                    "Token",
                    {"token_type": t_type, "value_hash": t_hash},
                    "SENDS_TOKEN",
                    rel_properties={"import_id": import_id, "confidence": "EVIDENCIA", "score": 1.0},
                )
                # semantica: el endpoint consume el token que autoriza
                repo.upsert_relationship(
                    "Endpoint",
                    ep_meta,
                    "Token",
                    {"token_type": t_type, "value_hash": t_hash},
                    "AUTHENTICATES_WITH",
                    rel_properties={"import_id": import_id, "confidence": "EVIDENCIA", "score": 1.0},
                )
                repo.upsert_relationship(
                    "Token",
                    {"token_type": t_type, "value_hash": t_hash},
                    "Endpoint",
                    ep_meta,
                    "AUTHORIZES",
                    rel_properties={"import_id": import_id, "confidence": "EVIDENCIA", "score": 1.0},
                )

        # ── cookies ────────────────────────────────────────────────────
        for c in ex.get("request", {}).get("cookies", []):
            counts["cookies"] += _link_cookie(repo, c, exchange_id, "SENDS", import_id)
            _link_endpoint_cookie(repo, ep_meta, c, "CONSUMES", import_id)
        for c in ex.get("response", {}).get("cookies", []):
            counts["cookies"] += _link_cookie(repo, c, exchange_id, "RECEIVES", import_id)
            _link_endpoint_cookie(repo, ep_meta, c, "EMITS", import_id)

    return counts


# segmentos de prefijo/verbo que no se tratan como recursos
_SKIP_RESOURCE_SEGMENTS = {
    "api",
    "v1",
    "v2",
    "v3",
    "auth",
    "oauth",
    "oauth2",
    "login",
    "logout",
    "token",
    "session",
    "health",
    "status",
    "ping",
    "webhooks",
}

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def resource_names_from_template(pattern: str) -> list[str]:
    """Deriva nombres de recursos de los segmentos estaticos de un template.

    Ejemplo: `/api/v1/users/{id}/contacts` -> ["users", "contacts"].
    El segmento que precede a un parametro o el ultimo segmento estatico es
    candidato a recurso (coleccion que se manipula).
    """
    segs = [s for s in pattern.split("/") if s]
    out: list[str] = []
    for i, seg in enumerate(segs):
        if seg.startswith("{") or seg.lower() in _SKIP_RESOURCE_SEGMENTS:
            continue
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        if nxt is None or nxt.startswith("{"):
            out.append(seg)
    return list(dict.fromkeys(out))


def _link_resources(
    repo: GraphRepository,
    ep_meta: dict[str, str],
    pattern: str,
    method: str,
    request: dict[str, Any],
    response: dict[str, Any],
    import_id: uuid.UUID,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Crea nodos Resource y relaciones ACCEPTS/RETURNS desde el endpoint.

    Devuelve ((recursos_creados, accepts), (recursos_creados, returns)).
    """
    names = resource_names_from_template(pattern)
    accepts = returns = 0
    created = 0
    for name in names:
        repo.upsert_node(
            "Resource",
            {"name": name},
            key_properties=["name"],
            import_id=import_id,
        )
        created += 1

        req_json = bool(request.get("has_json"))
        resp_json = bool(response.get("has_json"))
        status = response.get("status_code")

        # ACCEPTS: el endpoint recibe/escibe el recurso (request con body o metodo de escritura)
        if method in _WRITE_METHODS or req_json:
            repo.upsert_relationship(
                "Endpoint",
                ep_meta,
                "Resource",
                {"name": name},
                "ACCEPTS",
                rel_properties={
                    "import_id": import_id,
                    "confidence": "INFERENCIA",
                    "score": 0.7,
                },
            )
            accepts += 1

        # RETURNS: el endpoint devuelve el recurso (response JSON exitosa)
        if resp_json or (status and 200 <= status < 300):
            repo.upsert_relationship(
                "Endpoint",
                ep_meta,
                "Resource",
                {"name": name},
                "RETURNS",
                rel_properties={
                    "import_id": import_id,
                    "confidence": "INFERENCIA",
                    "score": 0.7,
                },
            )
            returns += 1

    return (created, accepts), (created, returns)


def _link_exchange(
    repo: GraphRepository,
    exchange_id: str,
    host: str,
    method: str,
    pattern: str,
    import_id: uuid.UUID,
) -> None:
    repo.upsert_relationship(
        "Exchange",
        {"exchange_id": exchange_id},
        "Host",
        {"name": host},
        "HITS_HOST",
        rel_properties={"import_id": import_id},
    )
    repo.upsert_relationship(
        "Exchange",
        {"exchange_id": exchange_id},
        "Endpoint",
        {"method": method, "pattern": pattern, "host": host},
        "CALLS",
        rel_properties={"import_id": import_id},
    )


def _link_cookie(
    repo: GraphRepository, c: dict[str, Any], exchange_id: str, rel_type: str, import_id: uuid.UUID
) -> int:
    value_hash = c.get("value_hash") or hashlib.sha256((c.get("value") or "").encode()).hexdigest()
    repo.upsert_node(
        "Cookie",
        {"name": c.get("name"), "value_hash": value_hash},
        key_properties=["name", "value_hash"],
        import_id=import_id,
    )
    repo.upsert_relationship(
        "Exchange",
        {"exchange_id": exchange_id},
        "Cookie",
        {"name": c.get("name"), "value_hash": value_hash},
        rel_type,
        rel_properties={"import_id": import_id},
    )
    return 1


def _link_endpoint_cookie(
    repo: GraphRepository,
    ep: dict[str, str],
    c: dict[str, Any],
    rel_type: str,
    import_id: uuid.UUID,
) -> None:
    """Relacion semantica Endpoint -> Cookie (CONSUMES en request, EMITS en response)."""
    value_hash = c.get("value_hash") or hashlib.sha256((c.get("value") or "").encode()).hexdigest()
    repo.upsert_relationship(
        "Endpoint",
        ep,
        "Cookie",
        {"name": c.get("name"), "value_hash": value_hash},
        rel_type,
        rel_properties={"import_id": import_id},
    )


__all__ = ["materialize_exchanges", "resource_names_from_template"]
