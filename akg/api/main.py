"""Aplicacion FastAPI de API Knowledge Graph (SAD cap. 9)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from akg.api.graph_routes import router as graph_router
from akg.api.routes import router as main_router
from akg.api.schemas import ApiError

logger = logging.getLogger(__name__)


class NoCacheStaticFiles(StaticFiles):
    """Sirve assets estaticos sin cache para que los cambios se reflejen al instante."""

    def file_response(self, *args, **kwargs) -> Response:
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-store"
        return resp


def _envelope(code: str, message: str, details: dict | None = None) -> ApiError:
    return ApiError(error={"code": code, "message": message, "details": details})


def create_app() -> FastAPI:
    app = FastAPI(
        title="API Knowledge Graph",
        version="0.1.0",
        description=(
            "Plataforma inteligente para el analisis de seguridad de APIs. "
            "Transforma trafico exportado en un grafo de conocimiento navegable."
        ),
    )
    app.include_router(main_router)
    app.include_router(graph_router)
    app.mount(
        "/ui",
        NoCacheStaticFiles(directory="akg/ui", html=True),
        name="ui",
    )

    @app.get("/health", summary="Healthcheck")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.1.0"}

    # ── envelope de errores unificado (V0.1-34) ─────────────────────────
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        code = str(exc.status_code)
        message = detail if isinstance(detail, str) else "error de la API"
        if isinstance(detail, dict):
            message = detail.get("message", "error de la API")
            code = str(detail.get("code", exc.status_code))
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, message).model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        message = first.get("msg", "parametros invalidos")
        return JSONResponse(
            status_code=422,
            content=_envelope("VALIDATION_ERROR", message, {"location": loc, "count": len(errors)})
            .model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("error no manejado en %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=_envelope("INTERNAL_ERROR", "error interno del servidor").model_dump(
                mode="json"
            ),
        )

    return app


app = create_app()
