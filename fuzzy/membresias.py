"""Universos de discurso y funciones de pertenencia (Tablas 2-6 del informe).

Este módulo es la **única fuente de verdad** de los parámetros de las variables
difusas: el motor, la API (``/api/membresias``) y las gráficas lo reutilizan.

Las funciones se evalúan con ``skfuzzy.trapmf`` / ``skfuzzy.trimf``. La variable
``hora`` es circular: Madrugada y Noche se componen con ``np.fmax`` sobre dos
funciones trapezoidales, de modo que 00:00 y 24:00 producen pertenencias idénticas.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Final, Literal

import numpy as np
import skfuzzy as fuzz
from numpy.typing import NDArray

from core.exceptions import EntradaFueraDeRangoError

FloatArray = NDArray[np.float64]
TipoFuncion = Literal["trapezoidal", "triangular"]

# --------------------------------------------------------------------------- #
# Universos de discurso
# --------------------------------------------------------------------------- #
CONSUMO_MIN: Final[float] = 0.0
CONSUMO_MAX: Final[float] = 3000.0
PERSONAS_MIN: Final[float] = 0.0
PERSONAS_MAX: Final[float] = 6.0
HORA_MIN: Final[float] = 0.0
HORA_MAX: Final[float] = 24.0
SALIDA_MIN: Final[float] = 0.0
SALIDA_MAX: Final[float] = 100.0


# --------------------------------------------------------------------------- #
# Estructuras inmutables
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Componente:
    """Una función de pertenencia elemental (trapezoidal o triangular).

    Attributes:
        tipo: ``"trapezoidal"`` (4 parámetros) o ``"triangular"`` (3 parámetros).
        params: Vértices ``(a, b, c[, d])`` en orden no decreciente.
    """

    tipo: TipoFuncion
    params: tuple[float, ...]

    def __post_init__(self) -> None:
        """Valida el número y el orden de los parámetros."""
        esperados = 4 if self.tipo == "trapezoidal" else 3
        if len(self.params) != esperados:
            raise ValueError(f"{self.tipo} requiere {esperados} parámetros: {self.params}")
        if list(self.params) != sorted(self.params):
            raise ValueError(f"Parámetros no ordenados: {self.params}")

    def evaluar(self, x: FloatArray) -> FloatArray:
        """Evalúa la función en el arreglo ``x`` con scikit-fuzzy."""
        if self.tipo == "trapezoidal":
            return fuzz.trapmf(x, list(self.params))
        return fuzz.trimf(x, list(self.params))


@dataclass(frozen=True)
class ConjuntoDifuso:
    """Un conjunto difuso con nombre, compuesto por uno o más componentes.

    Los componentes se combinan con ``np.fmax`` (unión). Un único componente es el
    caso habitual; dos componentes modelan la continuidad circular de la hora.

    Attributes:
        clave: Identificador técnico sin tildes (p. ej. ``"manana"``).
        etiqueta: Nombre para mostrar y usado en las reglas (p. ej. ``"Mañana"``).
        componentes: Funciones elementales que se unen con máximo.
    """

    clave: str
    etiqueta: str
    componentes: tuple[Componente, ...]

    def evaluar(self, x: FloatArray) -> FloatArray:
        """Evalúa el conjunto en ``x`` (máximo de sus componentes)."""
        resultado = self.componentes[0].evaluar(x)
        for componente in self.componentes[1:]:
            resultado = np.fmax(resultado, componente.evaluar(x))
        return resultado


@dataclass(frozen=True)
class VariableDifusa:
    """Variable lingüística: universo de discurso + conjuntos difusos.

    Attributes:
        clave: Identificador técnico (``"consumo"``, ``"personas"``...).
        nombre: Nombre legible.
        unidad: Unidad física (``"W"``, ``"h"``, ``"%"``, ``"personas"``).
        minimo: Límite inferior del universo.
        maximo: Límite superior del universo.
        conjuntos: Conjuntos difusos, en el orden de las tablas del informe.
    """

    clave: str
    nombre: str
    unidad: str
    minimo: float
    maximo: float
    conjuntos: tuple[ConjuntoDifuso, ...]

    @property
    def etiquetas(self) -> tuple[str, ...]:
        """Etiquetas de los conjuntos, en orden."""
        return tuple(c.etiqueta for c in self.conjuntos)

    @property
    def claves(self) -> tuple[str, ...]:
        """Claves técnicas de los conjuntos, en orden."""
        return tuple(c.clave for c in self.conjuntos)

    def conjunto(self, etiqueta: str) -> ConjuntoDifuso:
        """Devuelve el conjunto con la etiqueta dada.

        Raises:
            KeyError: Si la etiqueta no existe en la variable.
        """
        for conjunto in self.conjuntos:
            if conjunto.etiqueta == etiqueta:
                return conjunto
        raise KeyError(f"Etiqueta {etiqueta!r} inexistente en la variable {self.clave!r}")

    def clave_de(self, etiqueta: str) -> str:
        """Traduce una etiqueta (``"Mañana"``) a su clave (``"manana"``)."""
        return self.conjunto(etiqueta).clave

    def validar(self, valor: float) -> float:
        """Comprueba que ``valor`` sea finito y esté en el universo (sin clamp).

        Raises:
            EntradaFueraDeRangoError: Si es NaN/inf o queda fuera de ``[minimo, maximo]``.
        """
        try:
            numero = float(valor)
        except (TypeError, ValueError) as exc:
            raise EntradaFueraDeRangoError(
                f"{self.nombre}: el valor {valor!r} no es numérico"
            ) from exc
        if not math.isfinite(numero):
            raise EntradaFueraDeRangoError(f"{self.nombre}: el valor debe ser finito, no {numero}")
        if not self.minimo <= numero <= self.maximo:
            raise EntradaFueraDeRangoError(
                f"{self.nombre}: {numero} fuera del universo [{self.minimo}, {self.maximo}] "
                f"{self.unidad}"
            )
        return numero

    def fuzzificar(self, valor: float) -> dict[str, float]:
        """Grados de pertenencia exactos (sin redondear) por clave de conjunto."""
        x = np.array([self.validar(valor)], dtype=np.float64)
        return {c.clave: float(c.evaluar(x)[0]) for c in self.conjuntos}

    def curvas(self, x: FloatArray) -> dict[str, FloatArray]:
        """Evalúa todos los conjuntos sobre el arreglo ``x``."""
        return {c.clave: c.evaluar(x) for c in self.conjuntos}


def _trap(*params: float) -> Componente:
    return Componente("trapezoidal", tuple(float(p) for p in params))


def _tri(*params: float) -> Componente:
    return Componente("triangular", tuple(float(p) for p in params))


# --------------------------------------------------------------------------- #
# Parámetros exactos del informe
# --------------------------------------------------------------------------- #
CONSUMO: Final[VariableDifusa] = VariableDifusa(
    clave="consumo",
    nombre="Consumo eléctrico",
    unidad="W",
    minimo=CONSUMO_MIN,
    maximo=CONSUMO_MAX,
    conjuntos=(
        ConjuntoDifuso("bajo", "Bajo", (_trap(0, 0, 500, 1200),)),
        ConjuntoDifuso("medio", "Medio", (_tri(700, 1500, 2200),)),
        ConjuntoDifuso("alto", "Alto", (_trap(1800, 2500, 3000, 3000),)),
    ),
)

PERSONAS: Final[VariableDifusa] = VariableDifusa(
    clave="personas",
    nombre="Cantidad de personas",
    unidad="personas",
    minimo=PERSONAS_MIN,
    maximo=PERSONAS_MAX,
    conjuntos=(
        ConjuntoDifuso("pocas", "Pocas", (_trap(0, 0, 1, 2),)),
        ConjuntoDifuso("moderadas", "Moderadas", (_tri(1, 3, 5),)),
        ConjuntoDifuso("muchas", "Muchas", (_trap(4, 5, 6, 6),)),
    ),
)

HORA: Final[VariableDifusa] = VariableDifusa(
    clave="hora",
    nombre="Hora del día",
    unidad="h",
    minimo=HORA_MIN,
    maximo=HORA_MAX,
    conjuntos=(
        # Variable circular: máx( trapecio diurno ; trapecio que cruza la medianoche ).
        ConjuntoDifuso("madrugada", "Madrugada", (_trap(0, 0, 4, 7), _trap(22, 24, 24, 24))),
        ConjuntoDifuso("manana", "Mañana", (_tri(5, 9, 13),)),
        ConjuntoDifuso("tarde", "Tarde", (_tri(11, 15, 19),)),
        ConjuntoDifuso("noche", "Noche", (_trap(17, 21, 24, 24), _trap(0, 0, 0, 2))),
    ),
)

SALIDA: Final[VariableDifusa] = VariableDifusa(
    clave="salida",
    nombre="Nivel de ahorro energético",
    unidad="%",
    minimo=SALIDA_MIN,
    maximo=SALIDA_MAX,
    conjuntos=(
        ConjuntoDifuso("muy_bajo", "Muy bajo", (_trap(0, 0, 10, 25),)),
        ConjuntoDifuso("bajo", "Bajo", (_tri(15, 30, 45),)),
        ConjuntoDifuso("medio", "Medio", (_tri(35, 50, 65),)),
        ConjuntoDifuso("alto", "Alto", (_tri(55, 70, 85),)),
        ConjuntoDifuso("muy_alto", "Muy alto", (_trap(75, 90, 100, 100),)),
    ),
)

#: Todas las variables por clave (solo lectura).
VARIABLES: Final[Mapping[str, VariableDifusa]] = MappingProxyType(
    {v.clave: v for v in (CONSUMO, PERSONAS, HORA, SALIDA)}
)


# --------------------------------------------------------------------------- #
# Fuzzificación (funciones puras; grados exactos, sin redondear)
# --------------------------------------------------------------------------- #
def fuzzificar_consumo(w: float) -> dict[str, float]:
    """Grados de pertenencia de un consumo en vatios (``bajo``, ``medio``, ``alto``)."""
    return CONSUMO.fuzzificar(w)


def fuzzificar_personas(n: float) -> dict[str, float]:
    """Grados de pertenencia de la cantidad de personas (``pocas``, ``moderadas``, ``muchas``)."""
    return PERSONAS.fuzzificar(n)


def fuzzificar_hora(h: float) -> dict[str, float]:
    """Grados de pertenencia de la hora decimal.

    Claves: ``madrugada``, ``manana``, ``tarde``, ``noche``. Las horas 0 y 24
    producen grados idénticos (circularidad).
    """
    return HORA.fuzzificar(h)


# --------------------------------------------------------------------------- #
# Funciones de salida precalculadas
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, eq=False)
class FuncionesSalida:
    """Universo de salida y funciones de pertenencia precalculadas (solo lectura).

    Attributes:
        paso: Resolución solicitada del universo.
        universo: Arreglo de 0 a 100 (inclusive), de solo lectura.
        funciones: Pertenencia de cada conjunto de salida (por clave), de solo lectura.
    """

    paso: float
    universo: FloatArray
    funciones: Mapping[str, FloatArray]


@lru_cache(maxsize=16)
def funciones_salida(paso_salida: float = 0.01) -> FuncionesSalida:
    """Calcula **una sola vez** por paso las funciones de salida sobre el universo.

    El resultado se cachea con ``lru_cache`` y sus arreglos se marcan como no
    escribibles, por lo que es seguro compartirlo entre hilos.

    Args:
        paso_salida: Resolución del universo de salida; ``0 < paso <= 1``.

    Raises:
        EntradaFueraDeRangoError: Si el paso no cumple ``0 < paso <= 1``.
    """
    if not (math.isfinite(paso_salida) and 0 < paso_salida <= 1):
        raise EntradaFueraDeRangoError(f"paso_salida debe cumplir 0 < paso <= 1: {paso_salida}")
    n_puntos = int(round((SALIDA_MAX - SALIDA_MIN) / paso_salida)) + 1
    universo = np.linspace(SALIDA_MIN, SALIDA_MAX, n_puntos, dtype=np.float64)
    universo.flags.writeable = False
    funciones: dict[str, FloatArray] = {}
    for clave, curva in SALIDA.curvas(universo).items():
        curva = np.array(curva, dtype=np.float64)
        curva.flags.writeable = False
        funciones[clave] = curva
    return FuncionesSalida(
        paso=paso_salida, universo=universo, funciones=MappingProxyType(funciones)
    )


def muestrear_variable(
    variable: VariableDifusa, n_puntos: int
) -> tuple[FloatArray, dict[str, FloatArray]]:
    """Muestrea las curvas de una variable en ``n_puntos`` equiespaciados.

    Returns:
        Tupla ``(x, curvas_por_clave)``.
    """
    if n_puntos < 2:
        raise ValueError("n_puntos debe ser >= 2")
    x = np.linspace(variable.minimo, variable.maximo, n_puntos, dtype=np.float64)
    return x, variable.curvas(x)
