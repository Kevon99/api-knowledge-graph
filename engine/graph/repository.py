from __future__ import annotations

import uuid
from typing import Any

from neo4j import GraphDatabase

from akg.config import settings


class GraphRepository:
    """Acceso al grafo de conocimiento (Neo4j). Consultas de lectura en sandbox."""

    def __init__(self) -> None:
        self._driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_lifetime=3600,
            max_connection_pool_size=20,
        )

    def close(self) -> None:
        self._driver.close()

    def run_read(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        db: str = "neo4j",
        timeout: int = 15,
    ) -> list[dict[str, Any]]:
        params = params or {}
        with self._driver.session(database=db) as session:
            result = session.run(cypher, params, timeout=timeout)
            rows = [record.data() for record in result]
            return rows

    def run_write(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        db: str = "neo4j",
        timeout: int = 30,
    ) -> list[dict[str, Any]]:
        params = params or {}
        with self._driver.session(database=db) as session:
            result = session.run(cypher, params, timeout=timeout)
            # consume so write executes
            summary = result.consume()
            counters = summary.counters
            return [
                {
                    "nodes_created": counters.nodes_created,
                    "nodes_deleted": counters.nodes_deleted,
                    "relationships_created": counters.relationships_created,
                    "relationships_deleted": counters.relationships_deleted,
                }
            ]

    def upsert_node(
        self,
        label: str,
        properties: dict[str, Any],
        key_properties: list[str],
        *,
        import_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        merge_parts = ", ".join(f"{k}: ${k}" for k in key_properties)
        set_keys = [k for k in properties if k not in key_properties]
        full_props = dict(properties)
        if import_id:
            full_props["import_id"] = str(import_id)
            set_keys.append("import_id")
        set_parts = ", ".join(f"n.{k} = ${k}" for k in set_keys)
        if set_parts:
            cypher = f"MERGE (n:{label} {{ {merge_parts} }}) SET {set_parts} RETURN n"
        else:
            cypher = f"MERGE (n:{label} {{ {merge_parts} }}) RETURN n"
        return self.run_write(cypher, full_props)

    def upsert_relationship(
        self,
        from_match: str,
        from_params: dict[str, Any],
        to_match: str,
        to_params: dict[str, Any],
        rel_type: str,
        rel_properties: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        rel_props = dict(rel_properties or {})
        for k, v in rel_props.items():
            if isinstance(v, uuid.UUID):
                rel_props[k] = str(v)
        # prefijar parametros por lado para soportar claves iguales (p.ej.
        # Endpoint -> Endpoint en relaciones NEXT)
        from_stored = {f"from_{k}": v for k, v in from_params.items()}
        to_stored = {f"to_{k}": v for k, v in to_params.items()}
        rel_set = ", ".join(f"r.{k} = ${k}" for k in rel_props) if rel_props else ""
        all_params = dict(**from_stored, **to_stored, **rel_props)
        from_match_parts = ", ".join(f"{k}: $from_{k}" for k in from_params)
        to_match_parts = ", ".join(f"{k}: $to_{k}" for k in to_params)
        stmt = (
            f"MATCH (a:{from_match} {{ {from_match_parts} }}) "
            f"MATCH (b:{to_match} {{ {to_match_parts} }}) "
            f"MERGE (a)-[r:{rel_type}]->(b) " + (f"SET {rel_set}" if rel_set else "")
        )
        return self.run_write(stmt, all_params)

    def health(self) -> bool:
        try:
            self.run_read("RETURN 1 AS ok", timeout=2)
            return True
        except Exception:
            return False


# singleton instance for the app
graph_repo = GraphRepository()
