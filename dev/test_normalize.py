"""Test del normalizador: plantillas, path_params y deteccion de secretos."""

from akg.pipeline.normalizer import (
    build_template,
    detect_secrets,
    extract_path_params,
    normalize,
)
from akg.schemas import RawExchange
from akg.schemas.core import BodyPayload, Cookie, Header, RequestPayload, ResponsePayload


def mk_exchange(path: str, method: str = "GET", with_auth: bool = False) -> RawExchange:
    req_headers = []
    if with_auth:
        req_headers.append(Header(name="Authorization", value="Bearer abc123"))
    req_headers.append(Header(name="Cookie" if False else "Accept", value="application/json"))
    req = RequestPayload(
        headers=req_headers,
        cookies=[Cookie(name="sid", value="secret-val")],
        body=BodyPayload(
            text=(
                '{"email":"a@b.c","api_key":"k123","x":"1"}'
                if with_auth
                else '{"email":"a@b.c"}'
            ),
            content_type="application/json",
        ),
    )
    resp = ResponsePayload(status_code=0, headers=[], cookies=[])
    exchange = RawExchange(
        host="api.example.com",
        method=method,
        path=path,
        scheme="https",
        timestamp="2026-01-01T00:00:00+00:00",
        request=req,
        response=resp,
    )
    return exchange


def main() -> None:
    cases = [
        ("/api/v1/users/42", "/api/v1/users/{int}"),
        ("/api/v1/users/123e4567-e89b-12d3-a456-426614174000", "/api/v1/users/{uuid}"),
        ("/api/v1/orders/7", "/api/v1/orders/{int}"),
        ("/health", "/health"),
        ("/", "/"),
    ]
    for path, expected in cases:
        tpl = build_template(path)
        ok = "OK " if tpl == expected else "FAIL"
        print(f"  [{ok}] {path!r} -> {tpl!r} (esperado {expected!r})")

    print("path_params:", extract_path_params("/api/v1/users/42", "/api/v1/users/{42}"))

    raw = mk_exchange("/api/v1/users/99", with_auth=True)
    norm = normalize(raw)
    print("normalize template:", norm.template)
    print("normalize params:", norm.path_params)
    print("detect_secrets:", detect_secrets(raw))


if __name__ == "__main__":
    main()