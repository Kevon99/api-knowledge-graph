"""Repositorio de evidencia (PostgreSQL).

Persiste los datos del modelo canonico (RawExchange) en las tablas relacionales
definidas en el SAD capitulo 5: http_exchanges, http_headers, http_cookies,
body_json. Incluye las metricas/estado de la importacion relacionada.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from akg.database import SessionLocal
from akg.models import (
    Alert,
    BodyJson,
    EndpointTemplate,
    EndpointValue,
    EntityOccurrence,
    HttpCookie,
    HttpExchange,
    HttpHeader,
    Import,
    ImportStage,
    RuleRun,
    Workspace,
)
from akg.schemas import RawExchange

if TYPE_CHECKING:
    from akg.pipeline.normalizer import NormalizeConfig


def _sha256(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EvidenceRepository:
    def __init__(self, session: Session | None = None) -> None:
        self._session = session or SessionLocal()

    def close(self) -> None:
        self._session.close()

    @property
    def session(self) -> Session:
        return self._session

    # ── Workspaces ──────────────────────────────────────────────────────────
    def create_workspace(self, name: str, description: str | None = None) -> Workspace:
        ws = Workspace(name=name, description=description)
        self._session.add(ws)
        self._session.commit()
        return ws

    def list_workspaces(self) -> list[Workspace]:
        return list(self._session.scalars(select(Workspace).order_by(Workspace.name)).all())

    def get_workspace(self, workspace_id: uuid.UUID) -> Workspace | None:
        return self._session.get(Workspace, workspace_id)

    def list_exchanges(self, import_id: uuid.UUID | None = None) -> list[HttpExchange]:
        stmt = select(HttpExchange).order_by(HttpExchange.import_id, HttpExchange.order)
        if import_id is not None:
            stmt = stmt.where(HttpExchange.import_id == import_id)
        return list(self._session.scalars(stmt).all())

    # ── Importaciones ───────────────────────────────────────────────────────
    def create_import(
        self,
        workspace_id: uuid.UUID,
        source_format: str,
        source_file_name: str,
        source_hash: str,
        pipeline_version: str,
    ) -> Import:
        imp = Import(
            workspace_id=workspace_id,
            source_format=source_format,
            source_file_name=source_file_name,
            source_hash=source_hash,
            pipeline_version=pipeline_version,
            status="PENDING",
        )
        self._session.add(imp)
        self._session.commit()
        return imp

    def update_import_status(
        self, import_id: uuid.UUID, status: str, totals: dict | None = None
    ) -> None:
        imp = self._session.get(Import, import_id)
        if imp is None:
            raise KeyError(f"import {import_id} no existe")
        imp.status = status
        if totals is not None:
            imp.totals = totals
        self._session.commit()

    def upsert_stage(
        self,
        import_id: uuid.UUID,
        stage: str,
        shard: int,
        status: str,
        processed: int | None = None,
    ) -> ImportStage:
        # buscar existente para idempotencia
        st = (
            self._session.query(ImportStage)
            .filter_by(import_id=import_id, stage=stage, shard=shard)
            .first()
        )
        if st is None:
            st = ImportStage(import_id=import_id, stage=stage, shard=shard, status=status)
            self._session.add(st)
        else:
            st.status = status
        if processed is not None:
            st.processed = processed
        self._session.commit()
        return st

    # ── Persistencia masiva de exchanges ────────────────────────────────────
    def persist_exchanges(
        self,
        import_id: uuid.UUID,
        exchanges: Sequence[RawExchange],
        template_map: dict[tuple[str, str, str], uuid.UUID] | None = None,
    ) -> dict:
        """Persiste exchanges + headers + cookies + bodies. Devuelve totals."""
        template_map = template_map or {}
        counts = {
            "exchanges": 0,
            "headers": 0,
            "cookies": 0,
            "bodies": 0,
        }

        for ex in exchanges:
            tpl_key = (ex.method.upper(), ex.template or "", ex.host)
            exchange = HttpExchange(
                id=ex.exchange_id,
                import_id=import_id,
                order=ex.order,
                timestamp=ex.timestamp,
                host=ex.host,
                port=ex.port,
                scheme=ex.scheme,
                method=ex.method,
                path=ex.path,
                query_string=ex.query_string,
                template_id=template_map.get(tpl_key),
                req_headers_count=len(ex.request.headers),
                resp_status_code=ex.response.status_code if ex.response else 0,
                resp_headers_count=len(ex.response.headers) if ex.response else 0,
                req_has_json=ex.request.has_json,
                resp_has_json=ex.response.has_json if ex.response else False,
                req_body_size=ex.request.body.size if ex.request.body else 0,
                resp_body_size=ex.response.body.size if ex.response and ex.response.body else 0,
                total_ms=ex.timings.total_ms if ex.timings else None,
            )
            self._session.add(exchange)
            self._session.flush()
            counts["exchanges"] += 1

            # headers de request + response
            for h in ex.request.headers:
                self._session.add(
                    HttpHeader(
                        exchange_id=exchange.id,
                        direction="request",
                        name=h.name,
                        value=h.value,
                        value_hash=_sha256(h.value),
                    )
                )
                counts["headers"] += 1
            if ex.response:
                for h in ex.response.headers:
                    self._session.add(
                        HttpHeader(
                            exchange_id=exchange.id,
                            direction="response",
                            name=h.name,
                            value=h.value,
                            value_hash=_sha256(h.value),
                        )
                    )
                    counts["headers"] += 1

            # cookies
            for c in ex.request.cookies:
                self._session.add(
                    HttpCookie(
                        exchange_id=exchange.id,
                        direction="request",
                        name=c.name,
                        value=c.value,
                        value_hash=_sha256(c.value),
                    )
                )
                counts["cookies"] += 1
            if ex.response:
                for c in ex.response.cookies:
                    self._session.add(
                        HttpCookie(
                            exchange_id=exchange.id,
                            direction="response",
                            name=c.name,
                            value=c.value,
                            value_hash=_sha256(c.value),
                            attributes=c.attributes,
                        )
                    )
                    counts["cookies"] += 1

            # bodies (JSON y texto)
            if ex.request.body and (ex.request.body.data or ex.request.body.text):
                self._session.add(
                    BodyJson(
                        exchange_id=exchange.id,
                        direction="request",
                        content_type=ex.request.body.content_type,
                        json=ex.request.body.data,
                        json_sha256=(
                            _sha256(__import__("json").dumps(ex.request.body.data, sort_keys=True))
                            if ex.request.body.data
                            else None
                        ),
                        stored_bytes=ex.request.body.size,
                    )
                )
                counts["bodies"] += 1
            if (
                ex.response
                and ex.response.body
                and (ex.response.body.data or ex.response.body.text)
            ):
                self._session.add(
                    BodyJson(
                        exchange_id=exchange.id,
                        direction="response",
                        content_type=ex.response.body.content_type,
                        json=ex.response.body.data,
                        json_sha256=(
                            _sha256(__import__("json").dumps(ex.response.body.data, sort_keys=True))
                            if ex.response.body.data
                            else None
                        ),
                        stored_bytes=ex.response.body.size,
                    )
                )
                counts["bodies"] += 1

        # commit por lote completo
        self._session.commit()
        return counts

    # ── Templates y valores de endpoint (V0.1-09) ──────────────────────────
    def persist_templates(
        self,
        import_id: uuid.UUID,
        exchanges: Sequence[RawExchange],
        *,
        normalizer_config: NormalizeConfig | None = None,
    ) -> tuple[dict[str, int], dict[tuple[str, str, str], uuid.UUID]]:
        """Crea endpoint_templates + endpoint_values. Devuelve (totals, template_map)."""
        from akg.pipeline.normalizer import (
            NormalizeConfig,
            _placeholder_positions,
            _template_segments,
            _values_at,
            build_restricted_template,
        )

        config = normalizer_config or NormalizeConfig()
        counts = {"templates": 0, "values": 0}
        template_map: dict[tuple[str, str, str], uuid.UUID] = {}
        grouped: dict[tuple[str, str, str], list[RawExchange]] = {}
        for ex in exchanges:
            key = (ex.method.upper(), ex.template or "", ex.host)
            grouped.setdefault(key, []).append(ex)

        for (method, pattern, host), members in grouped.items():
            path_freq: dict[str, int] = {}
            for ex in members:
                path_freq[ex.path] = path_freq.get(ex.path, 0) + 1
            restricted = build_restricted_template(
                path_freq,
                pattern,
                cardinality_threshold=config.cardinality_threshold,
                protected_segments=config.protected_segments,
            )
            segments = _template_segments(pattern)
            cardinality = {
                p: {"distinct": len(_values_at(path_freq, i))}
                for i, p in _placeholder_positions(pattern)
            }
            tpl = (
                self._session.query(EndpointTemplate)
                .filter_by(import_id=import_id, method=method, pattern=pattern, host_pattern=host)
                .first()
            )
            if tpl is None:
                tpl = EndpointTemplate(
                    import_id=import_id,
                    method=method,
                    pattern=pattern,
                    host_pattern=host,
                    segments=segments or None,
                    cardinality=cardinality or None,
                    restricted=restricted if restricted != pattern else None,
                    confidence="EVIDENCIA",
                )
                self._session.add(tpl)
                self._session.flush()
                counts["templates"] += 1
            template_map[(method, pattern, host)] = tpl.id

            for ex in members:
                for param, value in (ex.path_params or {}).items():
                    vh = _sha256(value)
                    existing = (
                        self._session.query(EndpointValue)
                        .filter_by(template_id=tpl.id, param=param, value_hash=vh)
                        .first()
                    )
                    if existing:
                        existing.last_seen = ex.timestamp
                        existing.count += 1
                    else:
                        self._session.add(
                            EndpointValue(
                                template_id=tpl.id,
                                param=param,
                                value=value,
                                value_hash=vh,
                                first_seen=ex.timestamp,
                                last_seen=ex.timestamp,
                                count=1,
                            )
                        )
                    counts["values"] += 1

        self._session.commit()
        return counts, template_map

    # ── Ocurrencias de entidades (V0.1-16) ──────────────────────────────────
    def persist_occurrences(
        self, occurrences: Sequence[tuple[uuid.UUID, object]]
    ) -> dict[str, int]:
        """Persiste entity_occurrences. Devuelve totals."""
        count = 0
        for exchange_id, occ in occurrences:
            self._session.add(
                EntityOccurrence(
                    exchange_id=exchange_id,
                    import_id=occ.import_id,
                    entity_type=occ.entity_type,
                    entity_label=occ.entity_label,
                    value=occ.value,
                    value_hash=occ.value_hash,
                    path=occ.path,
                    location=occ.location,
                    sensitive=occ.sensitive,
                    redacted=occ.redacted,
                    first_seen=occ.timestamp,
                    last_seen=occ.timestamp,
                )
            )
            count += 1
        self._session.commit()
        return {"occurrences": count}

    # ── Consultas para la API (V0.1-32) ─────────────────────────────────────
    def list_endpoint_templates(self, import_id: uuid.UUID) -> list[EndpointTemplate]:
        return list(
            self._session.query(EndpointTemplate)
            .filter(EndpointTemplate.import_id == import_id)
            .order_by(EndpointTemplate.method, EndpointTemplate.pattern)
            .all()
        )

    def get_endpoint_values(self, template_id: uuid.UUID) -> list[EndpointValue]:
        return list(
            self._session.query(EndpointValue)
            .filter(EndpointValue.template_id == template_id)
            .order_by(EndpointValue.count.desc())
            .all()
        )

    def list_entities(
        self, import_id: uuid.UUID, entity_type: str | None = None, limit: int = 200
    ) -> list[EntityOccurrence]:
        q = self._session.query(EntityOccurrence).filter(EntityOccurrence.import_id == import_id)
        if entity_type:
            q = q.filter(EntityOccurrence.entity_type == entity_type)
        return list(q.order_by(EntityOccurrence.last_seen.desc()).limit(limit).all())

    def get_exchange(
        self, exchange_id: uuid.UUID
    ) -> tuple[HttpExchange, list[HttpHeader], list[HttpCookie], list[BodyJson], list[EntityOccurrence]]:
        exchange = self._session.get(HttpExchange, exchange_id)
        if exchange is None:
            raise KeyError(f"exchange {exchange_id} no existe")
        headers = (
            self._session.query(HttpHeader).filter(HttpHeader.exchange_id == exchange_id).all()
        )
        cookies = (
            self._session.query(HttpCookie).filter(HttpCookie.exchange_id == exchange_id).all()
        )
        bodies = self._session.query(BodyJson).filter(BodyJson.exchange_id == exchange_id).all()
        occs = (
            self._session.query(EntityOccurrence)
            .filter(EntityOccurrence.exchange_id == exchange_id)
            .all()
        )
        return exchange, headers, cookies, bodies, occs

    # ── Motor de reglas: runs + alertas (SAD cap. 8) ─────────────────────
    def create_rule_run(
        self, import_id: uuid.UUID, rules_checked: int = 0
    ) -> RuleRun:
        run = RuleRun(
            import_id=import_id,
            started_at=datetime.now(UTC),
            rules_checked=rules_checked,
            status="RUNNING",
        )
        self._session.add(run)
        self._session.commit()
        return run

    def finish_rule_run(self, run_id: uuid.UUID, alerts_created: int, status: str) -> None:
        run = self._session.get(RuleRun, run_id)
        if run is None:
            raise KeyError(f"rule run {run_id} no existe")
        run.alerts_created = alerts_created
        run.status = status
        run.finished_at = datetime.now(UTC)
        self._session.commit()

    def create_alert(
        self,
        *,
        import_id: uuid.UUID,
        rule_id: str,
        rule_run_id: uuid.UUID,
        severity: str,
        title: str,
        description: str | None,
        evidence: dict,
        confidence: float,
        context_subgraph: dict | None = None,
    ) -> Alert:
        alert = Alert(
            import_id=import_id,
            rule_id=rule_id,
            rule_run_id=rule_run_id,
            severity=severity,
            title=title,
            description=description,
            evidence=evidence,
            confidence=confidence,
            context_subgraph=context_subgraph,
            status="OPEN",
        )
        self._session.add(alert)
        self._session.commit()
        return alert

    def list_alerts(
        self,
        import_id: uuid.UUID | None = None,
        *,
        severity: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[Alert]:
        q = self._session.query(Alert)
        if import_id is not None:
            q = q.filter(Alert.import_id == import_id)
        if severity:
            q = q.filter(Alert.severity == severity)
        if status:
            q = q.filter(Alert.status == status)
        return list(
            q.order_by(Alert.severity.desc(), Alert.created_at.desc()).limit(limit).all()
        )

    def get_alert(self, alert_id: uuid.UUID) -> Alert:
        alert = self._session.get(Alert, alert_id)
        if alert is None:
            raise KeyError(f"alert {alert_id} no existe")
        return alert

    def update_alert_status(self, alert_id: uuid.UUID, status: str) -> Alert:
        alert = self._session.get(Alert, alert_id)
        if alert is None:
            raise KeyError(f"alert {alert_id} no existe")
        alert.status = status
        self._session.commit()
        return alert

    def resolve_exchange_ids(
        self, pattern: str, method: str, host: str | None = None, limit: int = 20
    ) -> list[str]:
        """Resuelve exchange_ids reales que llaman a un Endpoint por template."""
        q = (
            self._session.query(HttpExchange.id)
            .join(EndpointTemplate, EndpointTemplate.id == HttpExchange.template_id)
            .filter(EndpointTemplate.method == method, EndpointTemplate.pattern == pattern)
        )
        if host:
            q = q.filter(HttpExchange.host == host)
        return [str(r[0]) for r in q.limit(limit).all()]
