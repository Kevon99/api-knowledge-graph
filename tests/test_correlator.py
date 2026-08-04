"""Tests unitarios del correlador (akg.pipeline.correlator)."""

import uuid as _uuid
from datetime import UTC, datetime

from akg.pipeline.correlator import correlate_exchanges, group_by_session, session_key_of
from akg.pipeline.normalizer import normalize
from akg.schemas import RawExchange
from akg.schemas.core import Cookie, Header, RequestPayload, ResponsePayload


class FakeGraphRepo:
    """Repo falso para aislar la correlacion del driver de Neo4j."""

    def __init__(self) -> None:
        self.nodes: list[tuple[str, dict]] = []
        self.rels: list[tuple[str, dict, dict, dict]] = []

    def upsert_node(self, label, props, key_properties, *, import_id=None):
        self.nodes.append((label, dict(props)))
        return []

    def upsert_relationship(self, from_match, from_params, to_match, to_params, rel_type, rel_properties=None):
        self.rels.append((rel_type, dict(from_params), dict(to_params), dict(rel_properties or {})))
        return []


def _mk_exchange(
    cookie: str | None = None, auth: str | None = None, ts: str = "2026-01-01T00:00:00+00:00"
) -> RawExchange:
    cookies = [Cookie(name="session", value=cookie)] if cookie else []
    headers = []
    if auth:
        headers.append(Header(name="Authorization", value=auth))
    req = RequestPayload(
        headers=headers,
        cookies=cookies,
        body=None,
        has_json=False,
    )
    resp = ResponsePayload(status_code=200, headers=[], cookies=[])
    return RawExchange(
        host="api.example.com",
        method="GET",
        path="/api/v1/users/42",
        scheme="https",
        timestamp=datetime.fromisoformat(ts).replace(tzinfo=UTC),
        request=req,
        response=resp,
    )


def test_session_key_cookie() -> None:
    ex = normalize(_mk_exchange("abc", ts="2026-01-01T00:00:00+00:00"))
    key = session_key_of(ex)
    assert key.startswith("c:session:")


def test_session_key_auth() -> None:
    ex = normalize(_mk_exchange(None, auth="Bearer tok123", ts="2026-01-01T00:00:00+00:00"))
    key = session_key_of(ex)
    assert key.startswith("t:")


def test_session_key_orphan() -> None:
    ex = normalize(_mk_exchange(None, ts="2026-01-01T00:00:00+00:00"))
    assert session_key_of(ex) == "orphan"


def test_group_by_session_preserves_session_first() -> None:
    ex1 = normalize(_mk_exchange("abc", ts="2026-01-01T00:00:00+00:00"))
    ex2 = normalize(_mk_exchange("abc", ts="2026-01-01T00:00:01+00:00"))
    ex3 = normalize(_mk_exchange(None, ts="2026-01-01T00:00:02+00:00"))
    buckets = group_by_session([ex1, ex2, ex3])
    assert len(buckets) == 2
    session_bucket = [k for k in buckets if k.startswith("c:")][0]
    assert len(buckets[session_bucket]) == 2
    assert len(buckets["orphan"]) == 1


def test_auth_flow_per_host() -> None:
    """Un login (sin token propio) genera AuthFlow a los endpoints posteriores."""
    exs = [
        normalize(_mk_exchange(None, ts="2026-01-01T00:00:00+00:00")),
        normalize(_mk_exchange(None, auth="Bearer t1", ts="2026-01-01T00:00:01+00:00")),
    ]
    # forzar el primero como login
    exs[0].path = "/api/v1/login"
    exs[0].method = "POST"
    exs[0].template = "/api/v1/login"

    repo = FakeGraphRepo()
    result = correlate_exchanges(exs, project="p", import_id=_uuid.uuid4(), graph=repo)

    assert result.get("auth_flows") == 1
    rels = {r[0] for r in repo.rels}
    assert "STARTS_AUTH" in rels
    assert "AUTHENTICATES" in rels
    auth_nodes = [p for lab, p in repo.nodes if lab == "AuthFlow"]
    assert len(auth_nodes) == 1
