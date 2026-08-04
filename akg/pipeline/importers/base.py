from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO, Protocol

from akg.schemas import RawExchange


@dataclass
class ValidationReport:
    valid: bool
    total_exchanges: int = 0
    errors: list[dict] = field(default_factory=list)
    message: str = ""


class ImportAdapter(Protocol):
    """Contrato para todos los adaptadores de importación (ADR-004, desacople del origen)."""

    format_name: str

    def parse(
        self,
        stream: BinaryIO,
        import_id: str | None = None,
    ) -> tuple[list[RawExchange], list[dict]]:
        """Parsa el stream en RawExchange[]. Devuelve (exchanges, parse_errors)."""
        ...
