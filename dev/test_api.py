"""Test de la API REST v1 con TestClient (curl-free smoke)."""

from fastapi.testclient import TestClient

from akg.api.main import app
from akg.evidence.repository import EvidenceRepository

client = TestClient(app)


def main() -> None:
    # creamos un workspace
    r = client.post("/api/v1/workspaces", json={"name": "api-smoke", "description": "test api"})
    print("create ws:", r.status_code, r.json()["id"])
    ws_id = r.json()["id"]

    # listar workspaces
    r = client.get("/api/v1/workspaces")
    print("list ws:", r.status_code, r.json()["total"])

    # subir archivo y ejecutar pipeline
    with open("dev/samples/burp_sample.json", "rb") as fh:
        r = client.post(
            "/api/v1/imports",
            params={"workspace_id": ws_id, "source_format": "burp_json"},
            files={"file": ("burp_sample.json", fh, "application/json")},
        )
    print("pipeline:", r.status_code, r.json().get("status"))
    imp_id = r.json().get("import_id")

    # detalle de import + stages
    r = client.get(f"/api/v1/imports/{imp_id}")
    print("import detail:", r.status_code, r.json().get("stages"))

    # stages endpoint
    r = client.get(f"/api/v1/imports/{imp_id}/stages")
    print("stages:", r.status_code, r.json())

    # graph summary
    r = client.get("/api/v1/graph/summary")
    print("graph summary:", r.status_code, r.json()["node_counts"])

    # graph query
    r = client.post("/api/v1/graph/query", json={"cypher": "MATCH (x:Exchange) RETURN x.method AS m LIMIT 5"})
    print("graph query:", r.status_code, r.json())

    # consulta bloqueada (debe fallar 422)
    r = client.post("/api/v1/graph/query", json={"cypher": "MATCH (n) DETACH DELETE n"})
    print("blocked query:", r.status_code)


if __name__ == "__main__":
    main()