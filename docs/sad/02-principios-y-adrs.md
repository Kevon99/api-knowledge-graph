# 2. Principios Arquitectónicos y Decisiones de Arquitectura (ADRs)

> **Capítulo 2 de 15** — Principios que guían todas las decisiones técnicas del proyecto y el registro formal de decisiones de arquitectura (Architecture Decision Records).

---

## 2.1 Introducción

Este capítulo define los principios arquitectónicos del proyecto y documenta formalmente las decisiones de arquitectura (ADRs). Cada ADR sigue el formato clásico: **Contexto → Decisión → Consecuencias → Alternativas consideradas**.

Los ADRs son vinculantes para la implementación. Cualquier cambio en ellos debe generar un nuevo ADR que lo reemplace (ADR-000 se reserva como índice).

## 2.2 Principios arquitectónicos

Los siguientes principios son la brújula de todas las decisiones de diseño:

| Código | Principio | Descripción |
|--------|-----------|-------------|
| PR-01 | **Conocimiento sobre tráfico** | El sistema almacena y razona sobre conocimiento estructurado; el tráfico crudo es evidencia transitoria |
| PR-02 | **API-first** | Toda funcionalidad debe ser invocable vía la API interna; la UI es un consumidor más |
| PR-03 | **Desacople del origen** | El núcleo ignora el formato de entrada; los adaptadores de importación son pluggable |
| PR-04 | **Evidencia, no especulación** | Toda relación tiene nivel de confianza explícito; nunca se presenta una inferencia como hecho |
| PR-05 | **Idempotencia** | Reimportar el mismo dataset produce el mismo resultado (upsert, sin duplicados) |
| PR-06 | **Reproductibilidad** | Cada importación registra versión del pipeline y config; el análisis es reproducible |
| PR-07 | **Escalabilidad horizontal** | El pipeline debe poder escalar con workers sin re-diseñar el modelo |
| PR-08 | **Privacidad por diseño** | Datos sensibles redactables, retención configurable, funcionamiento local |
| PR-09 | **Reglas extensibles** | El catálogo de reglas es datos, no código; el núcleo es genérico |
| PR-10 | **Sistemas comprobables** | Núcleo sin dependencias de UI; pruebas unitarias y de integración obligatorias |
| PR-11 | **Versionado del esquema** | El esquema del grafo y de la BD evolucionan con migraciones versionadas |
| PR-12 | **Fail-closed en análisis** | Si un parser falla en una porción de datos, se aísla y se registra; el resto continúa |

## 2.3 Índice de ADRs

| ADR | Título | Estado |
|-----|--------|--------|
| ADR-001 | Almacenamiento del grafo: Neo4j | Aceptado |
| ADR-002 | Almacenamiento de evidencia: PostgreSQL | Aceptado |
| ADR-003 | Estilo de aplicación: monorepo modular | Aceptado |
| ADR-004 | Pipeline dirigido por eventos (mensajería) | Aceptado |
| ADR-005 | Lenguaje del núcleo: Python 3.11+ (FastAPI) | Aceptado |
| ADR-006 | Modelo de confianza de tres niveles | Aceptado |
| ADR-007 | Normalización de rutas con segmentos dinámicos | Aceptado |
| ADR-008 | Almacenamiento de cuerpos JSON con JSONB + paths canónicos | Aceptado |
| ADR-009 | Reglas declarativas con DSL interno | Aceptado |
| ADR-010 | Contenerización como estándar de despliegue | Aceptado |
| ADR-011 | Trazas y correlación interna con OpenTelemetry | Aceptado |
| ADR-012 | API versionada por URL con contratos OpenAPI | Aceptado |

---

## 2.4 ADR-001 — Almacenamiento del grafo: Neo4j

### Contexto

El núcleo del producto es un grafo de conocimiento: nodos (entidades) y relaciones (correlaciones) con propiedades y niveles de confianza. Se necesitan consultas de recorrido de grafos (caminos login→pago), algoritmos de análisis (centralidad, comunidades) y búsqueda por propiedades.

### Decisión

Usar **Neo4j Community Edition** como base de datos de grafos. El esquema se define en `06-esquema-del-grafo.md`. Se usarán:

- **Cypher** como lenguaje de consulta.
- **APOC** para utilidades y transformaciones.
- **Graph Data Science (GDS)** para algoritmos de grafo en versiones posteriores (v2+).

### Consecuencias

- Positivas: recorridos de grafo expresivos, índice de labels/propiedades, ecosistema maduro, APOC/GDS, integración con Python (`neo4j` driver).
- Negativas: licenciamiento Community (limitaciones de HA/backups online para clusters), coste de memoria para grafos grandes; necesidad de sincronizar metadata entre PostgreSQL y Neo4j.

### Alternativas consideradas

- **ArangoDB**: multi-modelo interesante, pero menor ecosistema de análisis de grafos.
- **Memgraph**: prometedor en rendimiento, menor madurez de ecosistema y menor soporte de drivers en el stack elegido.
- **GraphQL + BBDD documental**: no soporta recorridos eficientes a profundidad.
- **In-memory (networkx)**: no escala a 100k+ nodos de forma persistente.

---

## 2.5 ADR-002 — Almacenamiento de evidencia: PostgreSQL

### Contexto

El sistema recibe tráfico HTTP crudo que debe persistirse como **evidencia** para reconstrucción y auditoría, pero con un modelo relacional estructurado (requests, responses, headers, cookies, params, bodies, archivos). También se necesitan metadatos de importación, sesiones de auditoría y configuración.

### Decisión

Usar **PostgreSQL 15+** como base relacional. Uso intensivo de:

- **JSONB** para cabeceras, cuerpos y estructuras semi-estructuradas.
- Índices GIN para consultas sobre JSONB.
- `tsvector` para búsqueda de texto sobre rutas y valores.
- Particionamiento por `import_id` para datasets grandes.

### Consecuencias

- Positivas: integridad transaccional, JSONB maduro, herramientas de backup, madurez operativa.
- Negativas: dos motores de datos (PG + Neo4j) requieren sincronización; la doble escritura incrementa la complejidad de la capa de persistencia.

### Alternativas consideradas

- SQLite: insuficiente para datasets grandes y conc<->necurrencia.
- Elasticsearch: buen para búsqueda, malo como fuente de verdad transaccional.
- S3 + Parquet: viable para v3+ como capa fría, no como fuente primaria en v1.

---

## 2.6 ADR-003 — Estilo de aplicación: monorepo modular

### Contexto

El proyecto tiene varios módulos: importadores, normalización, extracción, correlación, reglas, API, UI. La pregunta es si construir un monolito, microservicios o un término medio.

### Decisión

**Monorepo modular con módulos con límites estrictos** (bounded contexts) en fase v0.1–v1.0. Cada módulo es un paquete independiente con su propia interfaz, tests y contratos. La comunicación entre módulos en proceso es por **colas internas in-process** o mediante la **mensajería** del ADR-004 según el acoplamiento.

La evolución a microservicios queda abierta si el rendimiento o la organización del equipo lo requieren (v3+).

### Consecuencias

- Positivas: simplicidad de despliegue inicial, desarrollo rápido, tests integrales, refactorización segura por límites.
- Negativas: requiere disciplina para no romper los límites; el escalado horizontal del pipeline depende de que el procesamiento sea por lotes desacoplados (ver ADR-004).

---

## 2.7 ADR-004 — Pipeline dirigido por eventos (mensajería)

### Contexto

La importación de un dataset grande dispara varias etapas asíncronas (parseo → normalización → extracción → correlación → materialización). Estas etapas tienen latencias distintas y deben poder escalar independientemente.

### Decisión

Usar **mensajería asíncrona** para el pipeline:

- **Redis Streams** como bus principal (bajo overhead, ideal para colas de trabajo con ack) en v0.1–v1.0.
- Reserva de **RabbitMQ/Kafka** si se requiere entrega at-least-once garantizada y múltiples consumidores a gran escala (v3+).

Los trabajos se procesan con un modelo de worker: **un worker por etapa**, consumidores idempotentes, soporte de reintentos con backoff.

### Consecuencias

- Positivas: desacoplamiento entre etapas, escalado horizontal por etapa, resiliencia ante fallos puntuales.
- Negativas: complejidad operativa de la mensajería, necesidad de idempotencia en todos los workers, mayor latencia mínima por etapa.

---

## 2.8 ADR-005 — Lenguaje del núcleo: Python 3.11+ (FastAPI)

### Contexto

Se necesita un lenguaje con: ecosistema rico de parsing/HTTP/JSON, productividad alta para prototipar, drivers maduros de Neo4j/PostgreSQL, y soporte de computación concurrente.

### Decisión

**Python 3.11+** con:

- **FastAPI** para la API interna (tipado, OpenAPI automático, alto rendimiento).
- **Pydantic v2** para modelos de dominio y validación.
- **TaskIQ/Celery** o **arq** para workers asíncronos.
- **pytest** como framework de pruebas.
- **ruff + mypy** para calidad estática.

### Consecuencias

- Positivas: velocidad de desarrollo, ecosistema, tipado fuerte, generación automática de OpenAPI (alineado con PR-02/ADR-012).
- Negativas: rendimiento inferior a lenguajes compilados; mitigado delegando operaciones costosas a Neo4j (Cypher) y a librerías nativas (orjson, rapidjson, uvloop).

### Alternativas consideradas

- Go: excelente rendimiento, pero menor velocidad de prototipado para el análisis de datos; el equipo puede evaluar para componentes críticos en v3+.
- TypeScript/Node: buen rendimiento y tipado, ecosistema menor para análisis de grafos.

---

## 2.9 ADR-006 — Modelo de confianza de tres niveles

### Contexto

La herramienta distingue hechos observados de relaciones inferidas. Se necesita un modelo formal de confianza aplicable a nodos y relaciones del grafo.

### Decisión

Cada nodo y relación del grafo lleva el atributo `confidence ∈ {EVIDENCIA, INFERENCIA, HIPOTESIS}`.

- **EVIDENCIA**: relación observada directamente en el tráfico (p. ej., un JWT aparece en la cabecera `Authorization` de una petición).
- **INFERENCIA**: relación obtenida por correlación estadística o estructural con alta confianza (p. ej., mismo `customerId` en múltiples operaciones ⇒ mismo recurso de negocio).
- **HIPOTESIS**: conclusión razonable pero no confirmada (p. ej., dado `GET /users/{id}` y `POST /users`, se hipotetiza la existencia de `PUT /users/{id}`).

Además, cada relación puede llevar `score ∈ [0,1]` (grado de fuerza) y `evidence_ids[]` (referencias a la evidencia que la sustenta).

### Consecuencias

- Positivas: transparencia, auditabilidad, permite filtrar por nivel de confianza en la UI, base para el motor de reglas.
- Negativas: más datos por relación; requiere disciplina al construir el motor de correlación para no contaminar la capa de evidencia.

---

## 2.10 ADR-007 — Normalización de rutas con segmentos dinámicos

### Contexto

Las rutas contienen IDs y parámetros dinámicos. Se necesita convertir peticiones individuales en plantillas de recursos (`/users/15` y `/users/84` → `/users/{id}`) sin perder información del valor concreto.

### Decisión

Implementar un **normalizador de rutas por niveles**:

1. **Segmentación** por `/`.
2. **Clasificación de segmento**: fijo, numérico, UUID, hash (hex/base64), mixto.
3. **Templating por frecuencia**: los segmentos con cardinalidad alta y sin repetición constante se convierten en `{param:N}` con nombre derivado del contexto semántico si es posible (`id`, `uuid`, `hash`).
4. **Soporte de tokens semánticos**: detectar nombres de parámetro que viajan en la ruta (p. ej., `/users/{userId}/orders/{orderId}`) reutilizando el nombre de segmentos adyacentes cuando hay convenciones.

El valor concreto se almacena como `path_param_value` en la petición, manteniendo trazabilidad.

### Consecuencias

- Positivas: identifica recursos en lugar de peticiones individuales (objetivo clave), permite el análisis de "¿cuántos endpoints hay?" y "¿cuántos valores de recurso distintos?".
- Negativas: riesgo de sobre-normalización (segmentos que son en realidad valores finitos). Mitigado con el umbral de cardinalidad y configuración por importación.

---

## 2.11 ADR-008 — Almacenamiento de cuerpos JSON con JSONB y paths canónicos

### Contexto

Los cuerpos de las peticiones/respuestas contienen los objetos de negocio que alimentan la correlación (IDs, tokens, referencias). Se necesita extraer, indexar y correlacionar sobre esos contenidos de forma eficiente.

### Decisión

- Persistir cuerpos como **JSONB** (PostgreSQL) manteniendo fidelidad.
- En la fase de extracción, generar **paths canónicos** para cada hoja de valor (p. ej., `$.data.customer.id`), que se indexan en una tabla `entity_occurrences` junto con el valor y su tipo.
- Los **valores sensibles** (tokens, secretos) se redactan según política (capítulo 11) pero su **huella (hash)** se mantiene para correlación.

### Consecuencias

- Positivas: correlación por valor+path sin re-escanear cuerpos completos; trazabilidad directa a la evidencia.
- Negativas: la extracción de paths canónicos debe mantenerse sincronizada con cambios en el formato de los cuerpos; coste de almacenamiento adicional.

---

## 2.12 ADR-009 — Reglas declarativas con DSL interno

### Contexto

El motor de reglas debe ser extensible sin recompilar el núcleo. Las reglas necesitan describir patrones sobre el grafo y producir alertas contextuales.

### Decisión

Definir un **DSL declarativo** de reglas (YAML/JSON) con bloques: `when` (patrón de grafo en un sub-lenguaje tipo Cypher restringido), `where` (filtros), `severity`, `mitigation` y `references`. El motor ejecuta las reglas traduciendo el `when` a consultas parametrizadas sobre Neo4j.

Ver especificación completa en `08-motor-de-reglas.md`.

### Consecuencias

- Positivas: reglas versionadas y revisables, usuario experto puede añadir reglas, validación estática del DSL, alineado con PR-09.
- Negativas: el sub-lenguaje de patrones requiere diseño cuidadoso para cubrir casos sin ser un segundo Cypher completo.

---

## 2.13 ADR-010 — Contenerización como estándar de despliegue

### Contexto

El producto debe ser portable (instalación local del auditor, despliegue on-prem/cloud) y reproducible.

### Decisión

Distribución basada en **Docker**: imágenes por componente (api, workers, importer, ui, grafos de infra). `docker-compose` como forma de despliegue estándar para v1; Helm charts para Kubernetes en v3+. Cada imagen es reproducible (multi-stage build, pin de versiones).

### Consecuencias

- Positivas: portabilidad, entornos consistentes, onboarding rápido.
- Negativas: overhead operativo de orquestación; requiere estrategia de volúmenes para persistencia.

---

## 2.14 ADR-011 — Trazas y correlación interna con OpenTelemetry

### Contexto

El pipeline tiene múltiples etapas distribuidas. Se necesita observabilidad end-to-end (¿dónde se gasta el tiempo? ¿qué etapa falla?).

### Decisión

Integrar **OpenTelemetry** para trazas distribuidas y métricas del pipeline (tiempos por etapa, tasa de fallos, volumen de nodos/relaciones generadas). Exponer métricas en formato Prometheus y trazas a un backend compatible (Jaeger/OTLP).

### Consecuencias

- Positivas: diagnóstico eficiente, alineado con PR-05/PR-06 (reproducibilidad), base para SLOs.
- Negativas: dependencia de un backend de trazas para entornos de desarrollo; se provee un perfil "sin OTel" para modo local.

---

## 2.15 ADR-012 — API versionada por URL con contratos OpenAPI

### Contexto

La API interna debe evolucionar sin romper consumidores (UI, CLI, scripts de auditor).

### Decisión

- Versionado por **prefijo de URL** (`/api/v1/...`).
- Contratos **OpenAPI 3.x** generados automáticamente desde FastAPI y versionados en el repo (`api/contracts/`).
- Compatibilidad: dentro de la misma versión mayor, solo cambios aditivos.

### Consecuencias

- Positivas: estabilidad contractual, generación de clientes, documentación viva.
- Negativas: sobrecoste de mantenimiento del contrato.

---

## 2.16 Resumen y trazabilidad

| ADR | Principios que satisface | Capítulos relacionados |
|-----|--------------------------|------------------------|
| ADR-001 | PR-04, PR-10 | 6, 7 |
| ADR-002 | PR-04, PR-05 | 5 |
| ADR-003 | PR-10, PR-11 | 3, 4 |
| ADR-004 | PR-07, PR-05 | 4, 12 |
| ADR-005 | PR-02, PR-10 | 3, 9 |
| ADR-006 | PR-04 | 6, 7 |
| ADR-007 | PR-01 | 4, 7 |
| ADR-008 | PR-04 | 5, 7 |
| ADR-009 | PR-09 | 8 |
| ADR-010 | PR-07 | 12 |
| ADR-011 | PR-06 | 4, 12 |
| ADR-012 | PR-02 | 9 |
