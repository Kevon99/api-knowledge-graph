"""Router del grafo (consulta Neo4j, SAD cap. 9.4.3)."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from akg.api.deps import get_db
from akg.api.schemas import GraphQuery, GraphSummary, HeaderTrack
from akg.evidence.repository import EvidenceRepository
from engine.graph.repository import graph_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/graph")

_BLOCKED_KEYWORDS = re.compile(r"\b(DETACH\s+DELETE|DELETE|DROP|CREATE)\b", re.IGNORECASE)


@router.get("/summary", response_model=GraphSummary, summary="Estadisticas del grafo")
def graph_summary(
    workspace_id: str | None = Query(None, description="Filtrar por workspace (project)"),
) -> GraphSummary:
    if workspace_id:
        node_rows = graph_repo.run_read(
            "MATCH (n) WHERE n.project = $project_id "
            "RETURN labels(n)[0] AS label, count(*) AS c",
            {"project_id": workspace_id},
        )
        rel_rows = graph_repo.run_read(
            "MATCH ()-[r]->() WHERE r.project = $project_id "
            "RETURN type(r) AS t, count(*) AS c",
            {"project_id": workspace_id},
        )
    else:
        node_rows = graph_repo.run_read("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS c")
        rel_rows = graph_repo.run_read("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c")
    return GraphSummary(
        node_counts={r["label"]: r["c"] for r in node_rows},
        relationship_counts={r["t"]: r["c"] for r in rel_rows},
    )


@router.post("/query", summary="Consulta Cypher (solo lectura)")
def graph_query(
    payload: GraphQuery,
    workspace_id: str | None = Query(None, description="ID del workspace"),
) -> list[dict[str, Any]]:
    if _BLOCKED_KEYWORDS.search(payload.cypher):
        raise HTTPException(status_code=422, detail="solo se permiten consultas de lectura")
    params = dict(payload.params or {})
    if workspace_id:
        params.setdefault("project_id", workspace_id)
    return graph_repo.run_read(payload.cypher, params)


@router.get("/suggestions", summary="Sugerencias de hosts y endpoints para el buscador")
def graph_suggestions(
    q: str = "",
    limit: int = 25,
    workspace_id: str | None = Query(None, description="Filtrar por workspace"),
) -> dict[str, Any]:
    q = (q or "").strip()
    items: list[str] = []
    if q:
        if workspace_id:
            hosts = graph_repo.run_read(
                "MATCH (h:Host) WHERE h.project = $project_id "
                "AND toLower(h.name) CONTAINS toLower($q) "
                "RETURN h.name AS v ORDER BY h.name LIMIT $limit",
                {"q": q, "limit": limit, "project_id": workspace_id},
            )
            items += [r["v"] for r in hosts]
            eps = graph_repo.run_read(
                "MATCH (e:Endpoint) WHERE e.project = $project_id "
                "AND (toLower(e.host) CONTAINS toLower($q) "
                "OR toLower(e.pattern) CONTAINS toLower($q)) "
                "RETURN e.method + ' ' + coalesce(e.host, '') + e.pattern AS v "
                "ORDER BY v LIMIT $limit",
                {"q": q, "limit": limit, "project_id": workspace_id},
            )
            items += [r["v"] for r in eps]
        else:
            hosts = graph_repo.run_read(
                "MATCH (h:Host) WHERE toLower(h.name) CONTAINS toLower($q) "
                "RETURN h.name AS v ORDER BY h.name LIMIT $limit",
                {"q": q, "limit": limit},
            )
            items += [r["v"] for r in hosts]
            eps = graph_repo.run_read(
                "MATCH (e:Endpoint) WHERE toLower(e.host) CONTAINS toLower($q) "
                "OR toLower(e.pattern) CONTAINS toLower($q) "
                "RETURN e.method + ' ' + coalesce(e.host, '') + e.pattern AS v "
                "ORDER BY v LIMIT $limit",
                {"q": q, "limit": limit},
            )
            items += [r["v"] for r in eps]
    seen: set[str] = set()
    out: list[str] = []
    for v in items:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return {"suggestions": out[:limit]}


@router.get("/filter", summary="Grafo correlacionado con un subdominio o endpoint")
def graph_filter(
    q: str = "",
    limit: int = 200,
    workspace_id: str | None = Query(None, description="Filtrar por workspace"),
) -> list[dict[str, Any]]:
    q = (q or "").strip()
    if not q:
        raise HTTPException(status_code=422, detail="falta el parametro q")
    limit = max(10, min(1000, int(limit)))
    if workspace_id:
        base = (
            "MATCH (a) WHERE (a:Host AND toLower(a.name) CONTAINS toLower($q) AND a.project = $project_id) "
            "OR (a:Endpoint AND a.project = $project_id AND (toLower(a.host) CONTAINS toLower($q) "
            "OR toLower(a.pattern) CONTAINS toLower($q))) "
            "WITH a LIMIT $seedLimit "
            "OPTIONAL MATCH (a)-[r]-(b) WHERE NOT b:Exchange "
            "AND type(r) <> 'SENDS' AND type(r) <> 'RECEIVES' AND r.project = $project_id "
            "RETURN a, r, b, properties(r) AS rprops, labels(a) AS alabels, labels(b) AS blabels "
            "LIMIT $limit"
        )
        return graph_repo.run_read(
            base,
            {"q": q, "limit": limit, "seedLimit": min(100, limit), "project_id": workspace_id},
        )
    base = (
        "MATCH (a) WHERE (a:Host AND toLower(a.name) CONTAINS toLower($q)) "
        "OR (a:Endpoint AND (toLower(a.host) CONTAINS toLower($q) "
        "OR toLower(a.pattern) CONTAINS toLower($q))) "
        "WITH a LIMIT $seedLimit "
        "OPTIONAL MATCH (a)-[r]-(b) WHERE NOT b:Exchange "
        "AND type(r) <> 'SENDS' AND type(r) <> 'RECEIVES' "
        "RETURN a, r, b, properties(r) AS rprops, labels(a) AS alabels, labels(b) AS blabels "
        "LIMIT $limit"
    )
    return graph_repo.run_read(base, {"q": q, "limit": limit, "seedLimit": min(100, limit)})


def _node(view: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"{view.get('method', '')}:{view.get('pattern', '')}:{view.get('host', '')}",
        "labels": [view.get("labels", ["?"])[0]],
        "properties": {k: v for k, v in view.items() if k not in ("id", "labels")},
    }


def _edge(source: dict[str, Any], target: dict[str, Any], rel: str) -> dict[str, Any]:
    return {
        "id": f"{source['id']}->{target['id']}",
        "type": rel,
        "source": source["id"],
        "target": target["id"],
        "properties": {},
    }


@router.get("/auth-endpoints", summary="Endpoints que participan en auth (token/cookie)")
def graph_auth_endpoints(
    workspace_id: str | None = Query(None, description="Filtrar por workspace"),
) -> dict[str, Any]:
    if workspace_id:
        rows = graph_repo.run_read(
            "MATCH (e:Endpoint) WHERE e.project = $project_id "
            "OPTIONAL MATCH (e)-[:AUTHENTICATES_WITH]->(t:Token) WHERE t.project = $project_id "
            "OPTIONAL MATCH (e)-[:CONSUMES|EMITS]->(c:Cookie) WHERE c.project = $project_id "
            "RETURN e.method AS method, e.pattern AS pattern, e.host AS host, "
            "       count(DISTINCT t) AS tokens, count(DISTINCT c) AS cookies "
            "ORDER BY e.host, e.method, e.pattern",
            {"project_id": workspace_id},
        )
    else:
        rows = graph_repo.run_read(
            "MATCH (e:Endpoint) "
            "OPTIONAL MATCH (e)-[:AUTHENTICATES_WITH]->(t:Token) "
            "OPTIONAL MATCH (e)-[:CONSUMES|EMITS]->(c:Cookie) "
            "RETURN e.method AS method, e.pattern AS pattern, e.host AS host, "
            "       count(DISTINCT t) AS tokens, count(DISTINCT c) AS cookies "
            "ORDER BY e.host, e.method, e.pattern"
        )
    out = []
    for r in rows:
        if r["tokens"]:
            signal = "token"
        elif r["cookies"]:
            signal = "cookie"
        else:
            signal = "public"
        out.append({"method": r["method"], "pattern": r["pattern"], "host": r["host"], "signal": signal})
    return {"endpoints": out}


@router.get("/auth-flow", summary="Grafo de flujos de autenticacion (V0.1-23/37)")
def graph_auth_flow(
    workspace_id: str | None = Query(None, description="Filtrar por workspace"),
) -> dict[str, Any]:
    if workspace_id:
        rows = graph_repo.run_read(
            "MATCH (af:AuthFlow) WHERE af.project = $project_id "
            "OPTIONAL MATCH (af)-[a:AUTHENTICATES]->(c:Endpoint) WHERE a.project = $project_id "
            "RETURN af, c ORDER BY af.flow_hash",
            {"project_id": workspace_id},
        )
    else:
        rows = graph_repo.run_read(
            "MATCH (af:AuthFlow) "
            "OPTIONAL MATCH (af)-[a:AUTHENTICATES]->(c:Endpoint) "
            "RETURN af, c ORDER BY af.flow_hash"
        )
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for row in rows:
        af = row.get("af") or {}
        consumer = row.get("c")
        if consumer:
            n = _node_view(consumer, "Endpoint")
            nodes.setdefault(n["id"], n)
        af_node = _node_view(af, "AuthFlow")
        nodes.setdefault(af_node["id"], af_node)
        if consumer:
            edges.append(
                _edge(af_node, nodes[_node_view(consumer, "Endpoint")["id"]], "AUTHENTICATES")
            )
    return {"nodes": list(nodes.values()), "edges": edges}


def _node_view(data: dict[str, Any], label: str) -> dict[str, Any]:
    props = dict(data)
    nid = props.get("id")
    if label == "Header":
        nid = nid or f"Header:{props.get('name')}"
    elif nid is None:
        nid = f"{props.get('method', '')}:{props.get('pattern', '')}:{props.get('host', '')}"
    props.pop("labels", None)
    props.pop("id", None)
    return {"id": str(nid), "labels": [label], "properties": props}


@router.get("/resources", summary="Grafo de recursos y sus endpoints (V0.1-20/38)")
def graph_resources(
    workspace_id: str | None = Query(None, description="Filtrar por workspace"),
) -> dict[str, Any]:
    if workspace_id:
        rows = graph_repo.run_read(
            "MATCH (e:Endpoint)-[r:ACCEPTS|RETURNS]->(res:Resource) "
            "WHERE e.project = $project_id AND r.project = $project_id "
            "RETURN e, res, type(r) AS rel",
            {"project_id": workspace_id},
        )
    else:
        rows = graph_repo.run_read(
            "MATCH (e:Endpoint)-[r:ACCEPTS|RETURNS]->(res:Resource) "
            "RETURN e, res, type(r) AS rel"
        )
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for row in rows:
        ep = _node_view(row.get("e") or {}, "Endpoint")
        res = _node_view(row.get("res") or {}, "Resource")
        nodes.setdefault(ep["id"], ep)
        nodes.setdefault(res["id"], res)
        edges.append(_edge(ep, res, row.get("rel") or "RELATES"))
    return {"nodes": list(nodes.values()), "edges": edges}


# ── Seguimiento de headers (rastrear headers como nodos del grafo) ────────────
# La lista de headers rastreados vive en el workspace (autoritativa): solo los
# headers añadidos se materializan como nodo Header en Neo4j, y al dejarlos de
# rastrear se borran del grafo general. Ningun otro header genera nodo.


@router.get("/header-suggestions", summary="Sugerencias de headers existentes")
def header_suggestions(
    q: str = "",
    limit: int = 25,
    workspace_id: str | None = Query(None, description="Filtrar por workspace"),
    repo: EvidenceRepository = Depends(get_db),
) -> dict[str, Any]:
    if not workspace_id:
        return {"suggestions": []}
    try:
        from uuid import UUID

        ws_id = UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="workspace_id invalido") from None
    names = repo.list_header_names(ws_id, q=(q or "").strip(), limit=max(1, min(200, limit)))
    return {"suggestions": names}


def _header_full_view(
    repo: EvidenceRepository,
    workspace_id: uuid.UUID,
    headers: list[str],
    project: str,
) -> dict[str, Any]:
    """Grafo general completo del workspace + los headers rastreados como nodos.

    Devuelve TODOS los nodos/aristas del workspace (como el grafo general),
    pero si hay nodos :Header presentes, solo deja los de la lista `headers`
    (excluye cualquier otro header no rastreado).
    """
    names = {h.lower() for h in headers}
    if workspace_id:
        rows = graph_repo.run_read(
            "MATCH (a)-[r]->(b) WHERE NOT a:Exchange AND NOT b:Exchange "
            "AND type(r) <> 'SENDS' AND type(r) <> 'RECEIVES' "
            "AND a.project = $project AND r.project = $project "
            "RETURN a, r, b, type(r) AS rtype, labels(a) AS alabels, labels(b) AS blabels",
            {"project": project},
        )
    else:
        rows = graph_repo.run_read(
            "MATCH (a)-[r]->(b) WHERE NOT a:Exchange AND NOT b:Exchange "
            "AND type(r) <> 'SENDS' AND type(r) <> 'RECEIVES' "
            "RETURN a, r, b, type(r) AS rtype, labels(a) AS alabels, labels(b) AS blabels"
        )
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for row in rows:
        a = row.get("a") or {}
        b = row.get("b") or {}
        rtype = row.get("rtype") or ""
        if not a or not b or not rtype:
            continue
        alabel = (row.get("alabels") or ["?"])[0]
        blabel = (row.get("blabels") or ["?"])[0]
        if alabel == "Header" and str(a.get("name") or "").lower() not in names:
            continue
        if blabel == "Header" and str(b.get("name") or "").lower() not in names:
            continue
        na, nb = _node_view(a, alabel), _node_view(b, blabel)
        nodes.setdefault(na["id"], na)
        nodes.setdefault(nb["id"], nb)
        edges.append(_edge(na, nb, rtype))
    return {"nodes": list(nodes.values()), "edges": edges}


def _materialize_headers(targets: dict[str, list[dict[str, Any]]], project: str) -> None:
    """Crea en Neo4j los nodos Header y sus relaciones USES_HEADER."""
    for header_name, eps in targets.items():
        graph_repo.upsert_node(
            "Header",
            {"name": header_name, "raw": header_name, "project": project},
            key_properties=["name", "project"],
        )
        for ep in eps:
            graph_repo.upsert_relationship(
                "Endpoint",
                {"method": ep["method"], "pattern": ep["pattern"], "host": ep["host"]},
                "Header",
                {"name": header_name, "project": project},
                "USES_HEADER",
                {"project": project},
            )


@router.get("/headers", summary="Headers rastreados de un workspace (grafo general + headers)")
def list_tracked_headers(
    workspace_id: str = Query(..., description="ID del workspace"),
    repo: EvidenceRepository = Depends(get_db),
) -> dict[str, Any]:
    try:
        from uuid import UUID

        ws_id = UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="workspace_id invalido") from None
    tracked = repo.get_tracked_headers(ws_id)
    view = _header_full_view(repo, ws_id, tracked, str(ws_id))
    view["tracked"] = tracked
    return view


@router.post(
    "/headers/track",
    summary="Rastrea headers: crea el nodo Header en el grafo general",
)
def track_headers(
    payload: HeaderTrack,
    repo: EvidenceRepository = Depends(get_db),
) -> dict[str, Any]:
    headers = [h.strip() for h in payload.headers if h and h.strip()]
    if not headers:
        raise HTTPException(status_code=422, detail="al menos un header es requerido")
    try:
        tracked = repo.add_tracked_headers(payload.workspace_id, headers)
    except KeyError:
        raise HTTPException(status_code=404, detail="workspace no encontrado") from None

    project = str(payload.workspace_id)

    # reconciliacion: elimina del grafo cualquier nodo Header ya no rastreado
    # (nunca debe quedar un header que no este en la lista)
    graph_repo.run_write(
        "MATCH (h:Header) WHERE h.project = $p AND NOT h.name IN $names DETACH DELETE h",
        {"p": project, "names": [h.lower() for h in tracked]},
    )

    # materializa los nodos de los headers rastreados (aparecen en grafo general)
    targets = repo.header_endpoints(payload.workspace_id, tracked)
    _materialize_headers(targets, project)

    # la vista es el grafo general completo + los headers rastreados
    view = _header_full_view(repo, payload.workspace_id, tracked, project)
    view["tracked"] = tracked
    return view


@router.delete("/headers", summary="Deja de rastrear un header (borra el nodo del grafo)")
def untrack_header(
    name: str = Query(..., description="Nombre del header a dejar de rastrear"),
    workspace_id: str = Query(..., description="ID del workspace"),
    repo: EvidenceRepository = Depends(get_db),
) -> dict[str, Any]:
    header = (name or "").strip().lower()
    if not header:
        raise HTTPException(status_code=422, detail="nombre de header invalido")
    try:
        from uuid import UUID

        ws_id = UUID(workspace_id)
        project = str(ws_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="workspace_id invalido") from None
    tracked = repo.remove_tracked_header(ws_id, name)
    graph_repo.run_write(
        "MATCH (h:Header) WHERE h.name = $name AND h.project = $project_id DETACH DELETE h",
        {"name": header, "project_id": project},
    )
    return {"deleted": header, "tracked": tracked}
