"""Tests unitarios del extractor de entidades (akg.pipeline.extractor)."""

from datetime import UTC, datetime

from akg.pipeline.extractor import (
    claims_entities,
    decode_jwt,
    extract_entities,
    is_low_entropy,
    json_ids,
    stable_hash,
)
from akg.schemas import RawExchange
from akg.schemas.core import Cookie, Header, RequestPayload, ResponsePayload


def _mk_exchange(
    auth: str | None = None,
    cookie: str | None = None,
    req_json: dict | None = None,
    resp_json: dict | None = None,
) -> RawExchange:
    headers = [Header(name="Authorization", value=auth)] if auth else []
    cookies = [Cookie(name="session", value=cookie)] if cookie else []
    req = RequestPayload(
        headers=headers,
        cookies=cookies,
        body=None,
        has_json=bool(req_json),
    )
    resp = ResponsePayload(status_code=200, headers=[], cookies=[])
    return RawExchange(
        host="api.example.com",
        method="GET",
        path="/api/v1/users/42",
        scheme="https",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        request=req,
        response=resp,
    )


def test_stable_hash_is_sha256() -> None:
    assert len(stable_hash("foo")) == 64
    assert stable_hash("foo") == stable_hash(" foo ")


def test_is_low_entropy() -> None:
    assert is_low_entropy("1")
    assert is_low_entropy("test")
    assert is_low_entropy(None)
    assert not is_low_entropy("a1b2c3d4e5")


def test_decode_jwt_valid() -> None:
    import base64

    def b64(payload: dict) -> str:
        raw = base64.urlsafe_b64encode(str(payload).replace("'", '"').encode()).decode()
        return raw.rstrip("=")

    token = f"{b64({'alg': 'HS256'})}.{b64({'sub': '123', 'role': 'admin'})}.sig"
    header, payload = decode_jwt(token)
    assert header["alg"] == "HS256"
    assert payload["sub"] == "123"


def test_decode_jwt_invalid() -> None:
    assert decode_jwt("not-a-jwt") is None
    assert decode_jwt("abc.def.ghi") is None


def test_claims_entities_roles_scopes() -> None:
    claims = {"role": "admin", "scope": "read:users write:users"}
    entities = list(claims_entities(claims))
    assert ("role", "admin") in entities
    assert ("scope", "read:users") in entities
    assert ("scope", "write:users") in entities


def test_json_ids_canonical_paths() -> None:
    doc = {"data": {"user": {"id": 123456, "name": "foo"}, "contactId": "c-123"}}
    ids = list(json_ids(doc))
    assert ("data.user.id", "123456") in ids
    assert ("data.contactId", "c-123") in ids


def test_json_ids_skips_low_entropy() -> None:
    doc = {"id": 1, "data": {"id": "abc-456"}}
    ids = list(json_ids(doc))
    assert ("data.id", "abc-456") in ids
    assert not any(value == "1" for _, value in ids)


def test_extract_entities_jwt_and_cookie() -> None:
    import base64

    def b64(payload: dict) -> str:
        raw = base64.urlsafe_b64encode(str(payload).replace("'", '"').encode()).decode()
        return raw.rstrip("=")

    token = f"{b64({'alg': 'HS256'})}.{b64({'sub': '9', 'role': 'admin'})}.sig"
    ex = _mk_exchange(auth=f"Bearer {token}", cookie="sess123")
    occs = extract_entities(ex)
    types = {o.entity_type for o in occs}
    assert "jwt" in types
    assert "cookie_session" in types
    assert "role" in types
    jwt_occ = next(o for o in occs if o.entity_type == "jwt")
    assert jwt_occ.sensitive is True
    role_occ = next(o for o in occs if o.entity_type == "role")
    assert role_occ.entity_label == "admin"


def test_extract_entities_no_auth_no_ids() -> None:
    ex = _mk_exchange()
    occs = extract_entities(ex)
    assert all(o.entity_type == "json_id" for o in occs)
