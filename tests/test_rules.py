"""Tests del motor de reglas (SAD cap. 8)."""

import uuid
from typing import Any

from akg.rules import get_rules, run_rules
from akg.rules.catalog import CATALOG_V1


class FakeGraph:
    """Grafo falso: devuelve las filas registradas por query."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.queries: list[str] = []

    def run_read(self, cypher: str, params=None, *, db="neo4j", timeout=15):
        self.queries.append(cypher)
        return list(self.rows)


def _rows(*rows: dict[str, Any]) -> list[dict[str, Any]]:
    return list(rows)


def test_catalog_registry() -> None:
    ids = {r.rule_id for r in CATALOG_V1}
    assert "R-IDOR-001" in ids
    assert "R-IDOR-004" in ids
    assert "R-AUTH-001" in ids
    assert "R-INFRA-001" in ids
    enabled = get_rules(enabled_only=True)
    assert all(r.enabled for r in enabled)
    assert len(enabled) < len(CATALOG_V1)


def test_run_rules_produces_alerts() -> None:
    import_id = uuid.uuid4()
    graph = FakeGraph()
    graph.rows = _rows(
        {
            "method": "GET",
            "pattern": "/users/{int}",
            "resource_type": "users",
            "host": "api.a.com",
            "hosts_distinct": 3,
            "uses": 5,
        }
    )
    rules = [r for r in CATALOG_V1 if r.rule_id == "R-IDOR-001"]
    alerts = run_rules(rules, import_id, graph)
    assert len(alerts) == 1
    assert alerts[0].rule.rule_id == "R-IDOR-001"
    assert "{pattern}" not in alerts[0].title
    assert "/users/{int}" in alerts[0].title
    assert alerts[0].evidence["group_key"]
    assert graph.queries and "$import_id" in graph.queries[0]


def test_run_rules_where_filters() -> None:
    import_id = uuid.uuid4()
    graph = FakeGraph()
    # R-IDOR-001 tiene where: hosts_distinct gte 2 -> se filtra
    graph.rows = _rows(
        {
            "method": "GET",
            "pattern": "/users/{int}",
            "resource_type": "users",
            "host": "api.a.com",
            "hosts_distinct": 1,
            "uses": 5,
        }
    )
    rules = [r for r in CATALOG_V1 if r.rule_id == "R-IDOR-001"]
    alerts = run_rules(rules, import_id, graph)
    assert alerts == []


def test_run_rules_ignores_disabled() -> None:
    import_id = uuid.uuid4()
    graph = FakeGraph()
    graph.rows = _rows({"method": "GET", "pattern": "/x", "host": "h", "uses": 1})
    disabled = [r for r in CATALOG_V1 if not r.enabled]
    assert disabled  # al menos una regla deshabilitada en el catalogo
    alerts = run_rules(disabled, import_id, graph)
    assert alerts == []
