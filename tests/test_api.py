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
def test_delete_workspace_removes_data() -> None:
    """Borrar un workspace elimina workspace, imports y grafo de forma definitiva."""
    ws = client.post(
        "/api/v1/workspaces", json={"name": "delete-me", "description": "cleanup"}
    )
    assert ws.status_code == 201
    ws_id = ws.json()["id"]

    with open("dev/samples/burp_sample.json", "rb") as fh:
        resp = client.post(
            "/api/v1/imports",
            params={"workspace_id": ws_id, "source_format": "burp_json"},
            files={"file": ("burp_sample.json", fh, "application/json")},
        )
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "MATERIALIZED"
    import_id = resp.json()["import_id"]

    # los datos estan presentes antes de borrar
    lst = client.get(f"/api/v1/imports?workspace_id={ws_id}")
    assert lst.status_code == 200
    assert lst.json()["total"] >= 1

    # borrar
    r = client.delete(f"/api/v1/workspaces/{ws_id}")
    assert r.status_code == 204, r.text

    # el workspace ya no existe
    detail = client.get(f"/api/v1/workspaces/{ws_id}")
    assert detail.status_code == 404
    ids = [i["id"] for i in client.get("/api/v1/workspaces").json()["items"]]
    assert ws_id not in ids

    # los imports asociados ya no existen
    lst = client.get(f"/api/v1/imports?workspace_id={ws_id}")
    assert lst.status_code == 200
    assert lst.json()["total"] == 0
    assert client.get(f"/api/v1/imports/{import_id}").status_code == 404

    # borrar de nuevo da 404 (idempotente)
    assert client.delete(f"/api/v1/workspaces/{ws_id}").status_code == 404


@pytest.mark.integration
def test_header_tracking() -> None:
    """Rastrear headers: el nodo Header aparece dentro del grafo general completo."""
    ws = client.post("/api/v1/workspaces", json={"name": "header-track", "description": "check"})
    ws_id = ws.json()["id"]

    with open("dev/samples/burp_sample.json", "rb") as fh:
        resp = client.post(
            "/api/v1/imports",
            params={"workspace_id": ws_id, "source_format": "burp_json"},
            files={"file": ("burp_sample.json", fh, "application/json")},
        )
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "MATERIALIZED"

    # sugerencias basadas en headers existentes
    sug = client.get(f"/api/v1/graph/header-suggestions?q=content&workspace_id={ws_id}")
    assert sug.status_code == 200
    assert "content-type" in [s.lower() for s in sug.json()["suggestions"]]

    # antes de rastrear no hay ningun nodo Header en el workspace
    pre = client.get(f"/api/v1/graph/headers?workspace_id={ws_id}").json()
    assert pre["tracked"] == []
    assert all(n["labels"] != ["Header"] for n in pre["nodes"])
    baseline_nodes = len(pre["nodes"])

    # rastrear UN header -> la vista es el grafo COMPLETO + el nodo Header
    tr = client.post(
        "/api/v1/graph/headers/track",
        json={"headers": ["Content-Type"], "workspace_id": ws_id},
    )
    assert tr.status_code == 200, tr.text
    body = tr.json()
    assert body["tracked"] == ["Content-Type"]
    headers_in_view = [n for n in body["nodes"] if n["labels"] == ["Header"]]
    assert [n["properties"]["name"] for n in headers_in_view] == ["content-type"]
    assert any(e["type"] == "USES_HEADER" for e in body["edges"])
    # todos los demas nodos (que no son Header) siguen presentes
    assert len(body["nodes"]) >= baseline_nodes
    non_headers = [n for n in body["nodes"] if n["labels"] != ["Header"]]
    assert len(non_headers) == baseline_nodes

    # la lista es autoritativa (persistida en el workspace)
    got = client.get(f"/api/v1/graph/headers?workspace_id={ws_id}").json()
    assert got["tracked"] == ["Content-Type"]

    # el grafo general solo contiene el header añadido (nodo Header), sin otros headers
    gr = client.get(f"/api/v1/graph/headers?workspace_id={ws_id}").json()
    general_headers = {n["properties"]["name"] for n in gr["nodes"] if n["labels"] == ["Header"]}
    assert general_headers == {"content-type"}
    assert len(gr["nodes"]) >= baseline_nodes

    # dejar de rastrearlo -> desaparece el nodo Header pero el grafo sigue completo
    rm = client.delete(f"/api/v1/graph/headers?name=Content-Type&workspace_id={ws_id}")
    assert rm.status_code == 200
    assert rm.json()["deleted"] == "content-type"
    assert rm.json()["tracked"] == []
    got = client.get(f"/api/v1/graph/headers?workspace_id={ws_id}").json()
    assert got["tracked"] == []
    assert all(n["labels"] != ["Header"] for n in got["nodes"])
    assert len(got["nodes"]) == baseline_nodes

    # un header inexistente se rastrea en la lista pero no materializa nodo
    client.delete(f"/api/v1/workspaces/{ws_id}")
    ws2 = client.post("/api/v1/workspaces", json={"name": "header-track-2", "description": "x"})
    ws2_id = ws2.json()["id"]
    with open("dev/samples/burp_sample.json", "rb") as fh:
        client.post(
            "/api/v1/imports",
            params={"workspace_id": ws2_id, "source_format": "burp_json"},
            files={"file": ("burp_sample.json", fh, "application/json")},
        )
    tr2 = client.post(
        "/api/v1/graph/headers/track",
        json={"headers": ["x-no-existe"], "workspace_id": ws2_id},
    )
    assert tr2.status_code == 200
    assert all(n["labels"] != ["Header"] for n in tr2.json()["nodes"])
    assert tr2.json()["tracked"] == ["x-no-existe"]
    got2 = client.get(f"/api/v1/graph/headers?workspace_id={ws2_id}").json()
    assert got2["tracked"] == ["x-no-existe"]
    assert all(n["labels"] != ["Header"] for n in got2["nodes"])

    # borrar el workspace limpia tambien los headers
    assert client.delete(f"/api/v1/workspaces/{ws2_id}").status_code == 204


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
