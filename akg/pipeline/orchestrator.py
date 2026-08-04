"""Orquestador del pipeline ETL (etapas 1-4).

Encadena el flujo completo de una importacion:

    1. Parseo (adaptador)      -> RawExchange[]
    2. Normalizacion           -> NormalizedExchange[]
    3. Correlacion + materialz -> grafo Neo4j (con materializacion de vertices)
    4. Persistencia            -> PostgreSQL (evidencia)

Registra el progreso de cada etapa en `import_stages` y actualiza el estado
global del import. Es idempotente a nivel de etapa: `upsert_stage` usa
nueve/expects con clave (import_id, stage, shard).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from akg.evidence.repository import EvidenceRepository
from akg.pipeline.correlator import correlate_exchanges
from akg.pipeline.extractor import extract_from_exchanges
from akg.pipeline.importers import get_adapter
from akg.pipeline.normalizer import NormalizeConfig, normalize
from engine.graph.materialize import materialize_exchanges

PIPELINE_VERSION = "0.1.0"


def run_pipeline(
    source_file: Path,
    *,
    workspace_id: uuid.UUID,
    source_format: str = "burp_json",
    source_hash: str = "",
    repo: EvidenceRepository | None = None,
    project: str = "default",
    normalizer_config: NormalizeConfig | None = None,
) -> dict[str, Any]:
    """Ejecuta el pipeline completo para un archivo fuente.

    Devuelve un resumen con los import_id, workspace_id y los totales de cada
    etapa. Requiere un workspace existente.
    """
    repo = repo or EvidenceRepository()
    try:
        import_id: uuid.UUID | None = None
        result: dict[str, Any] = {}

        # ── 0) registrar import ──────────────────────────────────────────
        imp = repo.create_import(
            workspace_id=workspace_id,
            source_format=source_format,
            source_file_name=source_file.name,
            source_hash=source_hash or f"sha256:auto:{source_file.name}",
            pipeline_version=PIPELINE_VERSION,
        )
        import_id = imp.id
        result["import_id"] = str(import_id)
        result["workspace_id"] = str(workspace_id)
        result["pipeline_version"] = PIPELINE_VERSION

        # ── 1) parse ─────────────────────────────────────────────────────
        repo.update_import_status(import_id, "PARSING")
        adapter = get_adapter(source_format)
        with source_file.open("rb") as fh:
            raw_exchanges, parse_errors = adapter.parse(fh, import_id=str(import_id))
        repo.upsert_stage(import_id, "parse", 0, "DONE", len(raw_exchanges))
        result["parsed"] = len(raw_exchanges)
        result["parse_errors"] = len(parse_errors)

        # ── 2) normalizar ────────────────────────────────────────────────
        repo.update_import_status(import_id, "NORMALIZING")
        normalized = [normalize(r, normalizer_config) for r in raw_exchanges]
        repo.upsert_stage(import_id, "normalize", 0, "DONE", len(normalized))
        result["normalized"] = len(normalized)

        # ── 2.5) templates de endpoint + valores ─────────────────────────
        tpl_totals, template_map = repo.persist_templates(
            import_id, normalized, normalizer_config=normalizer_config
        )
        result["templates"] = tpl_totals

        # ── 2.6) extraccion de entidades ────────────────────────────────
        repo.update_import_status(import_id, "EXTRACTING")
        occurrences = extract_from_exchanges(normalized, import_id=import_id)

        # ── 3) materializar vertices base en el grafo ────────────────────
        repo.update_import_status(import_id, "MATERIALIZING")
        materialized = materialize_exchanges(
            [n.model_dump() for n in normalized],
            project=project,
            import_id=import_id,
        )
        repo.upsert_stage(import_id, "materialize", 0, "DONE", len(raw_exchanges))
        result["materialized"] = materialized

        # ── 4) correlacion (relaciones de sesion) ─────────────────────────
        repo.update_import_status(import_id, "CORRELATING")
        correlation = correlate_exchanges(
            normalized,
            project=project,
            import_id=import_id,
        )
        repo.upsert_stage(import_id, "correlate", 0, "DONE", len(normalized))
        result["correlation"] = correlation

        # ── 5) persistir evidencia + ocurrencias ──────────────────────────
        repo.update_import_status(import_id, "EXTRACTING")
        totals = repo.persist_exchanges(import_id, normalized, template_map=template_map)
        repo.persist_occurrences(occurrences)
        repo.upsert_stage(import_id, "extract", 0, "DONE", totals["exchanges"])
        result["extracted"] = {"occurrences": len(occurrences)}
        result["persisted"] = totals

        # ── 5) capitalizar status final ──────────────────────────────────
        repo.update_import_status(import_id, "MATERIALIZED", totals=totals)
        result["status"] = "MATERIALIZED"
        return result
    except Exception as exc:  # pragma: no cover - manejo defensivo
        if import_id:
            repo.update_import_status(import_id, "FAILED", totals={"error": str(exc)})
        result["status"] = "FAILED"
        result["error"] = str(exc)
        return result


__all__ = ["run_pipeline", "PIPELINE_VERSION"]
