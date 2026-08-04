"""Smoke test de integración Sprint 1-2: importar → persistir en PG → grafos Neo4j."""

from pathlib import Path

from akg.evidence.repository import EvidenceRepository
from akg.pipeline.importers import get_adapter
from engine.graph.materialize import materialize_exchanges

SAMPLE = Path("dev/samples/burp_sample.json")


def main() -> None:
    repo = EvidenceRepository()

    ws = repo.create_workspace(name="sprint1-demo", description="smoke")
    print("workspace:", ws.id, ws.name)

    imp = repo.create_import(
        workspace_id=ws.id,
        source_format="burp_json",
        source_file_name="burp_sample.json",
        source_hash="sha256:smoke",
        pipeline_version="0.1.0",
    )
    print("import:", imp.id, imp.status)

    adapter = get_adapter("burp_json")
    with SAMPLE.open("rb") as fh:
        exchanges, errors = adapter.parse(fh, import_id=str(imp.id))

    print("parsed:", len(exchanges), "errors:", len(errors))
    for err in errors:
        print("  err:", err)

    repo.upsert_stage(
        imp.id, stage="parse", shard=0, status="DONE", processed=len(exchanges)
    )

    totals = repo.persist_exchanges(imp.id, exchanges)
    print("persisted totals:", totals)

    repo.update_import_status(imp.id, "PARSED", totals=totals)

    print("SHAPES")
    for i, e in enumerate(exchanges):
        print(
            f"  [{i}] {e.method} {e.scheme}://{e.host}{e.path} "
            f"req_cookies={len(e.request.cookies)} resp={e.response.status_code} "
            f"resp_cookies={len(e.response.cookies)}"
        )

    graph_counts = materialize_exchanges(
        [e.model_dump() for e in exchanges if e.import_id],
        project=ws.name,
        import_id=imp.id,
    )
    print("materialized:", graph_counts)

    repo.close()


if __name__ == "__main__":
    main()