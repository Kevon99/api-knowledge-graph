"""Tests de materializacion de recursos y AuthFlow (V0.1-20/22/23)."""

import uuid
from datetime import UTC, datetime

from engine.graph.materialize import resource_names_from_template


class FakeGraphRepo:
    """Repo falso que registra nodos y relaciones en memoria."""

    def __init__(self) -> None:
        self.nodes: list[tuple[str, dict]] = []
        self.rels: list[tuple[str, dict, str, dict, str, dict]] = []

    def upsert_node(self, label: str, props: dict, key_properties: list[str], *, import_id=None):
        self.nodes.append((label, dict(props)))
        return []

    def upsert_relationship(self, from_match, from_params, to_match, to_params, rel_type, rel_properties=None):
        self.rels.append((from_match, dict(from_params), to_match, dict(to_params), rel_type, dict(rel_properties or {})))
        return []


def test_resource_names_from_template() -> None:
    assert resource_names_from_template("/api/v1/users/{id}") == ["users"]
    assert resource_names_from_template("/api/v1/contacts/{id}/messages") == ["contacts", "messages"]
    assert resource_names_from_template("/auth/login") == []
    assert resource_names_from_template("/") == []


def test_materialize_creates_resources_with_confidence() -> None:
    from engine.graph.materialize import materialize_exchanges

    repo = FakeGraphRepo()
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    exchanges = [
        {
            "exchange_id": uuid.uuid4(),
            "host": "api.example.com",
            "method": "GET",
            "path": "/api/v1/users/42",
            "template": "/api/v1/users/{int}",
            "scheme": "https",
            "port": 443,
            "timestamp": ts,
            "request": {"headers": [], "cookies": [], "has_json": False},
            "response": {"headers": [], "cookies": [], "has_json": True, "status_code": 200},
        }
    ]
    counts = materialize_exchanges(exchanges, project="p", import_id=uuid.uuid4(), graph=repo)

    resources = [p for lab, p in repo.nodes if lab == "Resource"]
    assert any(r["name"] == "users" for r in resources)
    assert counts["accepts"] == 0  # GET sin body -> no ACCEPTS

    accepts = [r for r in repo.rels if r[4] == "ACCEPTS"]
    returns = [r for r in repo.rels if r[4] == "RETURNS"]
    assert len(returns) == 1
    assert returns[0][5]["confidence"] == "INFERENCIA"
    assert returns[0][5]["score"] == 0.7
    assert len(accepts) == 0


def test_materialize_accepts_on_write() -> None:
    from engine.graph.materialize import materialize_exchanges

    repo = FakeGraphRepo()
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    exchanges = [
        {
            "exchange_id": uuid.uuid4(),
            "host": "api.example.com",
            "method": "POST",
            "path": "/api/v1/contacts",
            "template": "/api/v1/contacts",
            "scheme": "https",
            "port": 443,
            "timestamp": ts,
            "request": {"headers": [], "cookies": [], "has_json": True},
            "response": {"headers": [], "cookies": [], "has_json": True, "status_code": 201},
        }
    ]
    materialize_exchanges(exchanges, project="p", import_id=uuid.uuid4(), graph=repo)
    accepts = [r for r in repo.rels if r[4] == "ACCEPTS"]
    assert len(accepts) == 1
    assert accepts[0][3]["name"] == "contacts"
