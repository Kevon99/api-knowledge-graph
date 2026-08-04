# API Knowledge Graph — Entrypoint único
#
# Uso rápido:
#   make setup      -> levanta infra + esquema BD + Neo4j + migraciones
#   make dev        -> levanta todo y arranca la API en http://localhost:8000
#   make api        -> solo arranca el servidor
#   make test       -> tests unitarios (sin infra)
#   make test-int   -> tests de integración (requiere infra arriba)
#   make down       -> detiene los contenedores
#   make clean      -> detiene infra y borra artefactos

SHELL := /bin/bash
COMPOSE := docker compose -f deploy/compose/docker-compose.yml
RU := PYTHONPATH=. uv run

.DEFAULT_GOAL := help

.PHONY: help setup infra up neo4j-schema migrate schema api dev test test-all \
        test-int lint format smoke down clean

help:  ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

## ── Setup completo ───────────────────────────────────────────────────────────

setup: infra schema migrate  ## Infra + esquema BD + Neo4j + migraciones
	@echo "--> Dependencias listas"

infra:  ## Levanta PostgreSQL, Neo4j y Redis (idempotente)
	$(COMPOSE) up -d
	@echo "Esperando a que los contenedores esten healthy..."
	@for c in akg-postgres akg-neo4j akg-redis; do \
	  until [ "$$(docker inspect -f '{{.State.Health.Status}}' $$c 2>/dev/null)" = "healthy" ]; do \
	    sleep 2; \
	  done; \
	  echo "  $$c healthy"; \
	done
	@$(COMPOSE) ps

up: infra  ## Alias de `make infra`

## ── Esquemas ─────────────────────────────────────────────────────────────────

neo4j-schema:  ## Aplica constraints e indices del grafo en Neo4j
	@echo "Aplicando esquema Neo4j (idempotente)..."
	$(COMPOSE) exec -T neo4j cypher-shell -u neo4j -p neo4j_dev_password < schemas/neo4j/v1.cypher

migrate:  ## Aplica migraciones de base de datos (Alembic)
	$(RU) alembic upgrade head

schema: neo4j-schema migrate  ## Aplica esquema Neo4j + migraciones Postgres

## ── App ──────────────────────────────────────────────────────────────────────

api:  ## Arranca la API (uvicorn, reload)
	$(RU) uvicorn app:app --host 0.0.0.0 --port 8000 --reload

dev:  ## Setup + API (todo en un solo paso)
	make infra
	make schema
	make api

## ── Calidad ──────────────────────────────────────────────────────────────────

test:  ## Tests unitarios (sin infraestructura)
	$(RU) pytest tests/ -q -m "not integration"

test-int:  ## Tests de integración (requiere infra)
	$(RU) pytest tests/ -q -m "integration"

test-all: test test-int  ## Todos los tests (unitarios + integración)

lint:  ## ruff check + mypy
	$(RU) ruff check akg engine pipeline tests app.py
	$(RU) mypy --ignore-missing-imports akg engine pipeline tests app.py

format:  ## Formatea el codigo con ruff
	$(RU) ruff format akg engine pipeline tests app.py

## ── Scripts dev ──────────────────────────────────────────────────────────────

smoke:  ## Chequeo fundacional (PostgreSQL+Neo4j+Schemas)
	$(RU) python dev/smoke.py

## ── Limpieza ─────────────────────────────────────────────────────────────────

down:  ## Detiene los contenedores
	$(COMPOSE) down

clean:  ## Detiene contenedores y borra artefactos
	$(COMPOSE) down
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +