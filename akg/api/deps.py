"""Dependencias compartidas de la API (sesiones, repositorios)."""

from __future__ import annotations

from collections.abc import Generator

from akg.database import SessionLocal
from akg.evidence.repository import EvidenceRepository


def get_db() -> Generator[EvidenceRepository, None, None]:
    """Dependencia FastAPI: sesion + repositorio por request."""
    repo = EvidenceRepository(session=SessionLocal())
    try:
        yield repo
    finally:
        repo.close()
