"""Esquemas Pydantic v2 de entrada y salida de la API (y de la CLI)."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from core.config import get_settings
from fuzzy.membresias import (
    CONSUMO_MAX,
    CONSUMO_MIN,
    HORA_MAX,
    HORA_MIN,
    PERSONAS_MAX,
    PERSONAS_MIN,
)

_settings = get_settings()

#: Rango válido de cada variable de entrada (mismo universo que el motor).
_RANGOS: dict[str, tuple[float, float]] = {
    "consumo_w": (CONSUMO_MIN, CONSUMO_MAX),
    "personas": (PERSONAS_MIN, PERSONAS_MAX),
    "hora": (HORA_MIN, HORA_MAX),
}


# --------------------------------------------------------------------------- #
# Entradas
# --------------------------------------------------------------------------- #
def _exigir_finito(valor: Any, info: ValidationInfo) -> Any:
    """Rechaza NaN e inf con un mensaje claro (antes de las restricciones ge/le)."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return valor  # Pydantic generará el error de tipo correspondiente.
    if not math.isfinite(numero):
        raise ValueError(f"'{info.field_name}' debe ser un número finito (no se admite NaN ni inf)")
    return valor


class EvaluacionRequest(BaseModel):
    """Una evaluación puntual. Los valores fuera de rango se rechazan (nunca se recortan)."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "id_evaluacion": "caso-informe-3",
                "consumo_w": 1900,
                "personas": 3,
                "hora": 12,
            }
        },
    )

    id_evaluacion: str | None = Field(
        default=None, max_length=100, description="Identificador opcional del cliente"
    )
    consumo_w: float = Field(ge=0, le=3000, description="Potencia demandada en W")
    personas: float = Field(
        ge=0, le=6, description="Personas presentes (admite promedios fraccionarios)"
    )
    hora: float = Field(ge=0, le=24, description="Hora del día en formato decimal (14.5 = 14:30)")

    @field_validator("consumo_w", "personas", "hora", mode="before")
    @classmethod
    def _finito(cls, valor: Any, info: ValidationInfo) -> Any:
        """Rechaza NaN e inf."""
        return _exigir_finito(valor, info)


class LoteRequest(BaseModel):
    """Lote de evaluaciones. La validación es atómica: un ítem inválido → 422 con su índice."""

    evaluaciones: list[EvaluacionRequest] = Field(min_length=1, max_length=_settings.max_lote)


class BarridoRequest(BaseModel):
    """Barrido de una variable manteniendo fijas las otras dos.

    Los valores de las dos variables no barridas son obligatorios; el valor fijo de la
    variable barrida (si se envía) se ignora.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "variable": "hora",
                "desde": 0,
                "hasta": 24,
                "pasos": 25,
                "consumo_w": 1900,
                "personas": 3,
            }
        }
    )

    variable: Literal["consumo_w", "personas", "hora"]
    desde: float
    hasta: float
    pasos: int = Field(ge=2, le=_settings.max_pasos_barrido)
    consumo_w: float | None = Field(default=None, ge=0, le=3000)
    personas: float | None = Field(default=None, ge=0, le=6)
    hora: float | None = Field(default=None, ge=0, le=24)

    @field_validator("desde", "hasta", "consumo_w", "personas", "hora", mode="before")
    @classmethod
    def _finito(cls, valor: Any, info: ValidationInfo) -> Any:
        """Rechaza NaN e inf."""
        return _exigir_finito(valor, info)

    @model_validator(mode="after")
    def _validar_barrido(self) -> BarridoRequest:
        """Comprueba rango del barrido y presencia de los valores fijos."""
        minimo, maximo = _RANGOS[self.variable]
        if not (minimo <= self.desde <= maximo and minimo <= self.hasta <= maximo):
            raise ValueError(
                f"'desde' y 'hasta' deben estar dentro de [{minimo:g}, {maximo:g}] "
                f"para la variable '{self.variable}'"
            )
        if self.desde >= self.hasta:
            raise ValueError("'desde' debe ser menor que 'hasta'")
        faltantes = [
            nombre
            for nombre in _RANGOS
            if nombre != self.variable and getattr(self, nombre) is None
        ]
        if faltantes:
            raise ValueError(f"Falta el valor fijo de: {', '.join(faltantes)}")
        return self


# --------------------------------------------------------------------------- #
# Salidas
# --------------------------------------------------------------------------- #
class EntradasEco(BaseModel):
    """Eco de las entradas evaluadas."""

    consumo_w: float
    personas: float
    hora: float


class ReglaActivadaItem(BaseModel):
    """Regla activada con su grado α (4 decimales)."""

    regla: str
    consumo: str
    personas: str
    hora: str
    salida: str
    alpha: float
    calculo: str


class EvaluacionResponse(BaseModel):
    """Resultado de una evaluación (redondeado solo aquí, en la presentación)."""

    id_evaluacion: str | None = None
    entradas: EntradasEco
    salida_pct: float = Field(description="Nivel de ahorro energético (%), 2 decimales")
    interpretacion: str
    accion_sugerida: str
    fuzzificacion: dict[str, dict[str, float]] = Field(
        description="Grados de pertenencia (4 decimales) por variable y conjunto"
    )
    reglas_activadas: list[ReglaActivadaItem]


class LoteResponse(BaseModel):
    """Resultados de un lote, en el mismo orden de entrada."""

    total: int
    resultados: list[EvaluacionResponse]


class BarridoPunto(BaseModel):
    """Un punto del barrido."""

    valor: float
    salida_pct: float
    interpretacion: str


class BarridoResponse(BaseModel):
    """Resultado de un barrido."""

    variable: str
    puntos: list[BarridoPunto]


class ReglaItem(BaseModel):
    """Una regla de la base (Tabla 8)."""

    id: str
    consumo: str
    personas: str
    hora: str
    salida: str


class CurvasVariable(BaseModel):
    """Curvas muestreadas de una variable difusa."""

    nombre: str
    unidad: str
    x: list[float]
    conjuntos: dict[str, list[float]]


class MembresiasResponse(BaseModel):
    """Curvas muestreadas por variable (``consumo``, ``personas``, ``hora``, ``salida``)."""

    variables: dict[str, CurvasVariable]


class ErrorResponse(BaseModel):
    """Formato único de error de la API."""

    detail: str
    error_code: str
    errors: list[dict[str, Any]] | None = Field(
        default=None, description="Detalle por campo en errores de validación (422)"
    )
