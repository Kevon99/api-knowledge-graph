"""Catalogo v1 de reglas (SAD 8.6).

Cada consulta usa el esquema materializado del grafo:
- nodos: Host, Endpoint, Exchange, Token, Cookie, Resource, Workspace
- relaciones: AUTHENTICATES_WITH (Endpoint->Token), AUTHORIZES (Token->Endpoint),
  CONSUMES/EMITS (Endpoint->Cookie), RETURNS (Endpoint->Resource),
  ACCEPTS (Endpoint->Resource), HITS_HOST/CALLS (Exchange->Host/Endpoint)

Parametrizado con `$import_id`. Solo lecturas estrictas (MATCH/RETURN).
"""

from __future__ import annotations

from akg.rules.dsl import RuleSpec

CATALOG_V1: list[RuleSpec] = [
    # ── Autorizacion / IDOR ──────────────────────────────────────────────
    RuleSpec(
        rule_id="R-IDOR-001",
        category="IDOR",
        severity="ALTA",
        name="IDOR potencial en parametro de recurso",
        description=(
            "Endpoint parametrizado devuelve un recurso que tambien es accedido "
            "desde otros endpoints o hosts, sugiriendo acceso cruzado por ID."
        ),
        match=(
            "MATCH (e:Endpoint {import_id: $import_id}) "
            "WHERE e.pattern CONTAINS '{' "
            "MATCH (e)-[:RETURNS]->(r:Resource {import_id: $import_id}) "
            "MATCH (h:Host {import_id: $import_id})-[:HOSTS]->(e) "
            "WITH e, r, h.name AS host, count(DISTINCT e) AS uses "
            "RETURN e.method AS method, e.pattern AS pattern, "
            "r.name AS resource_type, host AS host, "
            "count(DISTINCT host) AS hosts_distinct, uses "
        ),
        emit_title="IDOR potencial: {pattern} retorna {resource_type}",
        where={"hosts_distinct": {"gte": 2}},
        group_by="pattern",
        references=[
            "OWASP API-1 Broken Object Level Authorization",
            "https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/",
        ],
        mitigation="Validar autorizacion a nivel de objeto en el servidor.",
        confidence=0.5,
    ),
    RuleSpec(
        rule_id="R-IDOR-004",
        category="IDOR",
        severity="ALTA",
        name="Falta de control de objeto en coleccion",
        description=(
            "GET sobre coleccion con id ({pattern}) retorna un recurso y no "
            "presenta auth observada (sin token ni cookie) en el import."
        ),
        match=(
            "MATCH (e:Endpoint {import_id: $import_id}) WHERE e.method = 'GET' "
            "AND e.pattern CONTAINS '{' "
            "OPTIONAL MATCH (e)-[:AUTHENTICATES_WITH]->(t:Token) "
            "OPTIONAL MATCH (e)-[:CONSUMES]->(c:Cookie) "
            "WITH e, t, c "
            "WHERE t IS NULL AND c IS NULL "
            "MATCH (e)-[:RETURNS]->(r:Resource {import_id: $import_id}) "
            "RETURN e.method AS method, e.pattern AS pattern, "
            "r.name AS resource_type, count(DISTINCT e) AS uses "
        ),
        emit_title="Posible falta de control de objeto: GET {pattern} sin auth observada",
        references=[
            "OWASP API-1",
            "https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/",
        ],
        mitigation="Exigir autenticacion y autorizacion por objeto.",
        confidence=0.6,
    ),
    # ── Autenticacion ────────────────────────────────────────────────────
    RuleSpec(
        rule_id="R-AUTH-003",
        category="AUTH",
        severity="ALTA",
        name="Credenciales en query string",
        description=(
            "Detecta parametros tipo password/token/secret en query strings. "
            "Requiere materializar query_params en el grafo; deshabilitada en v1."
        ),
        match=(
            "MATCH (e:Endpoint {import_id: $import_id}) "
            "RETURN e.method AS method, e.pattern AS pattern, "
            "e.host AS host, 1 AS uses LIMIT 0"
        ),
        emit_title="Credenciales en query: {method} {pattern}",
        enabled=False,
        references=["OWASP API-2"],
        mitigation="Mover credenciales al body/headers.",
        confidence=0.9,
    ),
    RuleSpec(
        rule_id="R-AUTH-001",
        category="AUTH",
        severity="MEDIA",
        name="Endpoint sin autenticacion observada",
        description=(
            "Endpoint (API) al que nunca se le observo un Token (AUTHENTICATES_WITH) "
            "o Cookie (CONSUMES) en el import analizado. Excluye estaticos "
            "(JS/CSS/fonts) y paths raiz/documentos de rutina."
        ),
        match=(
            "MATCH (e:Endpoint {import_id: $import_id}) "
            "OPTIONAL MATCH (e)-[:AUTHENTICATES_WITH]->(t:Token) "
            "OPTIONAL MATCH (e)-[:CONSUMES]->(c:Cookie) "
            "WITH e, t, c "
            "WHERE t IS NULL AND c IS NULL "
            "RETURN e.method AS method, e.pattern AS pattern, "
            "e.host AS host, count(DISTINCT e) AS uses "
        ),
        where={
            # excluye assets estaticos, telemetria y paths triviales (raiz o id solo)
            "pattern": {
                "not_contains_any": [
                    ".js",
                    ".css",
                    ".woff",
                    ".woff2",
                    ".ttf",
                    ".png",
                    ".jpg",
                    ".svg",
                    ".ico",
                    ".json",
                    "webpack",
                    "static-",
                    "/chirp-",
                    "gateway/stream",
                    "store/",
                ],
                "not": ["/", "/{uuid}", "/{int}", "/{id}"],
            },
        },
        emit_title="Endpoint sin auth observada: {method} {pattern}",
        references=["OWASP API-2 Broken Authentication"],
        mitigation="Confirmar si el recurso requiere autenticacion omitida.",
        confidence=0.5,
    ),
    # ── Infraestructura ──────────────────────────────────────────────────
    RuleSpec(
        rule_id="R-INFRA-001",
        category="INFRA",
        severity="MEDIA",
        name="Host no TLS",
        description="Endpoints servidos por HTTP plano.",
        match=(
            "MATCH (e:Endpoint {import_id: $import_id}) WHERE e.scheme = 'http' "
            "RETURN e.method AS method, e.pattern AS pattern, e.host AS host, "
            "e.scheme AS scheme, count(DISTINCT e) AS uses "
        ),
        emit_title="Host sin TLS: {host} ({scheme})",
        references=["OWASP Transport Layer Security"],
        mitigation="Promover esquemas HTTPS.",
        confidence=1.0,
    ),
]


def get_rules(enabled_only: bool = True) -> list[RuleSpec]:
    return [r for r in CATALOG_V1 if not enabled_only or r.enabled]
