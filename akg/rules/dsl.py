"""Modelos del DSL de reglas (SAD cap. 8).

Una regla describe *que* buscar (patron de grafo + filtros + salida), no *como*.
Se compone de tres bloques:

- `when.match`: Cypher de lectura (solo MATCH/RETURN) parametrizado con `$import_id`.
- `where`: filtros sobre las filas emitidas por `match` (operadores eq/neq/gte/...).
- `emit`: titulo templado, severidad, evidencia y referencias.

Reglas = datos, no codigo (ADR-009). El catalogo vive versionado y se persiste
en la tabla `rules`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuleSpec:
    """Definicion declarativa de una regla."""

    rule_id: str
    name: str
    category: str
    severity: str
    match: str
    emit_title: str
    version: int = 1
    description: str | None = None
    enabled: bool = True
    where: dict = field(default_factory=dict)
    group_by: str | None = None
    references: list[str] = field(default_factory=list)
    mitigation: str | None = None
    confidence: float = 0.6
    limit: int = 5000

    def to_dsl(self) -> dict:
        """Serializa la regla al formato `dsl` de la tabla rules."""
        return {
            "when": {"match": self.match},
            "where": self.where,
            "group_by": self.group_by,
            "emit": {
                "title": self.emit_title,
                "severity": self.severity,
                "references": self.references,
                "mitigation": self.mitigation,
            },
        }

    @classmethod
    def from_dsl(cls, rule_id: str, name: str, category: str, dsl: dict) -> RuleSpec:
        return cls(
            rule_id=rule_id,
            name=name,
            category=category,
            severity=dsl.get("emit", {}).get("severity", "MEDIA"),
            match=dsl["when"]["match"],
            emit_title=dsl.get("emit", {}).get("title", name),
            version=int(dsl.get("version", 1)),
            description=None,
            enabled=bool(dsl.get("enabled", True)),
            where=dsl.get("where", {}),
            group_by=dsl.get("group_by"),
            references=dsl.get("emit", {}).get("references", []),
            mitigation=dsl.get("emit", {}).get("mitigation"),
        )
