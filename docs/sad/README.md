# API Knowledge Graph — Software Architecture Document (SAD)

**Documento de Arquitectura de Software del proyecto API Knowledge Graph.**

Versión del documento: `1.0-draft`
Fecha: 2026-08-03
Estado: Aprobado para implementación inicial
Repositorio: `api_Grapher`
Fuente inspiradora: `IDEA.md`

---

## Propósito

Este documento define la arquitectura técnica, el modelo de datos, el esquema del grafo, el motor de correlación, el sistema de reglas, la API interna y la hoja de ruta por versiones (v0.1 → v3.0) del proyecto **API Knowledge Graph**: una plataforma que transforma tráfico HTTP capturado (inicialmente desde Burp Suite Logger) en un **grafo de conocimiento** navegable del comportamiento real de una aplicación, orientado al análisis de seguridad de APIs.

El objetivo del documento es servir como **base de implementación ordenada y escalable**: cualquier desarrollador debe poder abrir esta carpeta y entender qué construir, en qué orden y con qué contratos técnicos.

---

## Estructura del Documento

| # | Archivo | Contenido |
|---|---------|-----------|
| 1 | [01-introduccion.md](./01-introduccion.md) | Contexto, problema, objetivos, alcance, filosofía y criterios de éxito |
| 2 | [02-principios-y-adrs.md](./02-principios-y-adrs.md) | Principios arquitectónicos y Decisiones de Arquitectura (ADRs) |
| 3 | [03-arquitectura-general.md](./03-arquitectura-general.md) | Arquitectura C4: contexto, contenedores, componentes, stack tecnológico |
| 4 | [04-pipeline-de-procesamiento.md](./04-pipeline-de-procesamiento.md) | Pipeline ETL del conocimiento: importación, normalización, extracción, correlación, materialización |
| 5 | [05-modelo-de-datos.md](./05-modelo-de-datos.md) | Modelo de datos relacional (capa de evidencia) |
| 6 | [06-esquema-del-grafo.md](./06-esquema-del-grafo.md) | Esquema del grafo de conocimiento (Neo4j): nodos, relaciones, índices |
| 7 | [07-motor-de-correlacion.md](./07-motor-de-correlacion.md) | Motor de correlación: algoritmos, modelo de confianza, resolución de entidades |
| 8 | [08-motor-de-reglas.md](./08-motor-de-reglas.md) | Sistema de reglas: DSL, catálogo, ciclo de vida, alertas |
| 9 | [09-api-interna.md](./09-api-interna.md) | API REST interna: contratos, autenticación, paginación, error model |
| 10 | [10-interfaz-de-usuario.md](./10-interfaz-de-usuario.md) | Vistas del sistema y frontend |
| 11 | [11-seguridad-y-privacidad.md](./11-seguridad-y-privacidad.md) | Manejo de datos sensibles, cifrado, privacidad |
| 12 | [12-despliegue-y-operaciones.md](./12-despliegue-y-operaciones.md) | Despliegue, escalado, observabilidad, CI/CD |
| 13 | [13-hoja-de-ruta.md](./13-hoja-de-ruta.md) | Hoja de ruta por versiones: v0.1, v1.0, v2.0, v3.0 |
| 14 | [14-riesgos-y-mitigaciones.md](./14-riesgos-y-mitigaciones.md) | Riesgos técnicos y de producto, mitigaciones |
| 15 | [15-glosario-y-apendices.md](./15-glosario-y-apendices.md) | Glosario y apéndices técnicos |
| 16 | [16-backlog-de-implementacion.md](./16-backlog-de-implementacion.md) | Backlog de implementación: tareas ordenadas por versión y dependencia |

---

## Resumen Ejecutivo

**API Knowledge Graph** convierte tráfico HTTP en conocimiento estructurado. El sistema:

1. **Importa** tráfico capturado (Burp Suite Logger en v0.1; HAR, OpenAPI, mitmproxy, PCAP, etc. en versiones posteriores).
2. **Normaliza** rutas dinámicas en plantillas de recursos (`GET /users/15` → `GET /users/{id}`).
3. **Identifica entidades** (JWTs, cookies, objetos JSON, roles, scopes, recursos, dominios, servicios...).
4. **Correlaciona** evidencia para descubrir relaciones (mismo token usado en N endpoints, mismo `customerId` recorriendo módulos...).
5. **Construye un grafo de conocimiento** con niveles de confianza (Evidencia / Inferencia / Hipótesis).
6. **Ejecuta reglas** de seguridad que producen alertas enriquecidas con contexto del grafo.
7. **Expone una API interna** y una interfaz web con vistas especializadas (autenticación, recursos, infraestructura, permisos, timeline).

El objetivo final del proyecto es convertirse en lo que **BloodHound** es para Active Directory, aplicado al análisis de APIs modernas.

---

## Stack Tecnológico Propuesto (resumen)

| Capa | Tecnología | Justificación |
|------|-----------|---------------|
| Backend | Go o Python (FastAPI) | Rendimiento para pipelines + ecosistema de análisis; se detalla en ADR-005 |
| Base relacional (evidencia) | PostgreSQL | Transacciones, JSONB, integridad |
| Grafo | Neo4j | Grafo de conocimiento maduro, Cypher, algoritmos de grafo embebidos |
| Mensajería | Redis Streams / RabbitMQ | Desacoplamiento del pipeline |
| Colas de trabajo | Celery (Python) / workers nativos | Procesamiento asíncrono de importaciones |
| Frontend | React + TypeScript + Cytoscape.js | Visualización de grafos, ecosistema maduro |
| Contenedores | Docker / Docker Compose / Kubernetes | Portabilidad y escalado |
| Observabilidad | OpenTelemetry + Prometheus + Grafana | Trazas del pipeline, métricas |

> El detalle completo y las justificaciones están en `03-arquitectura-general.md` y en los ADRs de `02-principios-y-adrs.md`.

---

## Cómo usar este documento

- **Para entender el "qué" y el "por qué"**: leer capítulos 1 y 2.
- **Para implementar la arquitectura base**: capítulos 3, 4 y 12.
- **Para implementar el modelo de datos**: capítulos 5 y 6.
- **Para implementar el motor de correlación y reglas**: capítulos 7 y 8.
- **Para implementar la API y el frontend**: capítulos 9 y 10.
- **Para planificar el trabajo**: capítulo 13 (hoja de ruta).

Cada capítulo es autocontenido en lo posible, pero se referencia explícitamente a otros cuando hay dependencias.

---

## Estado de implementación

| Módulo | Estado |
|--------|--------|
| Documento de arquitectura | Definido (este documento) |
| Código base | No iniciado |
| Importer Burp (v0.1) | No iniciado |
| Normalizador de rutas | No iniciado |
| Motor de correlación | No iniciado |
| Motor de reglas | No iniciado |
| API interna | No iniciado |
| UI | No iniciado |

Ver `13-hoja-de-ruta.md` para el detalle de lo que se debe construir en cada versión.
