# 12. Despliegue y Operaciones

> **Capítulo 12 de 15** — Topologías de despliegue, operaciones, observabilidad, CI/CD y estrategia de escalado del sistema.

---

## 12.1 Modelo de despliegue

### 12.1.1 Topologías soportadas

| Topología | Uso | A partir de |
|-----------|-----|-------------|
| **A — Local (dev)** | Desarrollo, pruebas | v0.1 |
| **B — Docker Compose (single-node)** | Instalación estándar del auditor | v0.1 |
| **C — Docker Compose (multi-nodo)** | Equipos pequeños | v1.0 |
| **D — Kubernetes** | Enterprise, alta disponibilidad | v3.0 |

### 12.1.2 Topología B — Docker Compose (referencia v1.0)

```yaml
services:
  api:            {image: akg/api,      ports: ["8080:8080"]}
  worker-parse:   {image: akg/worker,   command: ["parse"]}
  worker-normalize:{image: akg/worker,  command: ["normalize"]}
  worker-extract: {image: akg/worker,  command: ["extract"]}
  worker-correlate:{image: akg/worker,  command: ["correlate"]}
  worker-materialize:{image: akg/worker,command: ["materialize"]}
  worker-rules:   {image: akg/worker,  command: ["rules"]}
  importer:       {image: akg/importer}
  ui:             {image: akg/ui,       ports: ["3000:80"]}
  postgres:       {image: postgres:15}
  neo4j:          {image: neo4j:5,      volumes: ["neo4j-data"]}
  redis:          {image: redis:7}
  otel-collector: {image: otel/opentelemetry-collector, profiles: ["telemetry"]}
```

Persistencia en volúmenes nombrados: `pg-data`, `neo4j-data`, `redis-data`.

### 12.1.3 Consideraciones de red

- API y UI expuestos; internos (postgres, neo4j, redis) en red privada de Compose.
- Neo4j accesible desde API/workers únicamente (no expuesto al host por defecto).
- Bind de la API a `0.0.0.0` solo en topologías B+ con auth (capítulo 11).

## 12.2 Arranque y migraciones

| Paso | Herramienta | Detalle |
|------|-------------|---------|
| Esquema relacional | Alembic | `alembic upgrade head` en el contenedor `api` (init container) |
| Esquema de grafo | Scripts Cypher idempotentes | `schemas/neo4j/v1.cypher` en `worker-materialize` |
| Catálogo de reglas | Seed de datos | Cargado por `worker-rules` si `rules` vacía |
| Índices Redis | `redis-cli` | Configuración de streams y grupos |

## 12.3 Operaciones del pipeline

### 12.3.1 Estado de importaciones

Los workers actualizan `import_stages` y `imports.status`. Operaciones de la API:

- Reanudar (`POST /imports/{id}/resume`).
- Cancelar (`POST /imports/{id}/cancel` en v1.0).
- Re-correlacionar (`POST /imports/{id}/reprocess` tras actualizar el motor).

### 12.3.2 Backups

| Dato | Frecuencia sugerida | Mecanismo |
|------|---------------------|-----------|
| PostgreSQL | Diario | `pg_dump` / `pgBackRest` |
| Neo4j | Diario | `neo4j-admin dump` (offline) |
| Configuración | Por cambio | Git (repo de config) |

Recuperación: restore + regeneración del grafo (re-materializar desde evidencia) si fuera necesario.

## 12.4 Observabilidad

### 12.4.1 Métricas (Prometheus)

| Métrica | Tipo | Etiquetas |
|---------|------|-----------|
| `akg_import_total` | counter | source_format |
| `akg_import_duration_seconds` | histogram | stage |
| `akg_import_status` | gauge | status |
| `akg_exchanges_processed` | counter | import_id, stage |
| `akg_nodes_created_total` / `akg_edges_created_total` | counter | — |
| `akg_alerts_created_total` | counter | severity, category |
| `akg_graph_query_duration_seconds` | histogram | endpoint |
| `akg_queue_depth` | gauge | stream |

### 12.4.2 Trazas (OpenTelemetry)

- Span por etapa y por shard: `stage`, `import_id`, `shard`, `processed`.
- `otel-collector` recibe OTLP y exporta a Jaeger/Tempo.
- Perfil "sin telemetría" para entornos sin backend de trazas.

### 12.4.3 Logs

- Estructurados (JSON), con `request_id`, `import_id`, `stage`.
- Niveles: `dev` (debug) / `prod` (info+).
- Retención 30 días; sin datos sensibles (capítulo 11.7.4).

### 12.4.4 Alertas operativas (SLOs)

| Alerta | Condición |
|--------|-----------|
| Import demasiado lento | `akg_import_duration` p99 > 15 min (100k) |
| Etapa fallando | ratio de fallos de etapa > 1% en 10 min |
| Cola acumulada | profundidad de stream > 10k durante 5 min |
| Neo4j degradado | latencia de query p99 > 5 s |

## 12.5 CI/CD

### 12.5.1 Pipeline de CI (GitHub Actions)

| Job | Herramientas | Gate |
|-----|--------------|------|
| Lint + tipos | ruff, mypy | fallos bloquean |
| Tests unitarios | pytest | cobertura ≥ 85% |
| Tests de integración | pytest + Compose (postgres, neo4j, redis) | dataset sintético |
| Validación de reglas | dry-run sobre golden dataset | F1 por regla ≥ umbral |
| Validación OpenAPI | redocly/cli | schema válido |
| E2E frontend | Playwright | flujos principales |
| Build de imágenes | Docker Buildx | multi-arch (amd64/arm64) |

### 12.5.2 Publicación de versiones

- Versionado semántico del producto (`0.1.0`, `1.0.0`, ...).
- Etiquetas `vX.Y.Z` + changelog.
- Imágenes publicadas en GHCR con tags `X.Y.Z` y `latest`.

### 12.5.3 CD

- v0.1–v1.0: liberación manual de releases.
- v3.0: helm charts + flujo de canary en clúster.

## 12.6 Escalado

### 12.6.1 Estrategia por componente

| Componente | Estrategia |
|------------|-----------|
| Workers | Horizontal: N réplicas por etapa; sharding por `import_id`/chunk |
| Redis | Vertical inicial; Cluster Redis en v3+ |
| PostgreSQL | Replicación de lectura para consultas; particionamiento por import |
| Neo4j | Comunitario single; Enterprise/HA en v3+ con lectura de réplicas |
| API | Stateless → horizontal detrás de load balancer |

### 12.6.2 Dimensionamiento (guía)

| Dataset | API | Workers | PG | Neo4j | Redis |
|---------|-----|---------|----|-------|-------|
| 10k exchanges | 1×1 vCPU | 2 | 2 GB | 2 GB | 512 MB |
| 100k exchanges | 1×2 vCPU | 4 | 8 GB | 4 GB | 1 GB |
| 1M exchanges | 2×4 vCPU | 12 | 32 GB | 16 GB | 4 GB |

## 12.7 Entornos

| Entorno | Uso | Configuración clave |
|---------|-----|---------------------|
| `dev` | Desarrollo | SQLite opcional en PG en memoria, sin telemetría, seed |
| `test` | CI | Contenedores efímeros, dataset sintético |
| `staging` | QA | Compose completo, telemetría activa |
| `prod` | Producción | TLS, backups, auth, telemetría, retención |

## 12.8 Runbook (operaciones comunes)

| Operación | Pasos |
|-----------|-------|
| Reanudar import fallida | `POST /api/v1/imports/{id}/resume`; verificar `stage_error` |
| Actualizar motor de correlación | Rebuild worker + `POST /imports/{id}/reprocess` |
| Restaurar backup | Restore PG → restore Neo4j → `resume` si quedó a medias |
| Ampliar capacidad | Añadir réplicas de workers; Redis/PG/Neo4j según dimensionado |
| Rotar API key | Regenerar en workspace; revocar antigua en 24 h |
| Modo offline/air-gapped | Despliegue local sin telemetría ni registro externo |

## 12.9 Checklist de despliegue (v1.0)

- [ ] `docker compose up -d` levanta los 9 contenedores.
- [ ] `GET /api/v1/health` devuelve `ok` con estado de PG/Neo4j/Redis.
- [ ] Migraciones aplicadas (Alembic + Cypher idempotente).
- [ ] Catálogo de reglas cargado (`GET /api/v1/rules` no vacío).
- [ ] Import de prueba con dataset sintético completa las 7 etapas.
- [ ] TLS activo en la UI/API si no es localhost.
- [ ] Backups programados y verificados.
- [ ] Alertas operativas configuradas en Prometheus.
