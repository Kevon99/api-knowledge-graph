"""Test del orquestador: pipeline completo end-to-end."""

from pathlib import Path

from akg.evidence.repository import EvidenceRepository
from akg.pipeline.orchestrator import run_pipeline

SAMPLE = Path("dev/samples/burp_sample.json")


def main() -> None:
    repo = EvidenceRepository()
    ws = repo.create_workspace(name="orchestrator-demo", description="pipeline completo")
    print("workspace:", ws.id)

    result = run_pipeline(
        SAMPLE,
        workspace_id=ws.id,
        source_format="burp_json",
        source_hash="sha256:orchestrator-test",
        repo=repo,
        project="orchestrator-demo",
    )
    print("result:", result)

    repo.close()


if __name__ == "__main__":
    main()