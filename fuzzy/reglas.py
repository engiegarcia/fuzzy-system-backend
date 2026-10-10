"""Base de reglas difusas (Tabla 8 del informe) con validación al importar.

La tupla :data:`REGLAS` es la **única fuente de verdad**: el motor, la API
(``GET /api/reglas``) y la CLI la leen de aquí. La heurística de generación
(:func:`generar_reglas_heuristica`) no se usa en tiempo de ejecución: existe para
que las pruebas comprueben que reproduce exactamente la tabla.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from core.exceptions import ConfiguracionReglasError
from fuzzy.membresias import CONSUMO, HORA, PERSONAS, SALIDA

TOTAL_REGLAS: Final[int] = 36

#: Abreviaturas de salida usadas en la Tabla 8.
ABREVIATURAS_SALIDA: Final[dict[str, str]] = {
    "MB": "Muy bajo",
    "B": "Bajo",
    "M": "Medio",
    "A": "Alto",
    "MA": "Muy alto",
}

#: Orden de las columnas de hora en la Tabla 8.
ORDEN_HORAS: Final[tuple[str, ...]] = ("Madrugada", "Mañana", "Tarde", "Noche")

#: Escala numérica de la heurística (0 = Muy bajo ... 4 = Muy alto).
ESCALA_SALIDA: Final[tuple[str, ...]] = ("Muy bajo", "Bajo", "Medio", "Alto", "Muy alto")


@dataclass(frozen=True)
class Regla:
    """Regla ``SI consumo Y personas Y hora ENTONCES salida``.

    Attributes:
        id: Identificador ``R1``..``R36``.
        consumo: Etiqueta del antecedente de consumo (``"Bajo"``, ``"Medio"``, ``"Alto"``).
        personas: Etiqueta del antecedente de personas.
        hora: Etiqueta del antecedente de hora.
        salida: Etiqueta del consecuente (``"Muy bajo"``...``"Muy alto"``).
    """

    id: str
    consumo: str
    personas: str
    hora: str
    salida: str


# Tabla 8: (consumo, personas, salidas por hora en el orden Madrugada, Mañana, Tarde, Noche).
_TABLA_8: Final[tuple[tuple[str, str, tuple[str, str, str, str]], ...]] = (
    ("Bajo", "Pocas", ("M", "B", "B", "M")),
    ("Bajo", "Moderadas", ("B", "MB", "MB", "B")),
    ("Bajo", "Muchas", ("MB", "MB", "MB", "MB")),
    ("Medio", "Pocas", ("MA", "M", "A", "A")),
    ("Medio", "Moderadas", ("A", "B", "M", "M")),
    ("Medio", "Muchas", ("M", "MB", "B", "B")),
    ("Alto", "Pocas", ("MA", "MA", "MA", "MA")),
    ("Alto", "Moderadas", ("MA", "A", "A", "MA")),
    ("Alto", "Muchas", ("A", "M", "M", "A")),
)


def _construir_reglas() -> tuple[Regla, ...]:
    """Expande la Tabla 8 compacta a 36 reglas numeradas R1..R36."""
    reglas: list[Regla] = []
    for consumo, personas, salidas in _TABLA_8:
        for hora, abreviatura in zip(ORDEN_HORAS, salidas, strict=True):
            reglas.append(
                Regla(
                    id=f"R{len(reglas) + 1}",
                    consumo=consumo,
                    personas=personas,
                    hora=hora,
                    salida=ABREVIATURAS_SALIDA[abreviatura],
                )
            )
    return tuple(reglas)


def validar_reglas(reglas: Sequence[Regla]) -> None:
    """Valida la integridad de una base de reglas.

    Comprueba: exactamente 36 reglas, ids ``R1..R36`` únicos y consecutivos, las 36
    combinaciones de antecedentes presentes sin duplicados y etiquetas válidas.
    Esto garantiza que, para cualquier entrada, se active al menos una regla.

    Raises:
        ConfiguracionReglasError: Si alguna comprobación falla.
    """
    if len(reglas) != TOTAL_REGLAS:
        raise ConfiguracionReglasError(f"Se esperaban {TOTAL_REGLAS} reglas, hay {len(reglas)}")

    ids_esperados = [f"R{i}" for i in range(1, TOTAL_REGLAS + 1)]
    ids = [r.id for r in reglas]
    if len(set(ids)) != len(ids):
        raise ConfiguracionReglasError("Hay ids de regla duplicados")
    if ids != ids_esperados:
        raise ConfiguracionReglasError("Los ids deben ser consecutivos: R1..R36")

    for regla in reglas:
        for etiqueta, variable in (
            (regla.consumo, CONSUMO),
            (regla.personas, PERSONAS),
            (regla.hora, HORA),
            (regla.salida, SALIDA),
        ):
            if etiqueta not in variable.etiquetas:
                raise ConfiguracionReglasError(
                    f"{regla.id}: etiqueta {etiqueta!r} inválida para {variable.clave}"
                )

    combinaciones = [(r.consumo, r.personas, r.hora) for r in reglas]
    if len(set(combinaciones)) != len(combinaciones):
        raise ConfiguracionReglasError("Hay combinaciones de antecedentes duplicadas")
    esperadas = set(itertools.product(CONSUMO.etiquetas, PERSONAS.etiquetas, HORA.etiquetas))
    if set(combinaciones) != esperadas:
        raise ConfiguracionReglasError("Faltan combinaciones de antecedentes (base incompleta)")


def generar_reglas_heuristica() -> tuple[Regla, ...]:
    """Genera las 36 reglas con la heurística del grupo (solo para validación).

    Nivel base por consumo (Bajo 0, Medio 1,5, Alto 3) + ajuste por personas
    (Pocas +1, Moderadas 0, Muchas −1) + ajuste por hora (Madrugada +1,
    Noche +0,5, Tarde 0, Mañana −0,5); ``round(x) = ⌊x + 0,5⌋`` limitado a
    ``[0, 4]`` sobre la escala 0 = Muy bajo ... 4 = Muy alto.
    """
    base = {"Bajo": 0.0, "Medio": 1.5, "Alto": 3.0}
    ajuste_personas = {"Pocas": 1.0, "Moderadas": 0.0, "Muchas": -1.0}
    ajuste_hora = {"Madrugada": 1.0, "Noche": 0.5, "Tarde": 0.0, "Mañana": -0.5}

    reglas: list[Regla] = []
    for consumo, personas, _ in _TABLA_8:
        for hora in ORDEN_HORAS:
            valor = base[consumo] + ajuste_personas[personas] + ajuste_hora[hora]
            nivel = min(max(math.floor(valor + 0.5), 0), 4)
            reglas.append(
                Regla(
                    id=f"R{len(reglas) + 1}",
                    consumo=consumo,
                    personas=personas,
                    hora=hora,
                    salida=ESCALA_SALIDA[nivel],
                )
            )
    return tuple(reglas)


#: Base de reglas inmutable (Tabla 8).
REGLAS: Final[tuple[Regla, ...]] = _construir_reglas()

# Validación al importar: una base inconsistente impide arrancar el sistema.
validar_reglas(REGLAS)
