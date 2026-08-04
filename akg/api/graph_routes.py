"""Router del grafo (consulta Neo4j, SAD cap. 9.4.3)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException

from akg.api.schemas import GraphQuery, GraphSummary
from engine.graph.repository import graph_repo

router = APIRouter(prefix="/api/v1/graph")

# bloquear cypher destructivo en consultas de query
_BLOCKED_KEYWORDS = re.compile(r"\b(DETACH\s+DELETE|DELETE|DROP|CREATE)\b", re.IGNORECASE)


@router.get("/summary", response_model=GraphSummary, summary="Estadisticas del grafo")
def graph_summary() -> GraphSummary:
    node_rows = graph_repo.run_read("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS c")
    rel_rows = graph_repo.run_read("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c")
    return GraphSummary(
        node_counts={r["label"]: r["c"] for r in node_rows},
        relationship_counts={r["t"]: r["c"] for r in rel_rows},
    )


@router.post("/query", summary="Consulta Cypher (solo lectura)")
def graph_query(payload: GraphQuery) -> list[dict[str, Any]]:
    if _BLOCKED_KEYWORDS.search(payload.cypher):
        raise HTTPException(status_code=422, detail="solo se permiten consultas de lectura")
    return graph_repo.run_read(payload.cypher, payload.params)


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
def graph_auth_endpoints() -> dict[str, Any]:
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
def graph_auth_flow() -> dict[str, Any]:
    rows = graph_repo.run_read(
        "MATCH (af:AuthFlow) "
        "OPTIONAL MATCH (l:Endpoint)-[s:STARTS_AUTH]->(af) "
        "OPTIONAL MATCH (af)-[a:AUTHENTICATES]->(c:Endpoint) "
        "RETURN af, l, c ORDER BY af.session_hash"
    )
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for row in rows:
        af = row.get("af") or {}
        for key in ("l", "c"):
            ep = row.get(key)
            if not ep:
                continue
            n = _node_view(ep, "Endpoint")
            nodes.setdefault(n["id"], n)
        af_node = _node_view(af, "AuthFlow")
        nodes.setdefault(af_node["id"], af_node)
        login = row.get("l")
        if login:
            edges.append(_edge(nodes[_node_view(login, "Endpoint")["id"]], af_node, "STARTS_AUTH"))
        consumer = row.get("c")
        if consumer:
            edges.append(
                _edge(af_node, nodes[_node_view(consumer, "Endpoint")["id"]], "AUTHENTICATES")
            )
    return {"nodes": list(nodes.values()), "edges": edges}


def _node_view(data: dict[str, Any], label: str) -> dict[str, Any]:
    props = dict(data)
    nid = props.get("id")
    if nid is None:
        nid = f"{props.get('method', '')}:{props.get('pattern', '')}:{props.get('host', '')}"
    props.pop("labels", None)
    props.pop("id", None)
    return {"id": str(nid), "labels": [label], "properties": props}


@router.get("/resources", summary="Grafo de recursos y sus endpoints (V0.1-20/38)")
def graph_resources() -> dict[str, Any]:
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
