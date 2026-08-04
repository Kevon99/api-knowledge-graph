// API Knowledge Graph — Neo4j schema v1
// Idempotente: ejecutable múltiples veces. Corresponds to SAD chapter 6.
//
// NOTA v0.1: Neo4j no soporta UNIQUE constraints sobre labels compuestos (AKG:Endpoint)
// por lo que se usan labels simples. El namespacing `AKG` se documenta como resultado
// de esta limitación y se revierte con un script de migración si se requiere en el futuro.

// ── Constraints (claves naturales) ─────────────────────────────────────────────────
CREATE CONSTRAINT IF NOT EXISTS FOR (e:Endpoint) REQUIRE (e.method, e.pattern, e.host) IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (h:Host) REQUIRE h.name IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (s:Service) REQUIRE s.name IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (t:Token) REQUIRE (t.token_type, t.value_hash) IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (c:Cookie) REQUIRE (c.name, c.value_hash) IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (r:Resource) REQUIRE r.resource_key IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (p:Principal) REQUIRE (p.kind, p.principal_hash) IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (x:Exchange) REQUIRE x.exchange_id IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (w:Workspace) REQUIRE w.name IS UNIQUE;

// ── Índices de búsqueda frecuente ──────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS FOR (e:Endpoint) ON (e.pattern);
CREATE INDEX IF NOT EXISTS FOR (t:Token)    ON (t.value_hash);
CREATE INDEX IF NOT EXISTS FOR (c:Cookie)   ON (c.value_hash);
CREATE INDEX IF NOT EXISTS FOR (r:Resource) ON (r.resource_type);
CREATE INDEX IF NOT EXISTS FOR (x:Exchange) ON (x.timestamp);
CREATE INDEX IF NOT EXISTS FOR (e:Endpoint) ON (e.import_id);
CREATE INDEX IF NOT EXISTS FOR (r:Resource) ON (r.import_id);
CREATE INDEX IF NOT EXISTS FOR (r:Role)     ON (r.name);
CREATE INDEX IF NOT EXISTS FOR (s:Scope)    ON (s.name);