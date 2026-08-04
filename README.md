# API Knowledge Graph

Plataforma inteligente para el análisis de seguridad de APIs que transforma tráfico HTTP capturado en un **grafo de conocimiento** navegable — el "BloodHound" de las APIs modernas.

## Idea

Una auditoría de API puede generar decenas de miles de peticiones. Las herramientas actuales muestran ese tráfico como una secuencia lineal, obligando al analista a reconstruir mentalmente cómo interactúan los componentes.

Este proyecto almacena **conocimiento, no peticiones**: convierte cada request en evidencia, genera relaciones entre entidades, y construye un modelo navegable de la aplicación (flujos de autenticación, recursos de negocio, infraestructura, permisos y timeline).

Ver la visión completa en [`IDEA.md`](./IDEA.md).

## Documentación

La **Especificación de Arquitectura de Software (SAD)** está en [`docs/sad/`](./docs/sad/README.md). 16 capítulos (~50–60 páginas) que definen:

| Capítulo | Tema |
|----------|------|
| `01` | Introducción, problema, objetivos y criterios de éxito |
| `02` | Principios arquitectónicos y ADRs |
| `03` | Arquitectura general (C4) y stack tecnológico |
| `04` | Pipeline de procesamiento (7 etapas) |
| `05` | Modelo de datos relacional (evidencia, PostgreSQL) |
| `06` | Esquema del grafo de conocimiento (Neo4j) |
| `07` | Motor de correlación y modelo de confianza |
| `08` | Sistema de reglas (DSL y catálogo) |
| `09` | API REST interna |
| `10` | Vistas del sistema y frontend |
| `11` | Seguridad y privacidad |
| `12` | Despliegue y operaciones |
| `13` | **Hoja de ruta v0.1 → v3.0** |
| `14` | Riesgos y mitigaciones |
| `15` | Glosario y apéndices |

Para empezar a programar: [`docs/sad/16-backlog-de-implementacion.md`](./docs/sad/16-backlog-de-implementacion.md).

## Stack propuesto

- **Backend**: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy/Alembic
- **Grafo**: Neo4j 5 (Cypher)
- **Evidencia**: PostgreSQL 15 (JSONB)
- **Colas**: Redis Streams (arq)
- **Frontend**: React 18 + TypeScript + Cytoscape.js
- **Ops**: Docker Compose, OpenTelemetry/Prometheus/Grafana

## Hoja de ruta resumida

| Versión | Enfoque |
|---------|---------|
| **v0.1** | Prototipo: importar Burp Logger → grafo navegable básico |
| **v1.0** | Producto MVP: correlación robusta, motor de reglas, API estable |
| **v2.0** | IA sobre el grafo, nuevas fuentes (HAR/OpenAPI/mitmproxy), multiusuario |
| **v3.0** | Plataforma enterprise: HA, ecosistema de reglas, integraciones |

## Estado

Proyecto en fase de **implementación (v0.1)**. El pipeline ETL (importar Burp → normalizar → correlacionar → materializar en Neo4j → persistir en PostgreSQL), la API REST y una UI básica están funcionando.

## Cómo ejecutar

Requisitos: `uv`, `docker` + `docker compose`.

```bash
make setup     # levanta PostgreSQL+Neo4j+Redis y crea el esquema (BD + grafo)
make dev       # setup + arranca la API en http://localhost:8000
```

Alternativamente, paso a paso:

```bash
make up            # contenedores
make schema        # migraciones Alembic + esquema Neo4j
make api           # uvicorn con reload
```

Endpoints:
- `http://localhost:8000/docs` — Swagger
- `http://localhost:8000/ui/` — UI web del grafo
- `POST /api/v1/imports` — subir un export de Burp y disparar el pipeline

Calidad:

```bash
make test       # tests unitarios (sin infra)
make test-int   # tests de integración (con infra arriba)
make lint       # ruff + mypy
make smoke      # chequeo fundacional (PostgreSQL + Neo4j + schemas)
```

Datos de muestra en `dev/samples/burp_sample.json`.

| Comando | Descripción |
|---------|-------------|
| `make setup` | Infra + esquema BD + Neo4j + migraciones |
| `make dev` | Todo + API en `:8000` |
| `make api` | Solo servidor |
| `make test` / `test-int` / `test-all` | Tests |
| `make lint` / `format` | Calidad |
| `make down` / `clean` | Parar infra / limpiar |
