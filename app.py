"""Entrypoint de la aplicacion. Ejecutar con: uvicorn app:app"""

from akg.api.main import app

__all__ = ["app"]
