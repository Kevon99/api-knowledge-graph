import uuid
from akg.database import SessionLocal
from akg.models import Workspace
from akg.schemas import RawExchange
from engine.graph import graph_repo

print("1. PostgreSQL")
s = SessionLocal()
try:
    ws = Workspace(name="smoke_test")
    s.add(ws); s.flush()
    print(f"   OK Workspace: {ws.id}")
    s.delete(ws); s.commit()
    print("   OK borrado")
finally:
    s.close()

print("2. Neo4j")
graph_repo.upsert_node("Workspace", {"name": "smoke_ws"}, ["name"])
r = graph_repo.run_read("MATCH (w:Workspace {name: $n}) RETURN w.name", {"n": "smoke_ws"})
print(f"   OK nodo: {r[0]["w.name"]}")
graph_repo.run_write("MATCH (w:Workspace {name: 'smoke_ws'}) DETACH DELETE w")
print("   OK limpiado")
graph_repo.close()

print("3. Pydantic Schemas")
ex = RawExchange.model_validate({
    "exchange_id": str(uuid.uuid4()),
    "timestamp": "2026-08-03T21:00:00Z",
    "host": "api.example.com",
    "method": "GET",
    "path": "/users/15",
    "request": {"headers": [], "cookies": []},
    "response": {"status_code": 200, "headers": [], "cookies": []},
})
print(f"   OK RawExchange: {ex.method} {ex.host}{ex.path}")

print("\n✅ FUNDACION COMPLETA — PostgreSQL + Neo4j + Schemas listos para v0.1")
