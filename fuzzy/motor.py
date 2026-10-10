"""Motor de inferencia difusa tipo Mamdani.

Pipeline (replica el informe): fuzzificación → activación (AND = MIN) →
implicación (MIN, recorte al nivel α) → agregación (MAX) → defuzzificación por
centroide.

Decisión de concurrencia: :func:`evaluar` es una **función pura**. No lee ni
escribe estado mutable compartido: las reglas son una tupla inmutable, las
funciones de salida son arreglos de solo lectura precalculados y cada llamada
construye sus propios arreglos temporales. Por eso, a diferencia de un motor
basado en CLIPS (con una base de hechos mutable que exige serializar el acceso),
aquí **no hace falta ningún ``Lock``** y varias hebras pueden evaluar en paralelo.

Decisión de implementación: se usan las primitivas de scikit-fuzzy a bajo nivel
(``trapmf``, ``trimf``, ``defuzz``) en lugar de ``skfuzzy.control.ControlSystem``,
porque este último mantiene estado interno por simulación (no es seguro entre
hilos), oculta los pasos intermedios que el informe necesita mostrar (α por regla,
conjuntos recortados, agregado) y es notablemente más lento.

La salida **no se redondea** aquí: el redondeo es responsabilidad de la capa de
presentación.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
import skfuzzy as fuzz
from numpy.typing import NDArray

from core.exceptions import DefuzzificacionError
from fuzzy.interpretacion import interpretar
from fuzzy.membresias import (
    CONSUMO,
    HORA,
    PERSONAS,
    SALIDA,
    funciones_salida,
    fuzzificar_consumo,
    fuzzificar_hora,
    fuzzificar_personas,
)
from fuzzy.reglas import REGLAS, Regla

FloatArray = NDArray[np.float64]

#: Paso por defecto del universo de salida (coincide con los casos verificados).
PASO_SALIDA_DEFECTO: Final[float] = 0.01

# Precalcula, una sola vez, las claves de cada regla para no traducir etiquetas por evaluación.
_REGLAS_INDEXADAS: Final[tuple[tuple[Regla, str, str, str, str], ...]] = tuple(
    (
        regla,
        CONSUMO.clave_de(regla.consumo),
        PERSONAS.clave_de(regla.personas),
        HORA.clave_de(regla.hora),
        SALIDA.clave_de(regla.salida),
    )
    for regla in REGLAS
)


@dataclass(frozen=True)
class ReglaActivada:
    """Una regla con grado de activación α > 0.

    Attributes:
        regla: Identificador (``"R18"``).
        consumo: Etiqueta de consumo del antecedente.
        personas: Etiqueta de personas del antecedente.
        hora: Etiqueta de hora del antecedente.
        salida: Etiqueta del consecuente.
        alpha: Grado de activación exacto, ``min(μ_consumo, μ_personas, μ_hora)``.
        calculo: Texto del cálculo, p. ej. ``"mín(0,4286; 1,0000; 0,2500)"``.
    """

    regla: str
    consumo: str
    personas: str
    hora: str
    salida: str
    alpha: float
    calculo: str


@dataclass(frozen=True, eq=False)
class ResultadoInferencia:
    """Resultado completo (y sin redondear) de una inferencia.

    Attributes:
        entradas: Eco de las entradas (``consumo_w``, ``personas``, ``hora``).
        salida_pct: Nivel de ahorro defuzzificado (centroide), sin redondear.
        interpretacion: Texto de la Tabla 11.
        accion_sugerida: Acción de la Tabla 11.
        fuzzificacion: Grados por variable y conjunto (incluye los de valor 0).
        reglas_activadas: Reglas con α > 0, en orden R1..R36.
        universo: Universo de salida (solo lectura), para gráficas.
        agregado: Conjunto de salida agregado (solo lectura), para gráficas.
    """

    entradas: dict[str, float]
    salida_pct: float
    interpretacion: str
    accion_sugerida: str
    fuzzificacion: dict[str, dict[str, float]]
    reglas_activadas: list[ReglaActivada]
    universo: FloatArray
    agregado: FloatArray


def _fmt(grado: float) -> str:
    """Formatea un grado con 4 decimales y coma decimal (solo para presentación)."""
    return f"{grado:.4f}".replace(".", ",")


def evaluar(
    consumo_w: float,
    personas: float,
    hora: float,
    paso_salida: float = PASO_SALIDA_DEFECTO,
) -> ResultadoInferencia:
    """Ejecuta el pipeline Mamdani completo para una combinación de entradas.

    Args:
        consumo_w: Potencia demandada en W, en ``[0, 3000]``.
        personas: Personas presentes, en ``[0, 6]`` (admite fraccionarios).
        hora: Hora decimal en ``[0, 24]`` (14.5 = 14:30). 0 y 24 son equivalentes.
        paso_salida: Resolución del universo de salida para el centroide.

    Returns:
        :class:`ResultadoInferencia` con la salida sin redondear.

    Raises:
        EntradaFueraDeRangoError: Si alguna entrada es NaN/inf o está fuera de rango
            (nunca se recorta en silencio).
        DefuzzificacionError: Si el área agregada es nula o el centroide no es válido.
    """
    # 1. Fuzzificación (valida rangos y NaN/inf).
    mu_consumo = fuzzificar_consumo(consumo_w)
    mu_personas = fuzzificar_personas(personas)
    mu_hora = fuzzificar_hora(hora)
    salida = funciones_salida(paso_salida)

    # 2-3. Activación (MIN), implicación (MIN) y agregación (MAX).
    agregado: FloatArray = np.zeros_like(salida.universo)
    activadas: list[ReglaActivada] = []
    for regla, k_consumo, k_personas, k_hora, k_salida in _REGLAS_INDEXADAS:
        g_consumo = mu_consumo[k_consumo]
        g_personas = mu_personas[k_personas]
        g_hora = mu_hora[k_hora]
        alpha = min(g_consumo, g_personas, g_hora)
        if alpha <= 0.0:
            continue
        recorte = np.minimum(alpha, salida.funciones[k_salida])
        agregado = np.maximum(agregado, recorte)
        activadas.append(
            ReglaActivada(
                regla=regla.id,
                consumo=regla.consumo,
                personas=regla.personas,
                hora=regla.hora,
                salida=regla.salida,
                alpha=alpha,
                calculo=f"mín({_fmt(g_consumo)}; {_fmt(g_personas)}; {_fmt(g_hora)})",
            )
        )
    agregado.flags.writeable = False

    # 4. Defuzzificación por centroide.
    if not np.any(agregado > 0.0):
        raise DefuzzificacionError(
            "Área agregada nula: ninguna regla se activó "
            f"(consumo_w={consumo_w}, personas={personas}, hora={hora})"
        )
    centroide = float(fuzz.defuzz(salida.universo, agregado, "centroid"))
    if not math.isfinite(centroide):
        raise DefuzzificacionError(f"Centroide no finito para {consumo_w}/{personas}/{hora}")

    interpretacion, accion = interpretar(centroide)
    return ResultadoInferencia(
        entradas={
            "consumo_w": float(consumo_w),
            "personas": float(personas),
            "hora": float(hora),
        },
        salida_pct=centroide,
        interpretacion=interpretacion,
        accion_sugerida=accion,
        fuzzificacion={
            "consumo": mu_consumo,
            "personas": mu_personas,
            "hora": mu_hora,
        },
        reglas_activadas=activadas,
        universo=salida.universo,
        agregado=agregado,
    )
