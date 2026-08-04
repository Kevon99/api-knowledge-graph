# 11. Seguridad y Privacidad

> **Capítulo 11 de 15** — Manejo de datos sensibles, redacción, cifrado, privacidad por diseño (PR-08) y consideraciones de seguridad de la propia plataforma.

---

## 11.1 Contexto

El producto procesa datos potencialmente altamente sensibles: tokens de autenticación, cookies de sesión, credenciales, datos personales (PII) que viajan en cuerpos JSON, claves de API. La plataforma debe:

1. Proteger al **analista** (cuyos propios datos no deben filtrarse).
2. Proteger los **datos de la víctima/target** (los del sistema auditado).
3. Ser segura ella misma (la herramienta de seguridad no debe convertirse en una brecha).

## 11.2 Principios de privacidad por diseño

| Principio | Implementación |
|-----------|----------------|
| **Minimización** | Solo se almacena lo necesario para el análisis; el tráfico crudo completo es opcional |
| **Redacción por defecto** | Los valores sensibles se redactan salvo configuración explícita |
| **Local-first** | v0.1–v1.0 funcionan 100% en local; los datos nunca salen del equipo del analista |
| **Retención limitada** | Política de retención configurable por workspace |
| **Trazabilidad de accesos** | Logging de quién accedió a qué (v2+ multiusuario) |
| **Telemetría sin datos** | Los reportes de telemetría opcionales no incluyen valores de tráfico |

## 11.3 Clasificación de datos

| Nivel | Categorías | Tratamiento |
|-------|------------|-------------|
| S1 — Secreto | Credenciales, tokens, API keys, refresh tokens | Hash-only por defecto; jamás en logs |
| S2 — PII | Emails, nombres, direcciones, DNI, tarjetas | Redacción configurable; si se conservan, cifradas |
| S3 — Confidencial | Cuerpos de negocio, headers propietarios | Almacenamiento cifrado, acceso limitado |
| S4 — Público | Métodos, plantillas de ruta, tipos de recurso (sin valores) | Libre dentro del workspace |

La clasificación se aplica en la **extracción** (`entity_occurrences`) y en la **persistencia** (`body_json`, `http_headers`).

## 11.4 Mecanismos de redacción

### 11.4.1 Detección de valores sensibles

| Detector | Ejemplos |
|----------|----------|
| JWT / bearer | `Bearer eyJhbGci...` |
| API keys | `sk_live_...`, `X-API-Key: abc` |
| Cookies de sesión | `session=...`, `PHPSESSID=...` |
| Credenciales | `password`, `passwd`, `client_secret` (por nombre de campo y patrón) |
| PII | emails, teléfonos, NIF/DNI (patrones) |
| Tarjetas | PAN de 13–19 dígitos (Luhn) |
| Tokens OAuth | `access_token`, `refresh_token` |

### 11.4.2 Política por workspace

```yaml
redaction_policy:
  hash_only: [jwt, api_key, bearer_token, session_id, oauth_token, password, client_secret]
  redact_value_keep_schema: [email, phone, pan, pii]     # conserva path/forma
  store_plain: []                                          # explícito si es necesario
  hash_algorithm: sha256
```

- `hash_only`: en BD y grafo solo el `value_hash`; el valor original **no** se persiste.
- `redact_value_keep_schema`: se mantiene el path canónico y el tipo, el valor se sustituye (`***`).
- El analista puede **desbloquear por valor** puntual (con confirmación) para inspeccionar un intercambio concreto (auditoría local).

### 11.4.3 Redacción en UI/API

Todos los endpoints de evidencia aplican la política al serializar. El campo se devuelve como `{redacted: true, kind: "jwt", value_hash: "sha256:..."}`.

## 11.5 Hashing para correlación

La correlación necesita comparar valores sin exponerlos:

- `value_hash = sha256(canonical(normalize(value)))`.
- La canonicalización es **idempotente** para que el mismo valor en distintos formatos produzca el mismo hash (capítulo 7.3).
- El hash del JWT se calcula sobre el token completo **y** sobre `(alg, issuer, subject, exp)` para permitir agrupar "mismos claims, distinto nonce".

## 11.6 Cifrado

| Capa | Mecanismo |
|------|-----------|
| En tránsito | TLS 1.2+; API detrás de reverse proxy TLS (Caddy/nginx) |
| En reposo | Cifrado del volumen (dm-crypt/LUKS en host; EBS/KMS en cloud) |
| Valores S1/S2 (si se conservan) | Cifrado AEAD (AES-256-GCM) con claves por workspace (v2+) |
| Claves de cifrado | Env vars / secret manager; rotación soportada |

## 11.7 Seguridad de la plataforma

### 11.7.1 Autenticación de la API

| Versión | Mecanismo |
|---------|-----------|
| v0.1 | Sin auth (localhost) — solo bind a 127.0.0.1 |
| v1.0 | Clave API de workspace (`X-Api-Key`), bind opcional a red |
| v2.0 | Sesiones JWT, roles admin/auditor/viewer |
| v3.0 | OIDC/SSO, RBAC por workspace, MFA |

### 11.7.2 Sandbox de consultas

- `POST /graph/query` y motor de reglas: **solo lectura** en Neo4j, whitelist de funciones, límite de filas/timeout.
- El DSL de reglas no ejecuta código arbitrario (capítulo 8.5.2).

### 11.7.3 Protección contra abuso local

- Límite de tamaño de subida y de nº de importaciones simultáneas.
- Parsing de archivos con límites (zip-bombs → `source_hash` + límite de tamaño comprimido).
- Sin extracción de archivos a disco con rutas dinámicas (no usar el nombre del upload como ruta).

### 11.7.4 Logging seguro

- Nunca loguear valores S1/S2 en texto plano.
- `request_id`/`import_id` en logs para correlación.
- Nivel de log configurable (dev/prod).

## 11.8 Retención y borrado

| Política | Default | Configurable |
|----------|---------|--------------|
| Evidencia (exchanges, bodies) | Hasta que se borre el workspace | Retención en días |
| Ocurrencias y grafo | Persistente | Re-materializable |
| Logs | 30 días | Sí |
| Uploads temporales | Eliminados tras parseo | — |

Operaciones:
- `DELETE /imports/{id}`: elimina evidencia + subgrafo de la importación.
- `DELETE /workspaces/{id}`: borrado completo (cascade) con confirmación.
- **Borrado seguro** (SHRED) opcional para volúmenes de entornos auditados (v3+).

## 11.9 Cumplimiento y consideraciones legales

| Marco | Relevancia |
|-------|------------|
| GDPR | La redacción de PII y la retención limitada facilitan el cumplimiento |
| NDA/contratos de auditoría | Local-first; el analista controla la salida de datos |
| PCI-DSS | Detección y redacción de PAN; tarjetas nunca en claro |
| Políticas corporativas | Modo "sin almacenamiento de cuerpos" (solo paths + hashes) |

## 11.10 Modo "sin tráfico sensible" (privacy-first profile)

Perfil de configuración que maximiza privacidad:

- No persistir cuerpos JSON ni cabeceras (solo paths canónicos, tipos y hashes).
- No persistir valores S1/S2 (solo hashes).
- El análisis y las reglas siguen funcionando (las reglas usan paths/formas, no valores).
- Adecuado para entornos con políticas estrictas de manejo de datos.

## 11.11 Modelo de amenazas del propio sistema

| Amenaza | Mitigación |
|---------|------------|
| Exfiltración de tokens por consulta maliciosa | Sandbox de lectura, whitelist, límites |
| Acceso no autorizado a la API | Auth por fases (11.7.1), bind local |
| Fuga de secretos en logs | 11.7.4 |
| Data leak vía telemetría | 11.2 |
| Attaque al parser (maldito archivo) | Límites, sandboxing del proceso worker, `source_hash` |
| Acceso al host | Contenedores no-root, capability dropping, TLS |

## 11.12 Checklist de seguridad por versión

| Capacidad | v0.1 | v1.0 | v2.0 | v3.0 |
|-----------|------|------|------|------|
| Redacción por defecto | ✔ | ✔ | ✔ | ✔ |
| Hash-only para secretos | ✔ | ✔ | ✔ | ✔ |
| Auth de API | — (localhost) | API key | JWT+roles | SSO+RBAC |
| Cifrado en reposo de S1/S2 | Volumen | Volumen | AEAD por workspace | AEAD + KMS |
| Sandbox de Cypher | ✔ | ✔ | ✔ | ✔ |
| Auditoría de accesos | — | — | ✔ | ✔ |
| Borrado seguro | — | — | — | ✔ |
