# 4. Pipeline de Procesamiento

> **Capítulo 4 de 15** — El pipeline que transforma el tráfico HTTP capturado en conocimiento estructurado. Detalle de cada etapa: importación, normalización, extracción de entidades, correlación y materialización.

---

## 4.1 Visión general

El pipeline es la tubería central del sistema. Cada etapa consume un contrato y produce otro, avanzando el estado de una importación desde `PENDING` hasta `COMPLETED`.

```mermaid
flowchart LR
    A[Import] --> B[Parse & Validate]
    B --> C[Normalize Routes]
    C --> D[Extract Entities]
    D --> E[Correlate]
    E --> F[Materialize Graph]
    F --> G[Run Rules]
    G --> H[Import COMPLETED]
```

| Etapa | Contrato de entrada | Contrato de salida | Estado de import |
|-------|--------------------|--------------------|------------------|
| Import | Archivo (Burp/HAR/...) | `ImportRecord` | `PENDING` |
| Parse & Validate | `ImportRecord` + archivo | `HttpExchange[]` | `PARSING` → `PARSED` |
| Normalize | `HttpExchange[]` | `EndpointTemplate[]` | `NORMALIZING` → `NORMALIZED` |
| Extract | Exchanges + templates | `EntityOccurrence[]` | `EXTRACTING` → `EXTRACTED` |
| Correlate | Ocurrencias + templates | `GraphEdge[]` (con confianza) | `CORRELATING` → `CORRELATED` |
| Materialize | `GraphEdge[]` | Grafo en Neo4j | `MATERIALIZING` → `MATERIALIZED` |
| Rules | Grafo | `Alert[]` | `RULES` → `COMPLETED` |

> Cada etapa es un **worker** independiente (ADR-004) y **idempotente** (PR-05): re-procesar un shard no duplica resultados.

---

## 4.2 Etapa 0 — Importación

### 4.2.1 Contrato de entrada

Archivo de exportación subido por el analista. En v0.1 solo Burp Logger (JSON y CSV de Burp). La API acepta `multipart/form-data` con límite configurable (default 2 GB).

### 4.2.2 Adaptadores de importación

Cada adaptador implementa la interfaz:

```python
class ImportAdapter(Protocol):
    format: FormatEnum
    def parse(self, stream: BinaryIO) -> Iterator[RawExchange]: ...

    def validate(self, stream: BinaryIO) -> ValidationReport: ...
```

| Adaptador | Formato | Estado |
|-----------|---------|--------|
| `BurpJsonAdapter` | JSON exportado por Burp Logger | v0.1 |
| `BurpCsvAdapter` | CSV de Burp Logger | v0.1 |
| `HarAdapter` | HAR 1.2 | v2.0 |
| `OpenApiAdapter` | OpenAPI 3.x / Swagger | v2.0 |
| `PostmanAdapter` | Postman Collection | v2.0 |
| `MitmproxyAdapter` | flujo de mitmproxy | v2.0 |
| `PcapAdapter` | PCAP/PCAPng | v3.0 |
| `OtelAdapter` | spans de OpenTelemetry | v3.0 |

### 4.2.3 Modelo canónico `HttpExchange`

El formato canónico intermedio que el núcleo procesa:

```yaml
exchange_id: uuid
import_id: uuid
order: int                  # posición cronológica en el dataset
timestamp: rfc3339
client_ip: "10.0.0.5"
host: "api.example.com"
port: 443
scheme: "https"
method: "GET"
path: "/users/15/orders/42"
query_string: "?include=items"
template: "/users/{id}/orders/{orderId}"   # se llena en normalize
path_params: {"id": "15", "orderId": "42"}
request:
  headers: {":authority": "...", "authorization": "Bearer <JWT>", ...}
  cookies: {session: "abc123"}
  content_type: "application/json"
  body: {bytes_base64?, json?: {...}, text?: "..."}
  has_json: true
response:
  status_code: 200
  status_text: "OK"
  headers: {content-type: "application/json", set-cookie: [...]}
  content_type: "application/json"
  body: {json?: {...}, text?: "..."}
  has_json: true
timings:
  total_ms: 128
```

### 4.2.4 Validación

- Formato reconocido (magic bytes / estructura).
- Integridad: cada `RawExchange` válido tiene método, ruta y host.
- Registro de errores de parseo por entrada (`parse_errors`), sin abortar la importación (PR-12).

---

## 4.3 Etapa 1 — Normalización de rutas

### 4.3.1 Objetivo

Convertir rutas concretas en **plantillas de recursos** para identificar endpoints (recursos) en lugar de peticiones individuales (ADR-007).

### 4.3.2 Algoritmo

**Paso 1 — Segmentación y clasificación.**

Cada segmento de la ruta se clasifica:

| Clase | Patrón (regex) | Ejemplo |
|-------|----------------|---------|
| `fixed` | No coincide con ningún dinámico | `users`, `orders` |
| `numeric` | `^\d+$` | `15`, `912` |
| `uuid` | UUID v4/v5/v7 | `a1b2c3d4-...` |
| `hash_hex` | `^[a-f0-9]{16,}$` | `8f3c2d1a...` |
| `hash_b64url` | `^[A-Za-z0-9_-]{16,}$` | `lZvH1xK...` |
| `mixed` | Otros valores dinámicos | `user_15`, `2026-08` |

**Paso 2 — Agregación por (method, pattern).**

Se agrupan las rutas por método y patrón de segmentos. Un segmento es **dinámico** si, en su posición, se observan **≥ 3 valores distintos** y su cardinalidad relativa supera un umbral (configurable, default 60% de variabilidad).

**Paso 3 — Generación de la plantilla.**

Los segmentos dinámicos se nombran semánticamente cuando es posible:

| Heurística | Nombre |
|------------|--------|
| UUID → `{id}` | `{id}` |
| Numérico precedido de entidad en plural (`/users/15`) | `{userId}` |
| Precedido de entidad en singular (`/user/15`) | `{userId}` |
| Contexto general → `{paramN}` | `{param0}` |

**Paso 4 — Registro de valores.**

Cada valor concreto se persiste como `path_param_value` por exchange y como `EndpointValue` (valores únicos observados por endpoint).

### 4.3.3 Mitigación de sobre-normalización

- Umbral de cardinalidad configurable por importación.
- Lista de **segmentos protegidos** (p. ej., `api`, `v1`, `v2`, `admin`, `health`) nunca se templatizan.
- Almacenamiento del patrón "puro" y del "restringido" para comparación.

### 4.3.4 Contrato de salida

```yaml
endpoint_template:
  template_id: uuid
  import_id: uuid
  method: "GET"
  pattern: "/users/{userId}/orders/{orderId}"
  host_pattern: "{subdomain}.example.com"
  segments:
    - {index: 0, class: "fixed", value: "users"}
    - {index: 1, class: "numeric", param: "userId"}
    - {index: 2, class: "fixed", value: "orders"}
    - {index: 3, class: "uuid", param: "orderId"}
  cardinality: {exchanges: 152, distinct_users: 87}
  confidence: "EVIDENCIA"
```

---

## 4.4 Etapa 2 — Extracción de Entidades

### 4.4.1 Objetivo

Detectar en cada exchange las entidades que alimentarán el grafo (ADR-008). La extracción opera sobre cabeceras, cookies, query params, cuerpo JSON y rutas.

### 4.4.2 Tipos de extracción

| Tipo | Fuente | Detección | Ejemplo |
|------|--------|-----------|---------|
| `jwt` | Cabecera `Authorization`, cookie, body | Decodificación de estructura JWT (3 partes, payload JSON) | `eyJhbGciOi...` |
| `api_key` | Cabecera `X-API-Key`, `X-Api-Key`, query | Patrón de key | `sk_live_...`, `ak_...` |
| `bearer_token` | `Authorization: Bearer` | Estructura token opaca | `Bearer 9f3c...` |
| `cookie` | Cabecera `Cookie`, `Set-Cookie` | Parseo de cookies | `session=abc123` |
| `session_id` | Cuerpo/cookie | Nombres y patrones (`sid`, `session`, `PHPSESSID`) | `PHPSESSID=xyz` |
| `oauth_token` | Cabecera `Authorization: OAuth`, body | Estructura OAuth (access_token, refresh_token) | `OAuth xyz` |
| `json_id` | Cuerpo JSON | Campos con sufijo `_id`/`Id`/`ID` o nombres conocidos | `customerId`, `orderId` |
| `json_object_ref` | Cuerpo JSON | Campos que son referencias a otras entidades (URLs relativas) | `"/users/15"` |
| `role` | Claims JWT, body | Claims `role`, `roles`, `permissions` | `"admin"`, `"user"` |
| `scope` | Claims JWT, body | Claims `scope`, `scopes` | `"read:orders"` |
| `param` | Query/body | Nombres de parámetro reutilizados | `page`, `limit`, `sort` |
| `file_ref` | Respuesta | `content-disposition`, `content-type` no-JSON | `report.pdf` |
| `host` | Request | Parseo de host | `api.example.com` |
| `service` | Host/subdominio | Agrupación de hosts | `orders-service` |
| `sensitive_field` | Cuerpo JSON | Lista de campos sensibles (reglas) | `creditCard`, `ssn`, `password` |

### 4.4.3 Paths canónicos

Para cada valor extraído del cuerpo JSON se registra su **path canónico** (JSONPath simplificado):

```
$.data.customer.id       → {path: "$.data.customer.id", value: "c_1001", type: "json_id"}
$.items[].productId      → {path: "$.items[*].productId", value: "p_55", type: "json_id"}
```

El path se **abstrae** reemplazando índices de array por `[*]` para correlacionar por forma, no por posición.

### 4.4.4 Contrato de salida: `EntityOccurrence`

```yaml
occurrence_id: uuid
exchange_id: uuid
entity_type: "json_id"
entity_label: "customerId"          # nombre derivado
value: "c_1001"
value_hash: "sha256:..."            # hash del valor para correlación privada
path: "$.data.customer.id"
location: "response.body"           # request/response/header/cookie/query/path
sensitive: false
confidence: "EVIDENCIA"
```

### 4.4.5 Redacción y hashing (privacidad)

Los valores clasificados como sensibles (tokens, secretos) se almacenan **solo como hash** en `entity_occurrences` cuando la política de privacidad lo exige. La correlación usa el hash (función de huella estable). Ver capítulo 11.

---

## 4.5 Etapa 3 — Correlación

> Detalle completo en `07-motor-de-correlacion.md`. Resumen de lo que hace esta etapa:

1. **Agrupa ocurrencias** por `(entity_type, entity_label, value_hash)`.
2. **Genera nodos** (upsert) para cada entidad nueva.
3. **Genera relaciones** entre nodos (token→endpoint, endpoint→recurso, recurso→recurso, flujo temporal, etc.).
4. **Calcula confianza** (`EVIDENCIA`/`INFERENCIA`) y `score` de cada relación.
5. **Genera hipótesis** de recursos no observados (a partir de patrones REST).

Salida: `GraphEdge[]` con metadatos de confianza y evidencias.

## 4.6 Etapa 4 — Materialización del grafo

- Traduce `GraphEdge[]` a operaciones Cypher **batch** (UNWIND).
- Upsert por clave natural: `MERGE (n:Label {key: $key}) SET n += $props`.
- Cada nodo/relación referencia `import_id` y `exchange_id` para trazabilidad.
- Al finalizar, se ejecuta `CALL db.awaitIndexes()` y `OPTIONAL MATCH` de conteo para el reporte.

### 4.6.1 Operaciones por claves naturales

| Tipo de nodo | Clave natural |
|--------------|---------------|
| `Host` | `(name)` |
| `Endpoint` | `(method, pattern, host)` |
| `Entity` | `(entity_type, entity_label, value_hash)` |
| `Service` | `(name)` |
| `Resource` | `(resource_key)` |
| `Session` | `(session_id)` |
| `Token` | `(value_hash, token_type)` |

Ver definiciones completas en capítulo 6.

---

## 4.7 Etapa 5 — Motor de reglas

> Detalle completo en `08-motor-de-reglas.md`.

Ejecuta el catálogo de reglas sobre el grafo materializado. Genera `Alert[]` con severidad, descripción, evidencia y contexto (subgrafo). El resultado se persiste en PostgreSQL y se indexa en Neo4j (opcional, para consultas de contexto).

## 4.8 Manejo de errores y reanudación

### 4.8.1 Errores por etapa

| Fallo | Comportamiento |
|-------|----------------|
| Parseo de un exchange corrupto | Se registra `parse_error`, se continúa (PR-12) |
| Worker crashea a mitad de etapa | El trabajo se reintenta (at-least-once), upsert idempotente |
| Etapa agota reintentos | `import.status = FAILED`, `stage_error` poblado, DLQ |
| Neo4j no disponible | Backoff y reintentos; si persiste, import queda `PAUSED` |

### 4.8.2 Reanudación

`import_stages` registra el progreso por etapa y shard. Re-subir la misma importación (mismo `import_id`) o pulsar "reanudar" continúa desde el último estado consistente.

## 4.9 Rendimiento del pipeline

### 4.9.1 Cuellos de botella esperados y mitigación

| Cuello de botella | Mitigación |
|-------------------|------------|
| Parsing de cuerpos JSON grandes | `orjson`, streaming por shard, skip de bodies si `config.skip_large_bodies` |
| Normalización de rutas | Agregación en memoria por shard; estructura de trie para patrones |
| Extracción de entidades | Path canónicos computados una sola vez por exchange |
| Escritura masiva en Neo4j | `UNWIND` batch de 1000 edges; `per-import` MERGE |
| Correlación por valor | Índices hash en `entity_occurrences`; agrupación por (type,label,hash) |

### 4.9.2 Estimaciones (hardware de referencia 3.8.3)

| Dataset | Tiempo estimado |
|---------|-----------------|
| 10k exchanges | < 60 s |
| 100k exchanges | < 10 min |
| 1M exchanges | ~ 90 min (con sharding) |

## 4.10 Contratos de configuración por etapa

```yaml
pipeline:
  chunk_size: 5000
  retries: 3
  backoff_base_ms: 500
  normalize:
    min_distinct_values_for_dynamic: 3
    variability_threshold: 0.6
    protected_segments: [api, v1, v2, v3, admin, health, public]
  extract:
    skip_large_bodies_bytes: 5242880
    sensitive_fields: [password, token, apiKey, secret, creditCard, ssn]
    hash_only_entities: [jwt, api_key, bearer_token, session_id, oauth_token]
  correlate:
    min_occurrences_for_inference: 2
    session_window_minutes: 30
    max_depth_for_views: 5
  rules:
    enabled_ruleset: default
```
