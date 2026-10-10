"""Aplicación FastAPI del sistema difuso de gestión del consumo eléctrico.

Ejecución: ``uvicorn main:app --reload`` (dev) o ``uvicorn main:app --host 0.0.0.0`` (prod).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import APP_NAME, APP_VERSION, get_settings
from core.exceptions import MotorDifusoError
from core.logging_config import configure_logging
from routers.api import router as api_router
from schemas.difuso import ErrorResponse
from services.difuso_service import DifusoService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configura logging e instancia ``DifusoService`` una sola vez (en ``app.state``)."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    logger.info("Iniciando backend", extra={"environment": settings.environment})
    app.state.servicio = DifusoService(settings)
    yield
    logger.info("Backend detenido")


def _formatear_loc(loc: tuple[Any, ...]) -> str:
    """``("body", "evaluaciones", 2, "hora")`` → ``"evaluaciones[2].hora"``."""
    texto = ""
    for parte in loc:
        if parte in ("body", "query", "path"):
            continue
        if isinstance(parte, int):
            texto += f"[{parte}]"
        else:
            texto += f".{parte}" if texto else str(parte)
    return texto or "(cuerpo)"


async def _validacion(_: Request, exc: RequestValidationError) -> JSONResponse:
    """422 con formato ``ErrorResponse``; el detalle incluye el índice del ítem inválido."""
    errores = [
        {
            "campo": _formatear_loc(tuple(e["loc"])),
            "mensaje": str(e["msg"]),
            "tipo": str(e["type"]),
        }
        for e in exc.errors()
    ]
    detalle = "; ".join(f"{e['campo']}: {e['mensaje']}" for e in errores)
    cuerpo = ErrorResponse(
        detail=f"Entrada inválida: {detalle}", error_code="VALIDATION_ERROR", errors=errores
    )
    return JSONResponse(status_code=422, content=cuerpo.model_dump(exclude_none=True))


async def _error_motor(_: Request, exc: Exception) -> JSONResponse:
    """``MotorDifusoError`` → 500 con ``ErrorResponse``."""
    codigo = exc.codigo if isinstance(exc, MotorDifusoError) else MotorDifusoError.codigo
    cuerpo = ErrorResponse(detail=str(exc), error_code=codigo)
    return JSONResponse(status_code=500, content=cuerpo.model_dump(exclude_none=True))


async def _error_inesperado(_: Request, exc: Exception) -> JSONResponse:
    """Cualquier otra excepción → 500 genérico (sin filtrar detalles internos)."""
    logger.error("Excepción no controlada", exc_info=exc)
    cuerpo = ErrorResponse(detail="Error interno del servidor", error_code="ERROR_INTERNO")
    return JSONResponse(status_code=500, content=cuerpo.model_dump(exclude_none=True))


def create_app() -> FastAPI:
    """Construye la aplicación FastAPI."""
    settings = get_settings()
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        description=(
            "Sistema de inferencia difusa tipo Mamdani (36 reglas, centroide) que recomienda "
            "el nivel de ahorro energético (0–100 %) a partir del consumo (W), las personas "
            "presentes y la hora del día. Proyecto UNMSM · Sistemas Inteligentes · Grupo 6."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_exception_handler(RequestValidationError, _validacion)  # type: ignore[arg-type]
    app.add_exception_handler(MotorDifusoError, _error_motor)
    app.add_exception_handler(Exception, _error_inesperado)
    app.include_router(api_router)

    @app.get("/health", tags=["salud"])
    def health(request: Request) -> JSONResponse:
        """Estado del servicio: 200 si reglas, funciones de salida y caso de prueba están OK."""
        servicio: DifusoService = request.app.state.servicio
        sano = servicio.health_check()
        return JSONResponse(
            status_code=200 if sano else 503,
            content={"status": "ok" if sano else "degraded", "version": APP_VERSION},
        )

    return app


app = create_app()
