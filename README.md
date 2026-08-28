<div align="center">

# API Knowledge Graph

**Intelligent API security analysis** that turns captured HTTP traffic into a navigable **knowledge graph** — the "BloodHound" for modern APIs.

</div>

---

## Overview

An API audit can generate tens of thousands of requests. Conventional tooling renders this traffic as a flat, linear sequence, forcing the analyst to mentally reconstruct how components interact.

This project stores **knowledge, not requests**: every request becomes evidence, relationships between entities are inferred, and a navigable model of the application is assembled — covering authentication flows, business resources, infrastructure, permissions, and full timelines.

See the complete vision in [`IDEA.md`](./IDEA.md).

## Documentation

The **Software Architecture Specification (SAD)** lives in [`docs/sad/`](./docs/sad/README.md). Its 16 chapters (~50–60 pages) define the system end to end:

| Chapter | Topic |
|---------|-------|
| `01` | Introduction, problem statement, goals, and success criteria |
| `02` | Architectural principles and ADRs |
| `03` | High-level architecture (C4) and technology stack |
| `04` | Processing pipeline (7 stages) |
| `05` | Relational data model (evidence, PostgreSQL) |
| `06` | Knowledge graph schema (Neo4j) |
| `07` | Correlation engine and trust model |
| `08` | Rule system (DSL and catalogue) |
| `09` | Internal REST API |
| `10` | System views and frontend |
| `11` | Security and privacy |
| `12` | Deployment and operations |
| `13` | **Roadmap v0.1 → v3.0** |
| `14` | Risks and mitigations |
| `15` | Glossary and appendices |

Ready to start coding? See [`docs/sad/16-backlog-de-implementacion.md`](./docs/sad/16-backlog-de-implementacion.md).

## Technology Stack

| Layer | Choice |
|-------|--------|
| **Backend** | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy/Alembic |
| **Graph** | Neo4j 5 (Cypher) |
| **Evidence store** | PostgreSQL 15 (JSONB) |
| **Queues** | Redis Streams (arq) |
| **Frontend** | React 18 + TypeScript + Cytoscape.js |
| **Ops** | Docker Compose, OpenTelemetry/Prometheus/Grafana |

## Roadmap

| Version | Focus |
|---------|-------|
| **v0.1** | Prototype: import Burp Logger → basic navigable graph |
| **v1.0** | MVP: robust correlation, rule engine, stable API |
| **v2.0** | AI on the graph, new sources (HAR/OpenAPI/mitmproxy), multi-user |
| **v3.0** | Enterprise platform: HA, rule ecosystem, integrations |

## Status

Project currently in **implementation (v0.1)**. The ETL pipeline (import Burp → normalize → correlate → materialize into Neo4j → persist in PostgreSQL), the REST API, and a basic UI are functional.

## Getting Started

Requirements: `uv`, `docker` and `docker compose`.

```bash
make setup     # starts PostgreSQL + Neo4j + Redis and creates the schema (DB + graph)
make dev       # setup + runs the API at http://localhost:8000
```

Alternatively, step by step:

```bash
make up            # containers
make schema        # Alembic migrations + Neo4j schema
make api           # uvicorn with reload
```

### Endpoints

- `http://localhost:8000/docs` — Swagger UI
- `http://localhost:8000/ui/` — Web graph UI
- `POST /api/v1/imports` — upload a Burp export and trigger the pipeline

### Quality

```bash
make test       # unit tests (no infra)
make test-int   # integration tests (requires infra)
make lint       # ruff + mypy
make smoke      # foundational check (PostgreSQL + Neo4j + schemas)
```

Sample data is available at `dev/samples/burp_sample.json`.

## Make Targets

| Command | Description |
|---------|-------------|
| `make setup` | Infra + DB schema + Neo4j schema + migrations |
| `make dev` | Everything + API on `:8000` |
| `make api` | Server only |
| `make test` / `test-int` / `test-all` | Tests |
| `make lint` / `format` | Code quality |
| `make down` / `clean` | Stop infra / clean up |