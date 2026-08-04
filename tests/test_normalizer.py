"""Tests unitarios del normalizador (akg.pipeline.normalizer)."""

from datetime import UTC, datetime

import pytest

from akg.pipeline.normalizer import (
    build_restricted_template,
    build_template,
    detect_secrets,
    extract_path_params,
)
from akg.schemas import RawExchange
from akg.schemas.core import (
    BodyPayload,
    Cookie,
    Header,
    RequestPayload,
    ResponsePayload,
)


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/api/v1/users/42", "/api/v1/users/{int}"),
        ("/api/v1/users/7", "/api/v1/users/{int}"),
        ("/api/v1/users/123e4567-e89b-12d3-a456-426614174000", "/api/v1/users/{uuid}"),
        ("/health", "/health"),
        ("/", "/"),
        ("/api/v1/orders/0x1f", "/api/v1/orders/{hex}"),
        ("/api/v1/items/7", "/api/v1/items/{int}"),
    ],
)
def test_build_template(path: str, expected: str) -> None:
    assert build_template(path) == expected


def test_build_template_preserves_static_segments() -> None:
    assert build_template("/api/v1/users/me/profile") == "/api/v1/users/me/profile"


def test_build_template_protects_segments() -> None:
    """V0.1-10: segmentos protegidos (api/v1/admin...) nunca se templatizan."""
    assert build_template("/api/v1/users/42") == "/api/v1/users/{int}"
    assert build_template("/admin/health") == "/admin/health"
    assert build_template("/admin/42") == "/admin/{int}"


def test_build_restricted_template_reverts_low_cardinality() -> None:
    """V0.1-10: placeholders con cardinalidad <= umbral vuelven a valor fijo."""
    path_freq = {"/api/v1/users/1": 10, "/api/v1/users/2": 1}
    assert (
        build_restricted_template(
            path_freq, "/api/v1/users/{int}", cardinality_threshold=2
        )
        == "/api/v1/users/1"
    )
    assert (
        build_restricted_template(
            path_freq, "/api/v1/users/{int}", cardinality_threshold=1
        )
        == "/api/v1/users/{int}"
    )


def test_build_restricted_template_zero_threshold_unchanged() -> None:
    assert build_restricted_template(
        {"/a/1": 5, "/a/2": 5}, "/a/{int}", cardinality_threshold=0
    ) == "/a/{int}"


def test_extract_path_params() -> None:
    params = extract_path_params("/api/v1/users/42", "/api/v1/users/{int}")
    assert params.get("int") == "42"


def _mk_raw(body_text: str | None) -> RawExchange:
    req = RequestPayload(
        headers=[
            Header(name="Authorization", value="Bearer abc123"),
            Header(name="Accept", value="application/json"),
        ],
        cookies=[Cookie(name="sid", value="secret-val")],
        body=BodyPayload(data=None, text=body_text, content_type="application/json"),
        has_json=bool(body_text),
    )
    resp = ResponsePayload(
        status_code=200,
        headers=[Header(name="Content-Type", value="application/json")],
        cookies=[],
    )
    return RawExchange(
        host="api.example.com",
        method="GET",
        path="/api/v1/users/42",
        scheme="https",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        request=req,
        response=resp,
    )


def test_detect_secrets_authorization_header() -> None:
    secrets = detect_secrets(_mk_raw(body_text='{"a":"b"}'))
    assert "Authorization" in secrets["headers"]


def test_detect_secrets_json_body() -> None:
    secrets = detect_secrets(_mk_raw(body_text='{"api_key":"k123","user":"u"}'))
    assert "request" in secrets["bodies"]


def test_detect_secrets_no_false_positive() -> None:
    secrets = detect_secrets(_mk_raw(body_text='{"x":1}'))
    assert secrets["bodies"] == []
