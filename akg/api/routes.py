"""Router principal: workspaces, imports y ejecucion del pipeline (SAD cap. 9.4)."""

from __future__ import annotations

import json
import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from akg.api.deps import get_db
from akg.api.schemas import (
    AlertDetailOut,
    AlertList,
    AlertOut,
    AlertStatusUpdate,
    BodyOut,
    CookieOut,
    EndpointTemplateList,
    EndpointTemplateOut,
    EndpointValueOut,
    EntityList,
    ExchangeDetailOut,
    ExchangeOut,
    HeaderOut,
    ImportDetailOut,
    ImportList,
    ImportOut,
    OccurrenceOut,
    PipelineResult,
    RuleRunOut,
    WorkspaceCreate,
    WorkspaceList,
    WorkspaceOut,
)
from akg.evidence.repository import EvidenceRepository
from akg.pipeline.orchestrator import run_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


# ── Workspaces ─────────────────────────────────────────────────────────────────


@router.get("/workspaces", response_model=WorkspaceList, summary="Lista de workspaces")
def list_workspaces(repo: EvidenceRepository = Depends(get_db)) -> WorkspaceList:
    items = repo.list_workspaces()
    return WorkspaceList(items=[WorkspaceOut.model_validate(i) for i in items], total=len(items))


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201, summary="Crear workspace")
def create_workspace(
    payload: WorkspaceCreate, repo: EvidenceRepository = Depends(get_db)
) -> WorkspaceOut:
    ws = repo.create_workspace(payload.name, payload.description)
    return WorkspaceOut.model_validate(ws)


@router.get(
    "/workspaces/{workspace_id}", response_model=WorkspaceOut, summary="Detalle de workspace"
)
def get_workspace(
    workspace_id: uuid.UUID, repo: EvidenceRepository = Depends(get_db)
) -> WorkspaceOut:
    ws = repo.get_workspace(workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="workspace no encontrado")
    return WorkspaceOut.model_validate(ws)


# ── Imports ─────────────────────────────────────────────────────────────────────


@router.post(
    "/imports",
    response_model=PipelineResult,
    status_code=202,
    summary="Subir archivo y disparar el pipeline",
)
async def create_import(
    file: UploadFile,
    workspace_id: uuid.UUID,
    source_format: str = "burp_json",
    repo: EvidenceRepository = Depends(get_db),
) -> PipelineResult:
    if repo.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace no encontrado")

    suffix = Path(file.filename or "upload").suffix or ""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(await file.read())
        tmp.flush()
        result = await run_in_threadpool(
            run_pipeline,
            Path(tmp.name),
            workspace_id=workspace_id,
            source_format=source_format,
            source_hash=f"sha256:upload:{file.filename or 'unknown'}",
            repo=repo,
            project=str(workspace_id),
        )

    if result["status"] == "FAILED":
        raise HTTPException(status_code=422, detail=result.get("error", "pipeline fallido"))
    return PipelineResult(**result)


@router.get("/imports", response_model=ImportList, summary="Lista de importaciones")
def list_imports(
    workspace_id: uuid.UUID | None = None,
    repo: EvidenceRepository = Depends(get_db),
) -> ImportList:
    from akg.models import Import

    stmt = repo.session.query(Import).order_by(Import.created_at.desc())
    if workspace_id is not None:
        stmt = stmt.filter(Import.workspace_id == workspace_id)
    items = stmt.all()
    out = [ImportOut.model_validate(i) for i in items]
    return ImportList(items=out, total=len(out))


@router.get("/imports/{import_id}", response_model=ImportDetailOut, summary="Detalle de import")
def get_import(import_id: uuid.UUID, repo: EvidenceRepository = Depends(get_db)) -> ImportDetailOut:
    from akg.models import Import, ImportStage

    imp = repo.session.get(Import, import_id)
    if imp is None:
        raise HTTPException(status_code=404, detail="import no encontrado")

    stages = repo.session.query(ImportStage).filter(ImportStage.import_id == import_id).all()
    detail = ImportOut.model_validate(imp).model_dump()
    detail["stages"] = [
        {"stage": s.stage, "status": s.status, "processed": s.processed} for s in stages
    ]
    return ImportDetailOut(**detail)


@router.get("/imports/{import_id}/stages", summary="Progreso por etapa")
def get_import_stages(
    import_id: uuid.UUID, repo: EvidenceRepository = Depends(get_db)
) -> list[dict]:
    from akg.models import Import, ImportStage

    if repo.session.get(Import, import_id) is None:
        raise HTTPException(status_code=404, detail="import no encontrado")
    stages = repo.session.query(ImportStage).filter(ImportStage.import_id == import_id).all()
    return [{"stage": s.stage, "status": s.status, "processed": s.processed} for s in stages]


# ── Endpoints (plantillas), entidades y exchanges (V0.1-32) ────────────────────


@router.get(
    "/imports/{import_id}/endpoints",
    response_model=EndpointTemplateList,
    summary="Plantillas de endpoints de un import",
)
def list_endpoints(
    import_id: uuid.UUID, repo: EvidenceRepository = Depends(get_db)
) -> EndpointTemplateList:
    _ensure_import(repo, import_id)
    templates = repo.list_endpoint_templates(import_id)
    items: list[EndpointTemplateOut] = []
    for tpl in templates:
        values = [
            EndpointValueOut.model_validate(v)
            for v in repo.get_endpoint_values(tpl.id)
        ]
        items.append(
            EndpointTemplateOut(
                id=tpl.id,
                method=tpl.method,
                pattern=tpl.pattern,
                host_pattern=tpl.host_pattern,
                confidence=tpl.confidence,
                values=values,
            )
        )
    return EndpointTemplateList(items=items, total=len(items))


@router.get(
    "/imports/{import_id}/entities",
    response_model=EntityList,
    summary="Ocurrencias de entidades de un import",
)
def list_entities(
    import_id: uuid.UUID,
    entity_type: str | None = None,
    limit: int = 200,
    repo: EvidenceRepository = Depends(get_db),
) -> EntityList:
    _ensure_import(repo, import_id)
    occs = repo.list_entities(import_id, entity_type=entity_type, limit=limit)
    items = [
        OccurrenceOut(
            entity_type=o.entity_type,
            entity_label=o.entity_label,
            value_hash=o.value_hash,
            path=o.path,
            location=o.location,
            sensitive=o.sensitive,
        )
        for o in occs
    ]
    return EntityList(items=items, total=len(items))


def _build_raw_request(
    exchange: object,
    headers: list,
    cookies: list,
    bodies: list,
) -> str:
    """Reconstruye el request HTTP original a partir de las partes persistidas."""
    req_headers = [h for h in headers if h.direction == "request"]
    req_cookies = [c for c in cookies if c.direction == "request"]
    req_body = next((b for b in bodies if b.direction == "request"), None)

    target = exchange.path
    if exchange.query_string:
        target += "?" + exchange.query_string

    lines = [f"{exchange.method} {target} HTTP/1.1"]
    lines.append(f"Host: {exchange.host}")
    for h in req_headers:
        lines.append(f"{h.name}: {h.value or ''}")
    if req_cookies:
        joined = "; ".join(f"{c.name}={c.value or ''}" for c in req_cookies)
        lines.append(f"Cookie: {joined}")
    lines.append("")

    body_text = ""
    if req_body is not None and req_body.json is not None:
        body_text = json.dumps(req_body.json, ensure_ascii=False, indent=2)
        if req_body.content_type and not any(h.name.lower() == "content-type" for h in req_headers):
            lines.insert(-1, f"Content-Type: {req_body.content_type}")
        if not any(h.name.lower() == "content-length" for h in req_headers):
            lines.insert(-1, f"Content-Length: {len(body_text)}")
        if req_body.truncated:
            body_text += "\n# [cuerpo truncado]"
    return "\r\n".join(lines) + (("\r\n\r\n" + body_text) if body_text else "")


def _exchange_detail_out(repo: EvidenceRepository, exchange_id: uuid.UUID) -> ExchangeDetailOut:
    try:
        exchange, headers, cookies, bodies, occs = repo.get_exchange(exchange_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="exchange no encontrado") from None
    return ExchangeDetailOut(
        **ExchangeOut.model_validate(exchange).model_dump(),
        headers=[HeaderOut(direction=h.direction, name=h.name, value=h.value) for h in headers],
        cookies=[CookieOut(direction=c.direction, name=c.name, value=c.value, attributes=c.attributes) for c in cookies],
        bodies=[BodyOut(direction=b.direction, content_type=b.content_type, body=b.json) for b in bodies],
        occurrences=[
            OccurrenceOut(
                entity_type=o.entity_type,
                entity_label=o.entity_label,
                value_hash=o.value_hash,
                path=o.path,
                location=o.location,
                sensitive=o.sensitive,
            )
            for o in occs
        ],
        raw_request=_build_raw_request(exchange, headers, cookies, bodies),
    )


@router.get(
    "/exchanges/{exchange_id}",
    response_model=ExchangeDetailOut,
    summary="Detalle de un exchange (headers, cookies, bodies, ocurrencias)",
)
def get_exchange(
    exchange_id: uuid.UUID, repo: EvidenceRepository = Depends(get_db)
) -> ExchangeDetailOut:
    return _exchange_detail_out(repo, exchange_id)


@router.get(
    "/imports/{import_id}/sample-request",
    response_model=ExchangeDetailOut,
    summary="Request original de ejemplo de un endpoint (primer exchange del template)",
)
def sample_request(
    import_id: uuid.UUID,
    method: str,
    pattern: str,
    host: str | None = None,
    repo: EvidenceRepository = Depends(get_db),
) -> ExchangeDetailOut:
    _ensure_import(repo, import_id)
    ids = repo.resolve_exchange_ids(pattern, method, host, limit=1)
    if not ids:
        raise HTTPException(status_code=404, detail="sin exchanges de ejemplo para ese endpoint")
    return _exchange_detail_out(repo, uuid.UUID(ids[0]))


def _ensure_import(repo: EvidenceRepository, import_id: uuid.UUID) -> None:
    from akg.models import Import

    if repo.session.get(Import, import_id) is None:
        raise HTTPException(status_code=404, detail="import no encontrado")


# ── Motor de reglas y alertas (SAD cap. 8) ────────────────────────────────
@router.post(
    "/imports/{import_id}/rules/run",
    response_model=RuleRunOut,
    status_code=201,
    summary="Ejecuta el catalogo de reglas sobre un import",
)
def run_rules_on_import(
    import_id: uuid.UUID, repo: EvidenceRepository = Depends(get_db)
) -> RuleRunOut:
    _ensure_import(repo, import_id)
    from akg.rules import get_rules, run_rules
    from engine.graph.repository import graph_repo

    rules = get_rules(enabled_only=True)
    run = repo.create_rule_run(import_id, rules_checked=len(rules))
    try:
        candidates = run_rules(rules, import_id, graph_repo)
    except Exception as exc:  # pragma: no cover - defensivo
        repo.finish_rule_run(run.id, 0, "FAILED")
        raise HTTPException(
            status_code=422, detail=f"ejecucion de reglas fallida: {exc}"
        ) from exc
    for c in candidates:
        repo.create_alert(
            import_id=import_id,
            rule_id=c.rule.rule_id,
            rule_run_id=run.id,
            severity=c.rule.severity,
            title=c.title,
            description=c.rule.description,
            evidence=c.evidence,
            confidence=c.confidence,
        )
    repo.finish_rule_run(run.id, len(candidates), "COMPLETED")
    return RuleRunOut.model_validate(run)


@router.get("/imports/{import_id}/alerts", response_model=AlertList, summary="Alertas de un import")
def list_import_alerts(
    import_id: uuid.UUID,
    severity: str | None = None,
    status: str | None = None,
    repo: EvidenceRepository = Depends(get_db),
) -> AlertList:
    _ensure_import(repo, import_id)
    items = repo.list_alerts(import_id, severity=severity, status=status)
    return AlertList(items=[AlertOut.model_validate(a) for a in items], total=len(items))


@router.get(
    "/alerts/{alert_id}",
    response_model=AlertDetailOut,
    summary="Detalle de alerta con evidencia trazable",
)
def get_alert(alert_id: uuid.UUID, repo: EvidenceRepository = Depends(get_db)) -> AlertDetailOut:
    try:
        alert = repo.get_alert(alert_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="alerta no encontrada") from None
    out = AlertDetailOut.model_validate(alert)
    evidence = alert.evidence or {}
    fields = evidence.get("fields") or {}
    pattern = fields.get("pattern")
    method = fields.get("method")
    out.host = fields.get("host")
    if pattern and method:
        out.exchange_ids = repo.resolve_exchange_ids(pattern, method, fields.get("host"))[:20]
        out.node_keys = [
            f"Endpoint:{method}:{pattern}",
            *([f"Host:{fields.get('host')}"] if fields.get("host") else []),
        ]
    if not out.host and out.exchange_ids:
        try:
            exchange, *_ = repo.get_exchange(uuid.UUID(out.exchange_ids[0]))
            out.host = exchange.host
        except (KeyError, ValueError):  # pragma: no cover - defensivo
            pass
    return out


@router.patch(
    "/alerts/{alert_id}",
    response_model=AlertOut,
    summary="Actualiza el estado de una alerta (triage)",
)
def update_alert_status(
    alert_id: uuid.UUID, body: AlertStatusUpdate, repo: EvidenceRepository = Depends(get_db)
) -> AlertOut:
    try:
        alert = repo.update_alert_status(alert_id, body.status)
    except KeyError:
        raise HTTPException(status_code=404, detail="alerta no encontrada") from None
    return AlertOut.model_validate(alert)
