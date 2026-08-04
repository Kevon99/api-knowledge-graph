# 1. Introducción

> **Capítulo 1 de 15** — Contexto, problema, objetivos, alcance, filosofía y criterios de éxito del proyecto **API Knowledge Graph**.

---

## 1.1 Propósito de este capítulo

Este capítulo establece el contexto en el que nace el proyecto, el problema que resuelve, los objetivos de negocio y técnicos, el alcance de la primera versión, la filosofía de diseño y los criterios con los que se medirá el éxito del producto. Sirve como punto de partida conceptual para el resto del documento de arquitectura.

## 1.2 Contexto del problema

Durante una auditoría de una API REST, un analista genera fácilmente **decenas de miles de peticiones HTTP**. Las herramientas existentes de interceptación y análisis de tráfico (Burp Suite, OWASP ZAP, mitmproxy) y las plataformas de observabilidad son excelentes para **capturar** y **mostrar** tráfico, pero presentan una limitación fundamental:

> **Muestran el tráfico como una secuencia lineal de peticiones y respuestas, obligando al analista a reconstruir mentalmente cómo interactúan los componentes de la aplicación.**

Esta reconstrucción mental es lenta, propensa a errores y altamente dependiente de la experiencia del auditor. Preguntas que deberían ser triviales requieren trabajo manual intensivo.

### 1.2.1 Preguntas que hoy requieren trabajo manual

| # | Pregunta | Esfuerzo manual actual |
|---|----------|------------------------|
| Q1 | ¿Qué endpoints utilizan el mismo JWT? | Buscar/agrupar valores de `Authorization` en miles de líneas |
| Q2 | ¿Qué flujo sigue un usuario desde el login hasta el pago? | Seguir manualmente IDs de sesión y de objeto a través del tráfico |
| Q3 | ¿Qué objetos de negocio aparecen en diferentes módulos? | Rastrear `customerId`, `orderId`, `invoiceId` en cuerpos JSON |
| Q4 | ¿Qué recursos son accesibles con el mismo token? | Correlacionar token ↔ endpoints manualmente |
| Q5 | ¿Qué endpoints pertenecen al mismo microservicio? | Inferir por host, prefijo de ruta o convención |
| Q6 | ¿Qué parámetros se reutilizan durante toda la navegación? | Analizar nombres de parámetros en toda la sesión |
| Q7 | ¿Qué rutas exponen información sensible? | Revisar respuestas y marcar campos sensibles |

La herramienta propuesta **automatiza** estas respuestas generando un modelo de conocimiento de la aplicación.

## 1.3 Hipótesis del proyecto

El proyecto parte de la siguiente hipótesis central:

> **HIP-H1 — Del tráfico al conocimiento.** Es posible transformar de forma automatizada un conjunto de peticiones HTTP capturadas en un grafo de conocimiento que represente fielmente el comportamiento interno de una aplicación: sus flujos de autenticación, sus recursos de negocio, su infraestructura y sus permisos.

Hipótesis secundarias que el proyecto debe validar:

- **HIP-H2 — Relaciones implícitas.** La mayoría de las relaciones útiles (token→endpoint, recurso→módulo, flujo→objetivo) pueden inferirse automáticamente mediante correlación de valores, patrones de ruta y contexto temporal, sin intervención manual.
- **HIP-H3 — Confianza graduada.** Es viable y útil representar el conocimiento con niveles de confianza (evidencia, inferencia, hipótesis) para distinguir hechos observados de conjeturas.
- **HIP-H4 — Ahorro de tiempo.** El modelo resultante reduce el tiempo de "comprender una API desconocida" en al menos un orden de magnitud respecto al análisis manual.
- **HIP-H5 — Valor de seguridad.** Sobre el grafo pueden ejecutarse reglas que detectan automáticamente patrones de riesgo (IDOR/BOLA, tokens sobreprivilegiados, endpoints sin auth, etc.) con contexto rico.

## 1.4 Objetivos

### 1.4.1 Objetivo principal

Construir una plataforma que reciba como entrada tráfico HTTP capturado y genere automáticamente un **modelo navegable del funcionamiento de la aplicación**, basado en un grafo de conocimiento donde cada elemento observado se convierte en una entidad relacionada con el resto del sistema.

### 1.4.2 Objetivos de negocio (NO)

| Código | Objetivo | Métrica |
|--------|----------|---------|
| NO-1 | Reducir el tiempo de entendimiento de una API desconocida | Tiempo desde importación a respuesta de una pregunta compleja |
| NO-2 | Descubrir automáticamente relaciones ocultas | % de relaciones detectadas sin intervención manual |
| NO-3 | Asistir al auditor con alertas de seguridad contextualizadas | Nº de reglas accionables / falsos positivos |
| NO-4 | Convertirse en la referencia (BloodHound de las APIs) | Adopción por auditores y comunidad |

### 1.4.3 Objetivos técnicos (TO)

| Código | Objetivo | Detalle |
|--------|----------|---------|
| TO-1 | Independencia del origen de datos | Núcleo desacoplado de Burp; adaptadores de importación |
| TO-2 | Escalabilidad del pipeline | Procesar 100k+ peticiones en minutos |
| TO-3 | Modelo de conocimiento formal | Esquema de grafo versionado y documentado |
| TO-4 | Confianza explícita | Evidencia / Inferencia / Hipótesis en cada relación |
| TO-5 | Extensibilidad de reglas | DSL de reglas, catálogo versionado |
| TO-6 | API-first | Toda la funcionalidad accesible vía API interna |
| TO-7 | Privacidad | Capacidad de redacción/omisión de datos sensibles |

## 1.5 Filosofía del proyecto

> El proyecto **no pretende almacenar peticiones. Pretende almacenar conocimiento.**

Los principios operativos que rigen el diseño:

1. **Cada request representa evidencia.** Las peticiones y respuestas son materia prima, no el producto final.
2. **Cada evidencia genera relaciones.** El valor surge de las conexiones, no de los eventos individuales.
3. **Las relaciones construyen un modelo.** El modelo es el artefacto navegable.
4. **El modelo permite razonar sobre la superficie de ataque.** Sobre él se ejecutan reglas y consultas de seguridad.

## 1.6 Alcance

### 1.6.1 Dentro del alcance

- Importación de tráfico HTTP desde Burp Suite Logger (primera fuente).
- Normalización de rutas a plantillas de recursos.
- Detección de entidades: tokens (JWT, API Keys, OAuth/OIDC), cookies, sesiones, roles, scopes, objetos JSON, recursos REST, dominios/subdominios, servicios, archivos.
- Motor de correlación con niveles de confianza.
- Construcción y consulta de un grafo de conocimiento (Neo4j).
- Motor de reglas con alertas contextuales.
- API REST interna.
- UI web con vistas: autenticación, recursos, infraestructura, permisos, timeline.
- Hoja de ruta por versiones (v0.1 → v3.0).

### 1.6.2 Fuera del alcance (non-goals)

| Código | Non-goal | Motivo |
|--------|----------|--------|
| NG-1 | Proxy de interceptación en tiempo real | Ya lo cubren Burp/ZAP/mitmproxy; la plataforma es post-procesamiento |
| NG-2 | Visor RAW de tráfico (reemplazo de Burp) | La plataforma trabaja sobre el conocimiento, no sobre el byte-stream |
| NG-3 | Escáner de vulnerabilidades activo (fuzzing, inyección) | V0.x no envía tráfico; el análisis es pasivo sobre evidencia |
| NG-4 | Intérprete de tráfico mediante LLM en v1 | La IA opera sobre el conocimiento estructurado, no sobre el tráfico crudo (v2+) |
| NG-5 | Almacenamiento a largo plazo de tráfico masivo | Se retienen datos con política de retención y redacción |
| NG-6 | Multiusuario/cloud en v1 | v0.1–v1.0 son locales y de un solo analista; multiusuario llega en v2+ |

## 1.7 Partes interesadas

| Rol | Interés principal |
|-----|-------------------|
| Auditor de seguridad | Entender APIs rápidamente, detectar riesgos |
| Investigador | Validar hipótesis de correlación automática |
| Desarrollador backend | Pipeline, motores, API |
| Desarrollador frontend | Visualización de grafos y vistas |
| DevOps | Despliegue, escalado, observabilidad |
| (futuro) Cliente enterprise | Multiusuario, cloud, integraciones |

## 1.8 Entradas y salidas del sistema (visión general)

```
Entradas                             Procesos                          Salidas
───────────                          ─────────                          ────────
Burp Logger export ──► ┌─────────────┴─────────────┐ ──► Grafo de conocimiento (Neo4j)
HAR (v2+)       ──► ──► Importación → Normalización ──► Evidencia relacional (PostgreSQL)
OpenAPI (v2+)   ──► ──► → Extracción → Correlación ──► Alertas de reglas
mitmproxy (v2+) ──► ──► → Materialización           ──► Vistas navegables (UI)
PCAP (v3+)      ──► └─────────────────────────────┘ ──► API REST interna
```

## 1.9 Criterios de éxito

El proyecto se considera exitoso cuando:

1. Un analista puede importar un export de Burp Logger de una API real y **obtener un grafo navegable en menos de 10 minutos** de procesamiento.
2. El sistema responde automáticamente las preguntas Q1–Q7 de la sección 1.2.1 sin intervención manual.
3. Las relaciones inferidas tienen una **precisión superior al 90%** en conjuntos de datos de prueba etiquetados (fase de investigación).
4. El motor de reglas genera alertas con **menos de un 20% de falsos positivos** en las categorías principales (IDOR, tokens reutilizados, endpoints sin auth).
5. El 100% de la funcionalidad está disponible vía API interna (API-first).
6. La arquitectura permite añadir una nueva fuente de importación (p. ej. HAR) **sin cambios en el núcleo**.

## 1.10 Convenciones del documento

- **Identificadores**: elementos importantes se referencian con códigos (p. ej. `NO-1`, `ADR-003`, `REL-USES`, `NODE-JWT`).
- **Niveles de confianza**: `EVIDENCIA`, `INFERENCIA`, `HIPOTESIS`.
- **Severidad de reglas**: `CRITICA`, `ALTA`, `MEDIA`, `BAJA`, `INFO`.
- **Versiones del producto**: `v0.1` (prototipo), `v1.0` (producto utilizable), `v2.0` (IA + fuentes + multiusuario), `v3.0` (enterprise/plataforma).
- Los diagramas usan **Mermaid** (renderizable en GitHub).

## 1.11 Referencias

- `IDEA.md` — documento de visión del proyecto.
- OWASP API Security Top 10 (2023) — marco de categorías de riesgo.
- RFC 6750 (Bearer Tokens), RFC 7519 (JWT), RFC 9110/9112 (HTTP/1.1).

## 1.12 Estructura del resto del documento

| Capítulo | Tema |
|----------|------|
| 2 | Principios arquitectónicos y ADRs |
| 3 | Arquitectura general (C4) y stack |
| 4 | Pipeline de procesamiento |
| 5 | Modelo de datos (evidencia) |
| 6 | Esquema del grafo |
| 7 | Motor de correlación |
| 8 | Motor de reglas |
| 9 | API interna |
| 10 | Interfaz de usuario |
| 11 | Seguridad y privacidad |
| 12 | Despliegue y operaciones |
| 13 | Hoja de ruta v0.1–v3.0 |
| 14 | Riesgos y mitigaciones |
| 15 | Glosario y apéndices |
