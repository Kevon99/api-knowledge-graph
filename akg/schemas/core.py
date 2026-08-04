from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from akg.uuid7 import uuid7


class Header(BaseModel):
    name: str
    value: str
    value_hash: str | None = None
    redacted: bool = False


class Cookie(BaseModel):
    name: str
    value: str
    value_hash: str | None = None
    attributes: dict[str, str] | None = None
    redacted: bool = False


class BodyPayload(BaseModel):
    data: dict[str, Any] | None = None
    text: str | None = None
    content_type: str | None = None
    json_sha256: str | None = None
    size: int | None = None
    truncated: bool = False


class RequestPayload(BaseModel):
    headers: list[Header] = Field(default_factory=list)
    cookies: list[Cookie] = Field(default_factory=list)
    query_params: dict[str, str] = Field(default_factory=dict)
    body: BodyPayload | None = None
    has_json: bool = False


class ResponsePayload(BaseModel):
    status_code: int
    status_text: str | None = None
    headers: list[Header] = Field(default_factory=list)
    cookies: list[Cookie] = Field(default_factory=list)
    body: BodyPayload | None = None
    has_json: bool = False


class Timings(BaseModel):
    total_ms: int | None = None


class RawExchange(BaseModel):
    """Formato canónico intermedio producido por los adaptadores de importación."""

    exchange_id: uuid.UUID = Field(default_factory=uuid7)
    import_id: uuid.UUID | None = None
    order: int = 0
    timestamp: datetime
    host: str
    port: int = 443
    scheme: str = "https"
    method: str
    path: str
    query_string: str | None = None
    template: str | None = None
    path_params: dict[str, str] | None = None
    client_ip: str | None = None
    request: RequestPayload
    response: ResponsePayload
    timings: Timings | None = None


class NormalizedExchange(RawExchange):
    """Exchange con campos poblados tras la normalización."""

    template: str
    path_params: dict[str, str]


class EntityOccurrenceSchema(BaseModel):
    """Ocurrencia de una entidad detectada en un exchange."""

    import_id: uuid.UUID | None = None
    exchange_id: uuid.UUID
    entity_type: str
    entity_label: str | None = None
    value: str | None = None
    value_hash: str
    path: str | None = None
    location: str
    sensitive: bool = False
    redacted: bool = False
    timestamp: datetime


class ImportStatus(BaseModel):
    id: uuid.UUID
    status: str
    totals: dict | None = None
    stage_error: dict | None = None
    progress: list[dict] | None = None  # stage statuses
