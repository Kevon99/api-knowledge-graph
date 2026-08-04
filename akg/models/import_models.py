from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from akg.database import Base
from akg.uuid7 import uuid7


def utcnow() -> datetime:
    return datetime.now(UTC)


# ── Workspace ──────────────────────────────────────────────────────────────────


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=utcnow, onupdate=utcnow
    )

    imports = relationship("Import", back_populates="workspace", cascade="all, delete-orphan")


# ── Import ─────────────────────────────────────────────────────────────────────

IMPORT_STATUS = Enum(
    "PENDING",
    "PARSING",
    "PARSED",
    "NORMALIZING",
    "NORMALIZED",
    "EXTRACTING",
    "EXTRACTED",
    "CORRELATING",
    "CORRELATED",
    "MATERIALIZING",
    "MATERIALIZED",
    "RULES",
    "COMPLETED",
    "FAILED",
    "PAUSED",
    name="import_status",
)


class Import(Base):
    __tablename__ = "imports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    source_format: Mapped[str] = mapped_column(String(50), nullable=False)
    source_file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(IMPORT_STATUS, nullable=False, default="PENDING")
    stage_error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    totals: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    pipeline_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    redaction_policy: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=utcnow, onupdate=utcnow
    )

    workspace = relationship("Workspace", back_populates="imports")
    stages = relationship("ImportStage", back_populates="import_", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="import_", cascade="all, delete-orphan")


# ── Import Stage (progreso del pipeline) ────────────────────────────────────────

STAGE_ENUM = Enum(
    "parse",
    "normalize",
    "extract",
    "correlate",
    "materialize",
    "rules",
    name="stage_name",
)
STAGE_STATUS = Enum("PENDING", "RUNNING", "DONE", "FAILED", name="stage_status")


class ImportStage(Base):
    __tablename__ = "import_stages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("imports.id"), nullable=False
    )
    stage: Mapped[str] = mapped_column(STAGE_ENUM, nullable=False)
    shard: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(STAGE_STATUS, nullable=False, default="PENDING")
    processed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        # unique per (import_id, stage, shard) for idempotent resumption
        __import__("sqlalchemy").UniqueConstraint("import_id", "stage", "shard"),
    )

    import_ = relationship("Import", back_populates="stages")


# ── HTTP Exchange ──────────────────────────────────────────────────────────────


class HttpExchange(Base):
    __tablename__ = "http_exchanges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("imports.id"), nullable=False, index=True
    )
    order: Mapped[int] = mapped_column(BigInteger, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(nullable=False)
    scheme: Mapped[str] = mapped_column(String(10), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    query_string: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("endpoint_templates.id"), nullable=True, index=True
    )
    path_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    req_headers_count: Mapped[int] = mapped_column(nullable=False, default=0)
    resp_status_code: Mapped[int] = mapped_column(nullable=False)
    resp_headers_count: Mapped[int] = mapped_column(nullable=False, default=0)
    req_has_json: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resp_has_json: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    req_body_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resp_body_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_ms: Mapped[int | None] = mapped_column(nullable=True)
    client_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        __import__("sqlalchemy").Index("ix_http_exchanges_import_order", "import_id", "order"),
        __import__("sqlalchemy").Index("ix_http_exchanges_host", "host"),
    )

    occurrences = relationship(
        "EntityOccurrence", back_populates="exchange", cascade="all, delete-orphan"
    )


# ── Headers ────────────────────────────────────────────────────────────────────


class HttpHeader(Base):
    __tablename__ = "http_headers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("http_exchanges.id"), nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(
        Enum("request", "response", name="header_direction"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# ── Cookies ────────────────────────────────────────────────────────────────────


class HttpCookie(Base):
    __tablename__ = "http_cookies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("http_exchanges.id"), nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(
        Enum("request", "response", name="cookie_direction"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# ── Body JSON ──────────────────────────────────────────────────────────────────


class BodyJson(Base):
    __tablename__ = "body_json"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("http_exchanges.id"), nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(
        Enum("request", "response", name="body_direction"), nullable=False
    )
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    json_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stored_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# ── Parse Errors ───────────────────────────────────────────────────────────────


class ParseError(Base):
    __tablename__ = "parse_errors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("imports.id"), nullable=False
    )
    source_line: Mapped[int | None] = mapped_column(nullable=True)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_fragment: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── Endpoint Template (ruta normalizada) ───────────────────────────────────────


class EndpointTemplate(Base):
    __tablename__ = "endpoint_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("imports.id"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    host_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    segments: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cardinality: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    restricted: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(
        Enum("EVIDENCIA", "INFERENCIA", "HIPOTESIS", name="confidence_level"),
        nullable=False,
        default="EVIDENCIA",
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=utcnow)

    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint("import_id", "method", "pattern", "host_pattern"),
    )


class EndpointValue(Base):
    __tablename__ = "endpoint_values"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("endpoint_templates.id"), nullable=False, index=True
    )
    param: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(nullable=False, default=1)


# ── Entity Occurrence (corazón de la extracción) ───────────────────────────────


class EntityOccurrence(Base):
    __tablename__ = "entity_occurrences"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("http_exchanges.id"), nullable=False, index=True
    )
    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("imports.id"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_hash: Mapped[str | None] = mapped_column(String(64), nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str] = mapped_column(
        Enum(
            "request.header",
            "request.query",
            "request.body",
            "request.cookie",
            "response.header",
            "response.body",
            "response.cookie",
            "path",
            name="location_enum",
        ),
        nullable=False,
    )
    sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_seen: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    __table_args__ = (
        __import__("sqlalchemy").Index(
            "ix_occurrences_type_label_hash", "entity_type", "entity_label", "value_hash"
        ),
        __import__("sqlalchemy").Index("ix_occurrences_value_hash", "value_hash"),
    )

    exchange = relationship("HttpExchange", back_populates="occurrences")


# ── Rule ───────────────────────────────────────────────────────────────────────


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    rule_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(
        Enum("CRITICA", "ALTA", "MEDIA", "BAJA", "INFO", name="severity"), nullable=False
    )
    dsl: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    references: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (__import__("sqlalchemy").UniqueConstraint("rule_id", "version"),)


class RuleRun(Base):
    __tablename__ = "rule_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("imports.id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    rules_checked: Mapped[int] = mapped_column(nullable=False, default=0)
    alerts_created: Mapped[int] = mapped_column(nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        Enum("RUNNING", "COMPLETED", "FAILED", name="run_status"), nullable=False
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("imports.id"), nullable=False
    )
    rule_id: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_runs.id"), nullable=True
    )
    severity: Mapped[str] = mapped_column(
        Enum("CRITICA", "ALTA", "MEDIA", "BAJA", "INFO", name="alert_severity"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum("OPEN", "TRIAGED", "FALSE_POSITIVE", "CONFIRMED", "CLOSED", name="alert_status"),
        nullable=False,
        default="OPEN",
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    context_subgraph: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=utcnow, onupdate=utcnow
    )

    import_ = relationship("Import", back_populates="alerts")
