# 9. API Interna

> **Capítulo 9 de 15** — Especificación de la API REST interna que expone toda la funcionalidad de la plataforma (API-first, ADR-012). Contratos OpenAPI versionados por URL.

---

## 9.1 Principios

- **API-first** (PR-02): toda funcionalidad es invocable por API; la UI consume estos contratos.
- **Versionado por URL**: `/api/v1/...`.
- **OpenAPI 3.1**: contrato generado por FastAPI, versionado en `api/contracts/openapi.v1.yaml`.
- **Convenciones REST**: recursos plurales, verbos HTTP correctos, códigos de estado semánticos.
- **Idempotencia**: `POST` de creación con `Idempotency-Key` opcional.
- **Paginación por cursor** para listados grandes.
- **Auth de la API**: en v1, clave API local o token de sesión (capítulo 11). En v2+, autenticación multiusuario.

## 9.2 Convenciones generales

| Aspecto | Convención |
|---------|------------|
| Base path | `/api/v1` |
| Formato | `application/json` |
| Timestamps | RFC 3339 UTC |
| IDs | UUID v7 |
| Paginación | `?limit=50&cursor=...` → respuesta con `next_cursor` |
| Filtros | query params tipados (`?status=OPEN&severity=ALTA`) |
| Ordenación | `?sort=-timestamp` (prefijo `-` = desc) |
| Errores | Envelope `{error: {code, message, details?}}` |
| Rate limit | 100 req/min por workspace (v1, ajustable) |

## 9.3 Modelo de errores

```jsonc
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Import no encontrado: 018f...",
    "details": { "import_id": "018f..." }
  }
}
```

| Código | HTTP | Significado |
|--------|------|-------------|
| `VALIDATION_ERROR` | 422 | Campos inválidos |
| `RESOURCE_NOT_FOUND` | 404 | No existe |
| `IMPORT_IN_PROGRESS` | 409 | Importación ya en curso |
| `IMPORT_FAILED` | 422 | No se puede operar sobre import fallido |
| `UNAUTHORIZED` | 401 | Auth requerida |
| `FORBIDDEN` | 403 | Sin permisos sobre el recurso |
| `RATE_LIMITED` | 429 | Límite superado |
| `INTERNAL` | 500 | Error inesperado |

## 9.4 Endpoints

### 9.4.1 Workspaces

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/v1/workspaces` | Lista de workspaces |
| `POST` | `/api/v1/workspaces` | Crear workspace |
| `GET` | `/api/v1/workspaces/{id}` | Detalle |
| `PATCH` | `/api/v1/workspaces/{id}` | Actualizar (config) |
| `DELETE` | `/api/v1/workspaces/{id}` | Eliminar (cascade) |

### 9.4.2 Importaciones

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/api/v1/imports` | Subir archivo y crear importación (multipart) |
| `GET` | `/api/v1/imports` | Lista con filtros (`status`, `workspace_id`) |
| `GET` | `/api/v1/imports/{id}` | Detalle + progreso + totals |
| `POST` | `/api/v1/imports/{id}/resume` | Reanudar import fallida/pausada |
| `DELETE` | `/api/v1/imports/{id}` | Eliminar import + evidencias + subgrafo |
| `GET` | `/api/v1/imports/{id}/stages` | Progreso por etapa |
| `GET` | `/api/v1/imports/{id}/parse-errors` | Errores de parseo |

**Ejemplo de creación de importación:**

```http
POST /api/v1/imports
Content-Type: multipart/form-data

file: burp_export.json
workspace_id: 018f...
source_format: burp_json
config: {"normalize":{"protected_segments":["api","v1"]}}
```

**Respuesta 201:**

```jsonc
{
  "id": "018f...",
  "status": "PENDING",
  "source_format": "burp_json",
  "created_at": "2026-08-03T10:00:00Z",
  "status_url": "/api/v1/imports/018f...",
  "events_stream": "/api/v1/imports/018f.../events"
}
```

**Streaming de progreso (SSE):**

```
GET /api/v1/imports/{id}/events
→ event: stage.update
  data: {"stage":"correlate","shard":3,"status":"DONE","processed":5000}
→ event: import.completed
  data: {"totals":{"exchanges":100000,"nodes":12000,"edges":48000}}
```

### 9.4.3 Grafo (consulta)

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/v1/graph/summary` | Estadísticas del grafo de un workspace/import |
| `POST` | `/api/v1/graph/query` | Consulta Cypher con sandbox (body `{cypher, params, limit}`) |
| `GET` | `/api/v1/graph/node/{id}` | Detalle de nodo (todas las props) |
| `GET` | `/api/v1/graph/node/{id}/neighbors` | Vecinos a 1 salto (con tipos de relación) |
| `POST` | `/api/v1/graph/neighborhood` | Vecindario a profundidad N de un conjunto de nodos |
| `GET` | `/api/v1/graph/path` | Camino más corto entre dos nodos (`from`, `to`, `maxDepth`) |
| `POST` | `/api/v1/graph/entities/resolve` | Resolución de una entidad por valor (hash) |

**Consultas tipo "pregunta de auditor":**

| Problema de negocio | Endpoint/consulta |
|---------------------|-------------------|
| ¿Qué endpoints usan este JWT? | `POST /graph/query` con patrón `CONSUMES` |
| Recorrido de un objeto | `GET /graph/path` + `neighborhood` |
| Recursos en varios módulos | `GET /graph/summary` + filtro por `LINKS_TO` |
| Permisos | `GET /graph/node/{id}/neighbors` con `GRANTS`/`PROTECTS` |

### 9.4.4 Entidades (evidencia)

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/v1/entities` | Búsqueda de entidades (por tipo, label, valor/hash) |
| `GET` | `/api/v1/entities/{id}` | Detalle de entidad + ocurrencias |
| `GET` | `/api/v1/entities/{id}/occurrences` | Ocurrencias con paginación |
| `GET` | `/api/v1/exchanges/{id}` | Exchange completo (request/response, con redacción) |
| `GET` | `/api/v1/exchanges/{id}/headers` | Cabeceras |
| `GET` | `/api/v1/exchanges/{id}/body` | Cuerpo (aplicando política de redacción) |
| `GET` | `/api/v1/exchanges` | Filtro por `template_id`, `host`, `status_code`, `timestamp` |

### 9.4.5 Endpoints y plantillas

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/v1/endpoints` | Lista de `EndpointTemplate` con filtros (method, host, pattern) |
| `GET` | `/api/v1/endpoints/{id}` | Detalle + cardinalidad + segmentos |
| `GET` | `/api/v1/endpoints/{id}/values` | Valores únicos por parámetro (`endpoint_values`) |
| `GET` | `/api/v1/endpoints/{id}/exchanges` | Exchanges agrupados bajo el endpoint |

### 9.4.6 Alertas

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/v1/alerts` | Filtros: `import_id`, `severity`, `status`, `category`, `rule_id` |
| `GET` | `/api/v1/alerts/{id}` | Detalle + evidencia + contexto |
| `PATCH` | `/api/v1/alerts/{id}` | Cambiar `status`, añadir notas/etiquetas |
| `POST` | `/api/v1/alerts/{id}/context` | Generar `context_subgraph` a demanda |
| `GET` | `/api/v1/alerts/export` | Exportar alertas (JSON/CSV/Markdown) |

### 9.4.7 Reglas

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/v1/rules` | Catálogo (filtro por categoría/enabled) |
| `GET` | `/api/v1/rules/{rule_id}` | Detalle de regla + versión |
| `POST` | `/api/v1/rules` | Crear regla personalizada (validada) |
| `PATCH` | `/api/v1/rules/{rule_id}` | Habilitar/deshabilitar, actualizar |
| `POST` | `/api/v1/rules/{rule_id}/dry-run` | Ejecutar sobre import sin persistir alertas |
| `GET` | `/api/v1/rules/categories` | Categorías disponibles |
| `GET` | `/api/v1/rules/schema` | JSON Schema del DSL (para autocompletado UI) |

### 9.4.8 Vistas

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/api/v1/views/auth-flow` | Subgrafo del flujo de autenticación de un import |
| `POST` | `/api/v1/views/resources` | Subgrafo de recursos de negocio |
| `POST` | `/api/v1/views/infrastructure` | Subgrafo de infraestructura |
| `POST` | `/api/v1/views/permissions` | Subgrafo de permisos |
| `GET` | `/api/v1/views/timeline` | Secuencia de exchanges (paginada, por principal/sesión) |
| `GET` | `/api/v1/views/insights` | Resumen de preguntas frecuentes (top tokens, top recursos, ...) |

Cada endpoint de vista acepta `{import_id, filters, max_depth, max_nodes}` y devuelve el subgrafo serializado en formato Cytoscape.

## 9.5 Contratos detallados (ejemplos)

### 9.5.1 `POST /api/v1/graph/query`

```jsonc
// Request
{
  "cypher": "MATCH (t:AKG:Token)-[:AKG:CONSUMES]->(e:AKG:Endpoint) WHERE t.value_hash=$h AND e.import_id=$i RETURN e.method, e.pattern, count(*) AS uses ORDER BY uses DESC",
  "params": {"h": "sha256:...", "i": "018f..."},
  "limit": 50,
  "timeout_ms": 10000
}
// Response
{
  "columns": ["e.method", "e.pattern", "uses"],
  "rows": [["GET", "/users/{id}", 42], ["POST", "/orders", 9]],
  "stats": {"nodes_touched": 300, "elapsed_ms": 12}
}
```

> `graph/query` está **restringido a lectura** (sandbox idéntico al del motor de reglas). No se permite `CREATE/DELETE/SET`.

### 9.5.2 `GET /api/v1/alerts`

```
?import_id=018f...&severity=ALTA&status=OPEN&sort=-priority_score&limit=50&cursor=...
```

```jsonc
{
  "items": [{
    "id": "uuid",
    "rule_id": "R-IDOR-001",
    "severity": "ALTA",
    "status": "OPEN",
    "title": "IDOR potencial: /users/{id} accede a customer",
    "priority_score": 6,
    "created_at": "2026-08-03T10:05:00Z",
    "evidence": {"exchange_ids": ["018f..."], "node_keys": ["018f:Endpoint:..."]},
    "mitigation": "Validar autorización a nivel de objeto."
  }],
  "next_cursor": "abc...",
  "total": 12
}
```

## 9.6 Autenticación y autorización de la API

| Versión | Mecanismo |
|---------|-----------|
| v0.1–v1.0 | Clave API de workspace (configurable) o acceso local sin auth (modo dev) |
| v2.0 | Usuarios + sesiones JWT propias, roles (`admin`, `auditor`, `viewer`) |
| v3.0 | SSO (OIDC), RBAC por workspace, auditoría de accesos |

En v1, las operaciones destructivas (`DELETE import`, `DELETE workspace`) requieren la clave de workspace confirmada (`X-Confirm`).

## 9.7 Limitaciones y SLOs de la API

| Recurso | Límite |
|---------|--------|
| Tamaño de subida | 2 GB (configurable) |
| `graph/query` filas | 10.000 |
| `graph/query` timeout | 15 s |
| Profundidad máxima de vistas | 5 |
| Máximo de nodos en contexto de alerta | 200 |
| Rate limit | 100 req/min (v1) |

## 9.8 Versionado de contratos

| Contrato | Ruta en repo | Uso |
|----------|--------------|-----|
| OpenAPI v1 | `api/contracts/openapi.v1.yaml` | v1.0 |
| JSON Schema DSL de reglas | `api/contracts/rule.schema.json` | v1.0 |
| Modelo canónico `HttpExchange` | `api/contracts/http-exchange.schema.json` | v0.1+ |
| Mensajes de eventos | `api/contracts/events.schema.json` | v0.1+ |

Cambios breaking requieren nueva versión (`/api/v2/...`) con período de compatibilidad.

## 9.9 SDK / herramientas derivadas

- Cliente Python generado desde OpenAPI (para scripting de auditoría).
- CLI `akg` (v2+) que envuelve la API para operaciones de línea de comandos.
- Webhooks (v3+) para notificación de alertas a SIEM/ticketing.
