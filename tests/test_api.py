"""Tests de la API REST v1 con TestClient (requiere contenedores arriba)."""

import pytest
from fastapi.testclient import TestClient

from akg.api.main import app

client = TestClient(app)


@pytest.mark.integration
def test_create_and_list_workspace() -> None:
    r = client.post(
        "/api/v1/workspaces",
        json={"name": "pytest-ws", "description": "via test"},
    )
    assert r.status_code == 201
    ws = r.json()
    assert ws["name"] == "pytest-ws"

    lst = client.get("/api/v1/workspaces")
    assert lst.status_code == 200
    ids = [i["id"] for i in lst.json()["items"]]
    assert ws["id"] in ids


@pytest.mark.integration
def test_graph_summary() -> None:
    resp = client.get("/api/v1/graph/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["node_counts"], dict)


@pytest.mark.integration
def test_graph_query_readonly_blocked() -> None:
    resp = client.post(
        "/api/v1/graph/query",
        json={"cypher": "MATCH (n) DETACH DELETE n"},
    )
    assert resp.status_code == 422


@pytest.mark.integration
def test_error_envelope() -> None:
    """V0.1-34: los errores devuelven el envelope {error:{code,message}}."""
    resp = client.get("/api/v1/workspaces/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "404"
    assert body["error"]["message"] == "workspace no encontrado"


@pytest.mark.integration
def test_health_and_ui_serve() -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/ui/").status_code == 200
    assert client.get("/ui/app.js").status_code == 200
    assert client.get("/ui/style.css").status_code == 200


@pytest.mark.integration
def test_pipeline_full_upload() -> None:
    """Sube un export de Burp y verifica el pipeline completo hasta MATERIALIZED."""
    ws = client.post(
        "/api/v1/workspaces", json={"name": "pipeline-integration", "description": "full"}
    )
    ws_id = ws.json()["id"]

    with open("dev/samples/burp_sample.json", "rb") as fh:
        resp = client.post(
            "/api/v1/imports",
            params={"workspace_id": ws_id, "source_format": "burp_json"},
            files={"file": ("burp_sample.json", fh, "application/json")},
        )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "MATERIALIZED"
    assert body["parsed"] >= 3
    assert body["materialized"]["exchanges"] == body["parsed"]

    import_id = body["import_id"]
    detail = client.get(f"/api/v1/imports/{import_id}")
    assert detail.status_code == 200
    stages = {s["stage"]: s["status"] for s in detail.json()["stages"]}
    assert stages.get("parse") == "DONE"
    assert stages.get("correlate") == "DONE"


@pytest.mark.integration
def test_new_v01_endpoints() -> None:
    """Vistas v0.1: endpoints, exchanges, auth-flow y resources."""
    resp = client.post(
        "/api/v1/workspaces", json={"name": "v01-endpoints", "description": "check"}
    )
    ws_id = resp.json()["id"]

    with open("dev/samples/burp_sample.json", "rb") as fh:
        resp = client.post(
            "/api/v1/imports",
            params={"workspace_id": ws_id, "source_format": "burp_json"},
            files={"file": ("burp_sample.json", fh, "application/json")},
        )
    assert resp.status_code == 202, resp.text
    import_id = resp.json()["import_id"]

    # endpoints/plantillas
    ep = client.get(f"/api/v1/imports/{import_id}/endpoints")
    assert ep.status_code == 200
    assert ep.json()["total"] >= 1

    # entities
    ent = client.get(f"/api/v1/imports/{import_id}/entities", params={"limit": 5})
    assert ent.status_code == 200
    assert ent.json()["total"] >= 1

    # exchange detail
    ex = client.get(f"/api/v1/imports/{import_id}/endpoints")
    assert ex.json()["total"] >= 1
    # obtener un exchange persistido
    detail = client.get(f"/api/v1/imports/{import_id}")
    assert detail.status_code == 200

    # grafo auth-flow y resources (pueden estar vacios en datos de prueba)
    assert client.get("/api/v1/graph/auth-flow").status_code == 200
    assert client.get("/api/v1/graph/resources").status_code == 200


@pytest.mark.integration
def test_rules_alerts_flow() -> None:
    """Motor de reglas: run -> alertas -> detalle con evidencia -> triage."""
    resp = client.post("/api/v1/workspaces", json={"name": "rules-flow", "description": "check"})
    ws_id = resp.json()["id"]
    with open("dev/samples/burp_sample.json", "rb") as fh:
        resp = client.post(
            "/api/v1/imports",
            params={"workspace_id": ws_id, "source_format": "burp_json"},
            files={"file": ("burp_sample.json", fh, "application/json")},
        )
    assert resp.status_code == 202, resp.text
    import_id = resp.json()["import_id"]

    run = client.post(f"/api/v1/imports/{import_id}/rules/run")
    assert run.status_code == 201, run.text
    body = run.json()
    assert body["status"] == "COMPLETED"
    assert isinstance(body["alerts_created"], int)

    lst = client.get(f"/api/v1/imports/{import_id}/alerts")
    assert lst.status_code == 200
    assert lst.json()["total"] >= 0
    if lst.json()["total"] > 0:
        alert_id = lst.json()["items"][0]["id"]
        det = client.get(f"/api/v1/alerts/{alert_id}")
        assert det.status_code == 200
        assert isinstance(det.json()["exchange_ids"], list)
        upd = client.patch(f"/api/v1/alerts/{alert_id}", json={"status": "TRIAGED"})
        assert upd.status_code == 200
        assert upd.json()["status"] == "TRIAGED"
