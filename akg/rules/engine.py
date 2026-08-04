"""Motor de ejecucion de reglas (SAD 8.5).

Pasos: seleccion -> compilacion (Cypher con $import_id) -> ejecucion ->
filtrado (where) -> agrupacion -> alertas. Las alertas llevan evidencia
(exchange_ids, node_keys) para trazabilidad en la UI.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from akg.rules.dsl import RuleSpec


class GraphQuery(Protocol):
    """Contrato minimo de consulta de grafo para el motor (lectura estricta)."""

    def run_read(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        db: str = "neo4j",
        timeout: int = 15,
    ) -> list[dict[str, Any]]: ...


@dataclass
class AlertCandidate:
    rule: RuleSpec
    title: str
    evidence: dict[str, Any]
    fields: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.6


def _op(value: Any, op: str, expected: Any) -> bool:
    ops = {
        "eq": lambda v, e: v == e,
        "neq": lambda v, e: v != e,
        "gte": lambda v, e: v >= e,
        "gt": lambda v, e: v > e,
        "lte": lambda v, e: v <= e,
        "lt": lambda v, e: v < e,
        "in": lambda v, e: v in e,
        "contains": lambda v, e: (e in v) if isinstance(v, str) else False,
        "not_contains_any": lambda v, e: (
            isinstance(v, str) and not any(x in v for x in e)
        ) if isinstance(e, list) else True,
        "not": lambda v, e: (v not in e) if isinstance(e, (list, set, tuple)) else v != e,
        "is_null": lambda v, e: v is None,
        "not_null": lambda v, e: v is not None,
    }
    if op not in ops:
        return True
    try:
        return ops[op](value, expected)
    except TypeError:
        return False


def _matches_where(row: dict[str, Any], where: dict) -> bool:
    for fname, cond in where.items():
        if isinstance(cond, dict):
            for op, expected in cond.items():
                if not _op(row.get(fname), op, expected):
                    return False
        else:
            if row.get(fname) != cond:
                return False
    return True


def _title_template(title: str, fields: dict[str, Any]) -> str:
    out = title
    for k, v in fields.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def run_rules(
    rules: list[RuleSpec],
    import_id: uuid.UUID,
    graph: GraphQuery,
    *,
    limit: int = 5000,
) -> list[AlertCandidate]:
    """Ejecuta las reglas contra el grafo y devuelve candidatos a alerta."""
    alerts: list[AlertCandidate] = []
    params = {"import_id": str(import_id)}

    for rule in rules:
        if not rule.enabled:
            continue
        try:
            rows = graph.run_read(rule.match, params, timeout=30)
        except Exception:
            continue  # grafo inaccesible o query invalida: se omite la regla

        grouped: dict[Any, dict[str, Any]] = {}
        for row in rows[:limit]:
            if rule.where and not _matches_where(row, rule.where):
                continue
            key = row.get(rule.group_by) if rule.group_by else _row_key(row)
            if rule.group_by:
                acc = grouped.setdefault(key, {"_fields": {}, "_count": 0})
                for k, v in row.items():
                    acc["_fields"][k] = v
                acc["_count"] += 1
            else:
                grouped.setdefault(key, {"_fields": dict(row), "_count": 1})

        for key, acc in grouped.items():
            fields = dict(acc["_fields"])
            title = _title_template(rule.emit_title, fields)
            alerts.append(
                AlertCandidate(
                    rule=rule,
                    title=title,
                    evidence={
                        "rule_id": rule.rule_id,
                        "import_id": str(import_id),
                        "group_key": str(key),
                        "fields": fields,
                        "occurrences": acc["_count"],
                    },
                    fields=fields,
                    confidence=rule.confidence,
                )
            )

    return alerts


def _row_key(row: dict[str, Any]) -> str:
    return "|".join(f"{k}={row.get(k)}" for k in sorted(row))
