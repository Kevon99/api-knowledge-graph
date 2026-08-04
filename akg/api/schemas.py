"""Esquemas Pydantic de la API REST v1 (contratos OpenAPI, SAD cap. 9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ApiError(BaseModel):
    error: ApiErrorDetail


def error_response(code: str, message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(error=ApiErrorDetail(code=code, message=message, details=details))


# ── Workspace ───────────────────────────────────────────────────────────────────


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkspaceList(BaseModel):
    items: list[WorkspaceOut]
    total: int


# ── Import ──────────────────────────────────────────────────────────────────────


class ImportCreate(BaseModel):
    workspace_id: uuid.UUID
    source_format: str = Field(default="burp_json", pattern=r"^[a-z0-9_]+$")
    config: dict[str, Any] | None = None


class StageStatus(BaseModel):
    stage: str
    status: str
    processed: int


class ImportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    workspace_id: uuid.UUID
    source_format: str
    source_file_name: str
    status: str
    pipeline_version: str | None = None
    totals: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class ImportDetailOut(ImportOut):
    stages: list[StageStatus] = Field(default_factory=list)


class ImportList(BaseModel):
    items: list[ImportOut]
    total: int


# ── Pipeline result ─────────────────────────────────────────────────────────────


class PipelineResult(BaseModel):
    import_id: uuid.UUID
    workspace_id: uuid.UUID
    status: str
    pipeline_version: str
    parsed: int
    parse_errors: int
    normalized: int
    templates: dict[str, int] | None = None
    extracted: dict[str, int] | None = None
    materialized: dict[str, int] | None = None
    correlation: dict[str, int] | None = None
    persisted: dict[str, int] | None = None
    error: str | None = None


# ── Graph ───────────────────────────────────────────────────────────────────────


class GraphQuery(BaseModel):
    cypher: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=100, ge=1, le=1000)


class GraphNode(BaseModel):
    id: str
    labels: list[str]
    properties: dict[str, Any]


class GraphEdge(BaseModel):
    id: str
    type: str
    source: str
    target: str
    properties: dict[str, Any]


class GraphSummary(BaseModel):
    node_counts: dict[str, int]
    relationship_counts: dict[str, int]


class ExchangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    import_id: uuid.UUID
    order: int
    timestamp: datetime
    host: str
    port: int
    scheme: str
    method: str
    path: str
    resp_status_code: int
    req_has_json: bool
    resp_has_json: bool


# ── Vistas v0.1 (V0.1-32) ──────────────────────────────────────────────────────


class HeaderOut(BaseModel):
    direction: str
    name: str
    value: str | None = None


class CookieOut(BaseModel):
    direction: str
    name: str
    value: str | None = None
    attributes: dict[str, Any] | None = None


class BodyOut(BaseModel):
    direction: str
    content_type: str | None = None
    body: dict[str, Any] | None = None


class OccurrenceOut(BaseModel):
    entity_type: str
    entity_label: str | None = None
    value_hash: str
    path: str | None = None
    location: str
    sensitive: bool


class ExchangeDetailOut(ExchangeOut):
    headers: list[HeaderOut] = Field(default_factory=list)
    cookies: list[CookieOut] = Field(default_factory=list)
    bodies: list[BodyOut] = Field(default_factory=list)
    occurrences: list[OccurrenceOut] = Field(default_factory=list)
    raw_request: str | None = None


class EndpointValueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    param: str
    value: str | None = None
    value_hash: str | None = None
    count: int
    last_seen: datetime


class EndpointTemplateOut(BaseModel):
    id: uuid.UUID
    method: str
    pattern: str
    host_pattern: str | None = None
    confidence: str
    values: list[EndpointValueOut] = Field(default_factory=list)


class EndpointTemplateList(BaseModel):
    items: list[EndpointTemplateOut]
    total: int


class EntityList(BaseModel):
    items: list[OccurrenceOut]
    total: int


class EntitySummaryOut(BaseModel):
    entity_type: str
    count: int


class EntitySummaryList(BaseModel):
    items: list[EntitySummaryOut]
    total: int


class AlertOut(BaseModel):
    id: uuid.UUID
    import_id: uuid.UUID
    rule_id: str
    severity: str
    status: str
    title: str
    description: str | None = None
    evidence: dict | None = None
    confidence: float | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertList(BaseModel):
    items: list[AlertOut]
    total: int


class RuleRunOut(BaseModel):
    id: uuid.UUID
    import_id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None = None
    rules_checked: int
    alerts_created: int
    status: str

    model_config = ConfigDict(from_attributes=True)


class AlertDetailOut(AlertOut):
    context_subgraph: dict | None = None
    exchange_ids: list[str] = []
    node_keys: list[str] = []
    host: str | None = None


class AlertStatusUpdate(BaseModel):
    status: Literal["OPEN", "TRIAGED", "FALSE_POSITIVE", "CONFIRMED", "CLOSED"]


__all__ = [
    "ApiError",
    "WorkspaceCreate",
    "WorkspaceOut",
    "WorkspaceList",
    "ImportCreate",
    "StageStatus",
    "ImportOut",
    "ImportDetailOut",
    "ImportList",
    "PipelineResult",
    "GraphQuery",
    "GraphNode",
    "GraphEdge",
    "GraphSummary",
    "ExchangeOut",
    "ExchangeDetailOut",
    "HeaderOut",
    "CookieOut",
    "BodyOut",
    "OccurrenceOut",
    "EndpointTemplateOut",
    "EndpointTemplateList",
    "EndpointValueOut",
    "EntityList",
    "EntitySummaryOut",
    "EntitySummaryList",
    "AlertOut",
    "AlertList",
    "AlertDetailOut",
    "AlertStatusUpdate",
    "RuleRunOut",
    "error_response",
]
