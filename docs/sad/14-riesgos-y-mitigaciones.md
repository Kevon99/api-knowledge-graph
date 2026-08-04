# 14. Riesgos y Mitigaciones

> **Capítulo 14 de 15** — Identificación y gestión de riesgos técnicos, de producto y de investigación. Matriz de riesgos con probabilidad, impacto y mitigaciones.

---

## 14.1 Metodología

Cada riesgo se evalúa con **probabilidad** (Baja/Media/Alta) e **impacto** (Bajo/Medio/Alto). El nivel global determina la prioridad de mitigación.

Escala de nivel de riesgo: **Rojo** (actuar ya), **Ámbar** (mitigar en la versión actual), **Verde** (monitorizar).

## 14.2 Matriz de riesgos

| ID | Riesgo | Prob. | Impacto | Nivel | Mitigación |
|----|--------|-------|---------|-------|------------|
| R-01 | Correlación demasiado ruidosa (falsas relaciones) | Media | Alto | Rojo | Golden dataset, métricas tempranas, umbrales, confianza explícita (7.10) |
| R-02 | Sobre-normalización de rutas (endpoints falsos) | Media | Medio | Ámbar | Umbrales de cardinalidad, segmentos protegidos, patrón puro vs restringido (4.3.3) |
| R-03 | Falsos positivos en reglas que desacrediten el producto | Media | Alto | Rojo | Evaluación < 20% FP, severidad graduada, dry-run, deduplicación (8.7) |
| R-04 | Rendimiento insuficiente en datasets grandes | Media | Alto | Ámbar | Sharding, batch Cypher, particionamiento, dimensionamiento (3.8, 12.6) |
| R-05 | Escala del esquema del grafo (migraciones) | Baja | Medio | Verde | Versionado estricto del esquema, scripts idempotentes (6.8) |
| R-06 | Alucinaciones de la IA (v2) | Media | Alto | Ámbar | Citas obligatorias, subgrafo acotado, validación de patrones (13.4) |
| R-07 | Fuga de datos sensibles | Baja | Alto | Ámbar | Redacción por defecto, hash-only, local-first, sandbox (11) |
| R-08 | Violación de NDA/contratos por retención de datos | Media | Medio | Ámbar | Modo privacy-first, retención configurable, borrado (11.8) |
| R-09 | Cambios en el formato de export de Burp | Media | Medio | Verde | Adaptadores aislados, versionado de formatos, fixtures de prueba |
| R-10 | Baja adopción por parte de auditores | Media | Alto | Rojo | Validación temprana con analistas reales (v1.0), demo, valor Q1–Q7 |
| R-11 | Confianza del analista en inferencias incorrectas | Media | Alto | Rojo | Confianza explícita (Evidencia/Inferencia/Hipótesis), nunca promover hipótesis sin confirmar |
| R-12 | Coste operativo de mantener 2 BBDD (PG+Neo4j) | Media | Medio | Ámbar | Capa de repositorio única, re-materialización desde evidencia (3.7.2) |
| R-13 | Token de sesión que rompe correlación por SSO | Baja | Bajo | Verde | No deducir identidad de una sola cookie (7.10) |
| R-14 | Scope creep en v3.0 (enterprise prematuro) | Media | Medio | Ámbar | Open-core, priorización por demanda (13.7) |
| R-15 | Dependencia de GDS/APOC (licencias, disponibilidad) | Baja | Bajo | Verde | GDS solo en v2+; esquema v1 sin dependencias |

## 14.3 Detalle de los riesgos críticos

### 14.3.1 R-01 — Correlación ruidosa

**Descripción**: El motor de correlación por valor puede generar relaciones falsas (p. ej., un valor `1` reutilizado como ID en múltiples endpoints distintos que no están realmente relacionados).

**Mitigaciones**:
1. Entropía mínima de valores (descarte de `1`, `true`, fechas).
2. Umbral de ocurrencias (`min_occurrences_for_inference`).
3. Confianza explícita + `score` con penalizaciones.
4. Medición continua con golden dataset (7.13).
5. Capacidad del analista de "explicar la relación" (qué evidencia la sustenta).

### 14.3.2 R-03 — Falsos positivos en reglas

**Descripción**: Alertas incorrectas erosionan la confianza y la utilidad del producto.

**Mitigaciones**:
1. Reglas con severidad graduada (INFO/MEDIA para señales débiles).
2. `dry-run` y modo preview.
3. Evaluación automatizada sobre golden dataset (8.9).
4. Ciclo de vida de alertas que permite marcar FP y realimenta la mejora de reglas.

### 14.3.3 R-11 — Confianza del analista en inferencias

**Descripción**: Un analista que asume que una `INFERENCIA` es un hecho observado podría reportar falsos hallazgos o perder un hallazgo real.

**Mitigaciones**:
1. Representación visual distinta de los tres niveles (capítulo 10.4.1).
2. Toda relación con `evidence` navegable.
3. Política: las hipótesis nunca se promueven automáticamente.
4. Formación y documentación del significado de cada nivel.

## 14.4 Riesgos de investigación

| ID | Riesgo | Mitigación |
|----|--------|------------|
| RI-01 | El golden dataset es difícil de anonimizar | Herramientas de anonimización, datasets sintéticos realistas |
| RI-02 | Métricas de correlación dependen del dominio (REST vs GraphQL) | Múltiples datasets de dominios distintos (REST, microservicios, monolito) |
| RI-03 | IA no mejora sustancialmente la productividad | Evaluación con usuarios (tiempo por tarea), iteración del diseño de retrieval |

## 14.5 Registro de decisiones sobre riesgos

Todo riesgo aceptado se documenta en el repo (`docs/risks.md`) con responsable y plan de seguimiento. Los riesgos rojos se revisan en cada planificación de sprint.

## 14.6 Indicadores tempranos de alerta

| Señal | Riesgo implicado |
|-------|------------------|
| Precision < 85% en correlación en v0.1 | R-01 |
| FP > 25% en alguna categoría de reglas | R-03 |
| Import de 100k > 30 min | R-04 |
| Consulta de grafo > 5 s en vistas de auditor | R-04 |
| Pérdida de un valor sensible en logs | R-07 |
| Feedback negativo de 2+ auditores en prueba | R-10 |
