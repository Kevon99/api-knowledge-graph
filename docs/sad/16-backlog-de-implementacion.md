# 16. Backlog de Implementación

> **Capítulo 16 de 16** — Plan de trabajo accionable: tareas ordenadas por versión y por dependencia, para empezar a programar de forma ordenada. Complementa el capítulo 13 (hoja de ruta).

---

## 16.1 Cómo usar este backlog

- Cada tarea tiene un **ID estable** (`V0.1-01`) para referenciarla en issues, commits y sprints.
- Ordenadas por **dependencia** dentro de cada versión: nada se construye antes que su base.
- Cada tarea indica **qué capítulo del SAD** la define (trazabilidad).
- Prioridad: `P0` (bloqueante), `P1` (importante), `P2` (deseable).

Convención de etiquetas sugerida para el tracker (GitHub Projects / issues):

```
estado: 📋 Backlog | 🚧 En curso | ✅ Hecho
prioridad: P0 / P1 / P2
version: v0.1 / v1.0 / v2.0 / v3.0
area: pipeline | api | ui | infra | rules | graph | data
```

---

## 16.2 Fase 0 — Bootstrap del repo (antes de v0.1)

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| B-01 | Crear estructura de directorios del monorepo | infra | P0 | 15.9 |
| B-02 | Configurar Python 3.11 + pyproject (ruff, mypy, pytest) | infra | P0 | 2.8 |
| B-03 | Configurar pre-commit y CI básico (lint + test) | infra | P0 | 12.5 |
| B-04 | Docker Compose base (postgres, neo4j, redis) con perfiles | infra | P0 | 12.1 |
| B-05 | Migraciones Alembic iniciales (tablas base vacías) | data | P0 | 5.6 |
| B-06 | Scripts Cypher de esquema `schemas/neo4j/v1.cypher` | graph | P0 | 6.6 |
| B-07 | Configuración central `config.py` + `.env.example` | infra | P1 | 3.9 |
| B-08 | Logger de trazas (structlog) + request_id | infra | P1 | 12.4 |
| B-09 | Generador de dataset sintético (10k exchanges) | data | P1 | 15.8 |

---

## 16.3 v0.1 — Prototipo

### 16.3.1 Importación y parseo

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V0.1-01 | Modelo canónico `HttpExchange` (Pydantic) + esquema JSON | data | P0 | 4.2.3 |
| V0.1-02 | `BurpJsonAdapter` → `RawExchange[]` | pipeline | P0 | 4.2.2 |
| V0.1-03 | Validación de integridad + `parse_errors` | pipeline | P0 | 4.2.4 |
| V0.1-04 | Persistencia de `http_exchanges`, `http_headers`, `http_cookies` | data | P0 | 5.3 |
| V0.1-05 | Persistencia de `body_json` (JSONB) | data | P1 | 5.3.7 |
| V0.1-06 | `BurpCsvAdapter` | pipeline | P2 | 4.2.2 |

### 16.3.2 Normalización de rutas

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V0.1-07 | Clasificador de segmentos (fixed/numeric/uuid/hash/mixed) | pipeline | P0 | 4.3.2 |
| V0.1-08 | Generación de plantillas por (method, host, pattern) | pipeline | P0 | 4.3.2 |
| V0.1-09 | `endpoint_templates` + `endpoint_values` | data | P0 | 5.3.9–10 |
| V0.1-10 | Segmentos protegidos + umbrales configurables | pipeline | P1 | 4.3.3 |
| V0.1-11 | Naming semántico básico de parámetros (`{id}`) | pipeline | P1 | 4.3.2 |

### 16.3.3 Extracción de entidades

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V0.1-12 | Detector de JWT (estructura + claims) | pipeline | P0 | 15.3 |
| V0.1-13 | Detector de cookies y sesiones | pipeline | P0 | 4.4.2 |
| V0.1-14 | Extractor de `json_id` con paths canónicos | pipeline | P0 | 4.4.3 |
| V0.1-15 | Detector de roles/scopes desde claims JWT | pipeline | P1 | 4.4.2 |
| V0.1-16 | Persistencia de `entity_occurrences` con `value_hash` | data | P0 | 5.3.11 |
| V0.1-17 | Normalización de valores + hashing estable | engine | P0 | 7.3 |
| V0.1-18 | Lista de valores sintéticos de baja entropía | engine | P1 | 7.10 |

### 16.3.4 Correlación básica

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V0.1-19 | Correlación Token → `EMITS`/`CONSUMES`/`AUTHORIZES` | engine | P0 | 7.4 |
| V0.1-20 | Correlación Endpoint → `RETURNS`/`ACCEPTS` de recursos | engine | P0 | 7.5 |
| V0.1-21 | `LINKS_TO` por mismo valor en distintos endpoints | engine | P1 | 7.5 |
| V0.1-22 | Confianza `EVIDENCIA`/`INFERENCIA` básica + `score` | engine | P0 | 7.6 |
| V0.1-23 | AuthFlow simple (login → token → uso) | engine | P1 | 7.8 |

### 16.3.5 Grafo y materialización

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V0.1-24 | `GraphRepository` (driver Neo4j, queries parametrizadas) | graph | P0 | 6.9 |
| V0.1-25 | Materializer batch (UNWIND, MERGE por clave natural) | graph | P0 | 4.6 |
| V0.1-26 | Nodos base: Host, Endpoint, Token, Cookie, Resource | graph | P0 | 6.3 |
| V0.1-27 | Índices y constraints del esquema v1 | graph | P0 | 6.6 |

### 16.3.6 API mínima

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V0.1-28 | `POST /api/v1/imports` (multipart) + validación | api | P0 | 9.4.2 |
| V0.1-29 | `GET /api/v1/imports/{id}` + progreso por etapa | api | P0 | 9.4.2 |
| V0.1-30 | `GET /api/v1/graph/summary` | api | P0 | 9.4.3 |
| V0.1-31 | `POST /api/v1/graph/query` con sandbox de lectura | api | P0 | 9.5.1 |
| V0.1-32 | `GET /api/v1/endpoints`, `GET /api/v1/entities`, `GET /api/v1/exchanges/{id}` | api | P1 | 9.4.4–5 |
| V0.1-33 | SSE de eventos de importación | api | P1 | 9.4.2 |
| V0.1-34 | Modelo de errores unificado (envelope) | api | P0 | 9.3 |

### 16.3.7 UI mínima

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V0.1-35 | Bootstrap frontend (React + Vite + Cytoscape) | ui | P0 | 10.7 |
| V0.1-36 | Pantalla de importación con progreso en vivo | ui | P0 | 10.2 |
| V0.1-37 | Vista Flujo de Autenticación | ui | P1 | 10.3.1 |
| V0.1-38 | Vista Recursos (básica) | ui | P1 | 10.3.2 |
| V0.1-39 | Panel de detalle de nodo + evidencia | ui | P1 | 10.5 |
| V0.1-40 | Vista Timeline (básica) | ui | P2 | 10.3.5 |
| V0.1-41 | Estilos de confianza (Evidencia/Inferencia/Hipótesis) | ui | P1 | 10.4.1 |

### 16.3.8 Orquestación del pipeline

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V0.1-42 | Colas de trabajo Redis Streams + arq | infra | P0 | 4.1 |
| V0.1-43 | Workers por etapa + `import_stages` + idempotencia | infra | P0 | 4.8 |
| V0.1-44 | Reintentos con backoff + DLQ | infra | P1 | 4.8.1 |
| V0.1-45 | Estados de import completos (`PENDING→COMPLETED`) | data | P0 | 5.3.2 |

### 16.3.9 Investigación v0.1

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V0.1-46 | Golden dataset pequeño (~5k exchanges etiquetados) | research | P0 | 7.13 |
| V0.1-47 | Script de métricas (precisión/recall de correlación) | research | P1 | 7.13 |

---

## 16.4 v1.0 — Producto MVP

### 16.4.1 Robustez y rendimiento

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V1-01 | Parsing resiliente (archivos corruptos/truncados) + fixtures | pipeline | P0 | 4.8 |
| V1-02 | Sharding de importación (chunks de 5k) | infra | P0 | 3.6 |
| V1-03 | Particionamiento de evidencia por `import_id` | data | P1 | 5.5 |
| V1-04 | Benchmark de 100k exchanges + informe SLO | infra | P1 | 3.8.1 |
| V1-05 | Cancelación y reanudación de importaciones | api | P1 | 9.4.2 |

### 16.4.2 Correlación avanzada

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V1-06 | Familias de equivalencia de labels | engine | P0 | 7.3.2 |
| V1-07 | Cadenas temporales `NEXT` + ventanas de sesión | engine | P0 | 7.8.1 |
| V1-08 | AuthFlow completo (login/refresh/logout/oauth) | engine | P0 | 7.8.2 |
| V1-09 | `REFERENCES` entre recursos (paths anidados, URLs) | engine | P1 | 7.5.1 |
| V1-10 | Refinamiento de `score` + umbral de descarte | engine | P0 | 7.6.2 |
| V1-11 | Motor de hipótesis CRUD | engine | P1 | 7.7 |
| V1-12 | Agrupación Host → Service (heurísticas) | engine | P1 | 7.9 |
| V1-13 | Reducción de falsos positivos (entropía, tipos fecha/versión) | engine | P0 | 7.10 |

### 16.4.3 Motor de reglas

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V1-14 | Parser/compilador del DSL (when/where/emit) | rules | P0 | 8.4 |
| V1-15 | Motor de ejecución (sandbox, timeout, dedupe) | rules | P0 | 8.5 |
| V1-16 | JSON Schema del DSL + validación | rules | P1 | 8.4 |
| V1-17 | Catálogo v1 completo (R-AUTH/R-TOK/R-IDOR/R-DATA/R-INFRA/R-HYP) | rules | P0 | 8.6 |
| V1-18 | `context_subgraph` en alertas | rules | P1 | 8.7.2 |
| V1-19 | Dry-run de reglas | rules | P1 | 8.4 |
| V1-20 | Priorización de alertas (`priority_score`) | rules | P1 | 8.7.3 |
| V1-21 | Evaluación FP/recall por categoría | rules | P0 | 8.9 |

### 16.4.4 API completa

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V1-22 | Endpoints de workspaces | api | P0 | 9.4.1 |
| V1-23 | Endpoints de alertas + ciclo de vida | api | P0 | 9.4.6 |
| V1-24 | Endpoints de reglas (CRUD + dry-run + schema) | api | P1 | 9.4.7 |
| V1-25 | Endpoints de vistas (auth-flow, resources, infra, permissions, timeline) | api | P0 | 9.4.8 |
| V1-26 | Endpoints de endpoints/valores y exchanges avanzados | api | P1 | 9.4.4–5 |
| V1-27 | Autenticación con API key | api | P0 | 9.6 |
| V1-28 | Paginación por cursor + filtros | api | P1 | 9.2 |
| V1-29 | Contrato OpenAPI v1 versionado + validación CI | api | P0 | 9.8 |

### 16.4.5 UI completa

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V1-30 | Vista Permisos | ui | P1 | 10.3.4 |
| V1-31 | Vista Infraestructura | ui | P1 | 10.3.3 |
| V1-32 | Panel de Alertas (triaje, notas, exportar) | ui | P0 | 10.3.6 |
| V1-33 | Query Console con autocompletado | ui | P1 | 10.3.7 |
| V1-34 | Virtualización + layouts en worker | ui | P1 | 10.9 |
| V1-35 | i18n ES/EN | ui | P2 | 10.10 |
| V1-36 | Workspace de demo (dataset sintético) | ui | P1 | 10.11 |

### 16.4.6 Operaciones y calidad

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V1-37 | Compose multi-nodo + TLS | infra | P1 | 12.1.2 |
| V1-38 | OTel + Prometheus/Grafana + alertas operativas | infra | P1 | 12.4 |
| V1-39 | Backups y runbook | infra | P1 | 12.3, 12.8 |
| V1-40 | E2E Playwright (flujos principales) | ui | P1 | 12.5 |
| V1-41 | Golden dataset ampliado (~50k) + publicación de métricas | research | P0 | 7.13 |
| V1-42 | Validación con analistas externos | research | P0 | 13.3.3 |

---

## 16.5 v2.0 — Inteligencia y Escala

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V2-01 | Adaptador HAR 1.2 | pipeline | P0 | 4.2.2 |
| V2-02 | Adaptador OpenAPI 3.x / Swagger | pipeline | P1 | 4.2.2 |
| V2-03 | Adaptador Postman Collection | pipeline | P1 | 4.2.2 |
| V2-04 | Adaptador mitmproxy | pipeline | P1 | 4.2.2 |
| V2-05 | Merge multi-fuente en un workspace | pipeline | P1 | 13.4.2 |
| V2-06 | Servicio de preguntas NL sobre el grafo (retrieval acotado) | ai | P0 | 13.4.2 |
| V2-07 | Respuestas con citas de evidencia | ai | P0 | 13.4.2 |
| V2-08 | Resúmenes automáticos por vista | ai | P1 | 13.4.2 |
| V2-09 | Hipótesis guiadas por IA | ai | P1 | 13.4.2 |
| V2-10 | Usuarios + sesiones JWT + roles | api | P0 | 9.6 |
| V2-11 | RBAC por workspace + auditoría de accesos | api | P1 | 13.4.2 |
| V2-12 | Reglas personalizadas (UI + API) | rules | P1 | 8.8 |
| V2-13 | Rulesets por perfil (PCI-DSS, OWASP Top 10) | rules | P1 | 8.8 |
| V2-14 | Algoritmos GDS (centralidad, comunidades) | graph | P1 | 6.2 |
| V2-15 | Helm charts preliminares + réplicas de lectura PG | infra | P2 | 13.4.2 |
| V2-16 | Paper + datasets públicos anonimizados | research | P1 | 13.4.2 |

---

## 16.6 v3.0 — Plataforma

| ID | Tarea | Área | Prio | Ref SAD |
|----|-------|------|------|---------|
| V3-01 | SSO/OIDC + MFA + RBAC granular | api | P0 | 13.5.2 |
| V3-02 | Alta disponibilidad (HA) completa | infra | P0 | 13.5.2 |
| V3-03 | Multi-tenant aislado (cifrado por tenant) | data | P1 | 13.5.2 |
| V3-04 | Kubernetes + autoescalado por etapa | infra | P0 | 13.5.2 |
| V3-05 | Ingesta por streaming (OpenTelemetry spans) | pipeline | P1 | 13.5.2 |
| V3-06 | Capa fría S3/Parquet para retención | data | P2 | 13.5.2 |
| V3-07 | Neo4j Enterprise / clúster con réplicas de lectura | graph | P1 | 13.5.2 |
| V3-08 | Marketplace de reglas de la comunidad | rules | P1 | 13.5.2 |
| V3-09 | Webhooks a SIEM/ticketing | api | P1 | 13.5.2 |
| V3-10 | Plugins (Burp, ZAP, Postman, VS Code) | ecosystem | P2 | 13.5.2 |
| V3-11 | SDK Python/Go sobre la API | api | P1 | 13.5.2 |
| V3-12 | Adaptador PCAP/PCAPng | pipeline | P1 | 13.5.2 |
| V3-13 | Adaptador OpenTelemetry (trazas → flujos) | pipeline | P1 | 13.5.2 |
| V3-14 | Exportación de informes (PDF) | ui | P2 | 13.5.2 |
| V3-15 | Modelo de negocio open-core | product | P1 | 13.5.2 |

---

## 16.7 Orden de implementación recomendado (sprint 0–2)

Para arrancar el proyecto en las primeras 2–3 semanas:

1. **Sprint 0** — Bootstrap (B-01→B-09) + modelo canónico (V0.1-01) + migraciones base.
2. **Sprint 1** — Importación y parseo (V0.1-02→V0.1-05), persistencia de evidencia, API de importación (V0.1-28/29).
3. **Sprint 2** — Normalización (V0.1-07→09), extracción básica (V0.1-12→14), correlación token/endpoint (V0.1-19/20), primer subgrafo en Neo4j.

El objetivo de estos sprints es lograr el **primer grafo navegable** de un dataset sintético (criterio de salida de v0.1).

## 16.8 Métricas de progreso del backlog

| Métrica | Definición | Objetivo por versión |
|---------|------------|----------------------|
| Cobertura de backlog | % de tareas `Hecho` por versión | 100% al salir de cada versión |
| Cobertura de código | líneas testeadas / total | ≥ 85% en v1.0 |
| SLO de importación | tiempo de 100k exchanges | < 10 min en v1.0 |
| Precisión de correlación | golden dataset | > 90% en v1.0 |
| FP de reglas | alertas falsas / total | < 20% en v1.0 |
