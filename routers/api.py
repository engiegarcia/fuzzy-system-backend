"""Endpoints REST bajo el prefijo ``/api``.

Los endpoints son ``def`` (no ``async def``): el cálculo es CPU-bound, así que
FastAPI los ejecuta en su threadpool sin bloquear el event loop.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from schemas.difuso import (
    BarridoRequest,
    BarridoResponse,
    ErrorResponse,
    EvaluacionRequest,
    EvaluacionResponse,
    LoteRequest,
    LoteResponse,
    MembresiasResponse,
    ReglaItem,
)
from services.difuso_service import DifusoService

router = APIRouter(prefix="/api", tags=["difuso"])

_ERRORES = {
    422: {
        "model": ErrorResponse,
        "description": "Entrada inválida (fuera de rango, NaN, faltante)",
    },
    500: {"model": ErrorResponse, "description": "Error interno del motor difuso"},
}
_PNG = {200: {"content": {"image/png": {}}, "description": "Imagen PNG"}}


def get_servicio(request: Request) -> DifusoService:
    """Dependencia: devuelve el servicio creado una sola vez en el ``lifespan``."""
    servicio: DifusoService = request.app.state.servicio
    return servicio


Servicio = Annotated[DifusoService, Depends(get_servicio)]


@router.post("/evaluar", response_model=EvaluacionResponse, responses=_ERRORES)
def evaluar(req: EvaluacionRequest, servicio: Servicio) -> EvaluacionResponse:
    """Evalúa una combinación de consumo, personas y hora."""
    return servicio.evaluar(req)


@router.post("/evaluar/lote", response_model=LoteResponse, responses=_ERRORES)
def evaluar_lote(req: LoteRequest, servicio: Servicio) -> LoteResponse:
    """Evalúa un lote (validación atómica: un ítem inválido rechaza todo el lote)."""
    return servicio.evaluar_lote(req.evaluaciones)


@router.post("/barrido", response_model=BarridoResponse, responses=_ERRORES)
def barrido(req: BarridoRequest, servicio: Servicio) -> BarridoResponse:
    """Varía una variable y mantiene las otras dos fijas."""
    return servicio.barrido(req)


@router.get("/reglas", response_model=list[ReglaItem], responses={500: _ERRORES[500]})
def reglas(servicio: Servicio) -> list[ReglaItem]:
    """Las 36 reglas de la base (Tabla 8)."""
    return servicio.reglas()


@router.get("/membresias", response_model=MembresiasResponse, responses={500: _ERRORES[500]})
def membresias(servicio: Servicio) -> MembresiasResponse:
    """Curvas de pertenencia muestreadas de las cuatro variables."""
    return servicio.membresias()


@router.get(
    "/grafico/agregacion",
    response_class=Response,
    responses={**_PNG, **_ERRORES},
)
def grafico_agregacion(
    params: Annotated[EvaluacionRequest, Query()], servicio: Servicio
) -> Response:
    """Figura 4 (agregación y centroide) para la entrada indicada."""
    return Response(content=servicio.grafico_agregacion(params), media_type="image/png")


@router.get(
    "/grafico/membresias/{n}",
    response_class=Response,
    responses={**_PNG, 404: {"model": ErrorResponse}, **_ERRORES},
)
def grafico_membresias(
    n: Annotated[int, Path(description="Figura: 1 (consumo/personas), 2 (hora), 3 (salida)")],
    servicio: Servicio,
) -> Response:
    """Figuras 1–3 del informe. Responde 404 si ``n`` no está en {1, 2, 3}."""
    if n not in (1, 2, 3):
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                detail=f"No existe la figura de membresías {n}; use 1, 2 o 3",
                error_code="FIGURA_NO_ENCONTRADA",
            ).model_dump(exclude_none=True),
        )
    return Response(content=servicio.grafico_membresias(n), media_type="image/png")
