# 15. Glosario y Apéndices

> **Capítulo 15 de 15** — Glosario de términos, apéndices técnicos de referencia y plantillas para la implementación.

---

## 15.1 Glosario

| Término | Definición |
|---------|------------|
| **BOLA** | Broken Object Level Authorization — vulnerabilidad OWASP API-1 (acceso a objetos sin autorización). Sinónimo de IDOR en APIs. |
| **BodyField** | Nodo del grafo que representa un campo canónico de un cuerpo JSON observado en un endpoint. |
| **Confianza (nivel)** | Atributo de nodos/relaciones: `EVIDENCIA`, `INFERENCIA`, `HIPOTESIS`. |
| **Cypher** | Lenguaje de consulta de Neo4j usado por la API, el motor de reglas y la consola de la UI. |
| **Endpoint Template** | Plantilla de recurso (`GET /users/{id}`) derivada de la normalización de rutas. |
| **Evidencia** | Información observada directamente en el tráfico que sustenta una relación. |
| **Exchange** | Unidad canónica de tráfico: una petición y su respuesta (`HttpExchange`). |
| **Familia de equivalencia** | Conjunto de nombres de campo que se consideran el mismo concepto (`customerId`, `customer_id`). |
| **Golden dataset** | Conjunto de datos de referencia etiquetado para medir precisión/recall de correlación y reglas. |
| **IDOR** | Insecure Direct Object Reference — acceso directo a objetos mediante IDs manipulables. |
| **Materializer** | Etapa que escribe nodos y relaciones en Neo4j a partir de las relaciones calculadas. |
| **Path canónico** | Ruta normalizada dentro de un cuerpo JSON (`$.data.customer.id`), con arrays abstraídos a `[*]`. |
| **Pipeline** | Secuencia de etapas que transforma el tráfico importado en grafo de conocimiento. |
| **Resource** | Entidad de negocio identificada (un `customerId`, un `orderId`) como nodo del grafo. |
| **Ruleset** | Conjunto de reglas activas en un workspace o perfil de cumplimiento. |
| **Shard** | Porción de trabajo de una importación procesada por un worker (chunk de exchanges). |
| **Subgrafo** | Porción del grafo serializada para una vista o para el contexto de una alerta. |
| **value_hash** | SHA-256 del valor normalizado; permite correlación sin exponer el valor. |
| **Workspace** | Unidad de organización del trabajo (un proyecto de auditoría). |

## 15.2 Apéndice A — Normalización de rutas: algoritmo de detección de segmentos

Pseudocódigo de clasificación y templating:

```
function segment_class(segment):
    if is_uuid(segment):          return 'uuid'
    if is_numeric(segment):       return 'numeric'
    if is_hex_hash(segment):      return 'hash_hex'
    if is_b64url_hash(segment):   return 'hash_b64url'
    if is_date_like(segment):     return 'date'
    if is_semver(segment):        return 'version'
    return 'fixed'

function build_templates(exchanges):
    groups = group_by(exchanges, key=(method, host, path_segments_length))
    for g in groups:
        for position in range(len):
            values = distinct(g[position])
            cardinality = len(values)
            if cardinality >= MIN_DISTINCT and
               cardinality / total >= VARIABILITY_THRESHOLD and
               segment_class(values[0]) != 'fixed':
                mark_dynamic(g, position, semantic_name(values, neighbors))
        template = join_segments(g, dynamic → {param})
        yield template
```

## 15.3 Apéndice B — Detección de JWT

- **Formato**: `header.payload.signature` (3 partes separadas por `.`), `header.payload` decodificables como JSON base64url.
- **Header**: `alg`, `typ`.
- **Payload** (claims estándar): `iss`, `sub`, `aud`, `exp`, `nbf`, `iat`, `jti`; claims de negocio: `roles`, `scope`, `scopes`, `permissions`, `tenant`, `org`.
- **Extracción**:
  - `value_hash` del token completo.
  - `claims_fingerprint_hash` = hash de `(alg, iss, sub, aud, exp)` para agrupar tokens con los mismos claims.
  - Claims sensibles (como `roles`, `scope`) se almacenan como nombres + valores en `entity_occurrences` (hash-only si la política lo exige).
- **Contexto de aparición**: `header.authorization` → `CONSUMES`; `response.body`/`response.header` → `EMITS`.

## 15.4 Apéndice C — Familias de equivalencia de labels

Reglas de canonicalización de nombres de campo:

1. `snake_case` y `camelCase` → unificar a `snake_case`.
2. Eliminar sufijos: `_id`, `Id`, `ID`, `Uuid`, `Ref`, `Reference`, `Key`.
3. Si el resultado es genérico (`id`, `uuid`), usar el contexto del path: `$.data.customer.id` → `customerId`.
4. Sinónimos de dominio configurables (`documentId ↔ docId`).

```python
def family_of(label, path):
    norm = normalize_case(label)          # "customerId" -> "customer_id"
    norm = strip_suffix(norm)             # -> "customer"
    if norm in {"id", "uuid", "key"}:
        return family_from_path(path)     # "customer" de "$.data.customer.id"
    return norm
```

## 15.5 Apéndice D — Catálogo de señales de AuthFlow

| Señal | Regla de detección |
|-------|--------------------|
| `login` | `POST` con credenciales en body + `EMITS` de token en respuesta |
| `refresh` | `POST` con `refresh_token` → `EMITS` nuevo access token + `REFRESHES` |
| `logout` | `POST` que invalida token/sesión (respuesta 204/200 + `Set-Cookie` borrada) |
| `oauth` | `grant_type` en body/query (`authorization_code`, `client_credentials`, `password`) |
| `callback` | GET con `code`/`state` en query (flujo OAuth redirect) |

## 15.6 Apéndice E — Plantilla de ADR

```markdown
### ADR-NNN — Título de la decisión
Estado: Propuesto | Aceptado | Reemplazado por ADR-MMM
Fecha: YYYY-MM-DD

#### Contexto
...

#### Decisión
...

#### Consecuencias
Positivas: ...
Negativas: ...

#### Alternativas consideradas
- ...
```

## 15.7 Apéndice F — Plantilla de regla (YAML)

```yaml
rule_id: R-XXX-001
version: 1
name: "..."
category: ...
severity: ...
enabled: true
description: >
  ...
when:
  - match: "MATCH ... RETURN ..."
where: {}
group_by: []
emit:
  title: "..."
  severity: ...
  evidence: {exchange_ids: true, node_keys: true}
  references: []
mitigation: "..."
```

## 15.8 Apéndice G — Fixtures y datasets de prueba

| Dataset | Origen | Uso |
|---------|--------|-----|
| `synthetic_10k.json` | Generador sintético (configurable) | CI, demo, smoke tests |
| `golden_v0.json` | Etiquetado manual (~5k) | Métricas tempranas de correlación |
| `golden_v1.json` | Etiquetado ampliado (~50k) | Validación de v1.0 |
| `burp_sample.json` | Export real anonimizado | Integración Burp |

El generador sintético produce APIs REST ficticias (usuarios, pedidos, pagos, facturas) con flujos de auth, tokens JWT y reutilización de recursos controlada.

## 15.9 Apéndice H — Estructura de directorios propuesta del repo

```
api_Grapher/
├── docs/
│   └── sad/                     # este documento (capítulos 1–15)
├── api/
│   ├── routes/                  # routers FastAPI (imports, graph, alerts, ...)
│   ├── contracts/               # openapi.v1.yaml, schemas
│   └── deps/                    # auth, rate limit, tracing
├── pipeline/
│   ├── importers/               # burp_json, burp_csv, har, ...
│   ├── normalize/
│   ├── extract/
│   ├── correlate/
│   ├── materialize/
│   └── rules/
├── engine/
│   ├── graph/                   # GraphRepository (Neo4j)
│   ├── evidence/                # EvidenceRepository (PostgreSQL)
│   └── identity/                # normalización de valores, familias
├── ui/
│   └── src/                     # frontend React
├── schemas/
│   ├── postgres/                # migraciones Alembic
│   └── neo4j/                   # scripts Cypher por versión
├── rules/
│   └── catalog/                 # reglas YAML versionadas
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── golden/                  # datasets etiquetados
├── deploy/
│   ├── compose/
│   ├── helm/                    # v3+
│   └── monitoring/
└── .github/workflows/           # CI/CD
```

## 15.10 Referencias externas

| Referencia | Tema |
|------------|------|
| OWASP API Security Top 10 (2023) | Categorías de riesgo (BOLA, BFLA, Broken Auth...) |
| RFC 7519 | JSON Web Token |
| RFC 6750 | Bearer Token Usage |
| RFC 9110 / 9112 | HTTP Semantics / HTTP/1.1 |
| RFC 6455 | WebSockets (futuro) |
| HAR 1.2 spec | HTTP Archive format |
| OpenTelemetry spec | Trazas/métricas del pipeline |
| Neo4j docs | Cypher, APOC, GDS |

## 15.11 Índice de decisiones y códigos usados en el documento

| Código | Tipo |
|--------|------|
| ADR-001…012 | Decisiones de arquitectura (capítulo 2) |
| PR-01…12 | Principios arquitectónicos (capítulo 2) |
| NO-1…4 / TO-1…7 | Objetivos de negocio/técnicos (capítulo 1) |
| NG-1…6 | Non-goals (capítulo 1) |
| HIP-H1…5 | Hipótesis (capítulo 1) |
| Q1…Q7 | Preguntas problema (capítulo 1) |
| R-XXX-NNN | Reglas (capítulo 8) |
| R-01…15 / RI-01…03 | Riesgos (capítulo 14) |
