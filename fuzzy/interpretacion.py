"""Interpretación de la salida defuzzificada (Tabla 11 del informe)."""

from __future__ import annotations

import math
from bisect import bisect_right
from typing import Final

from core.exceptions import EntradaFueraDeRangoError

# Límites inferiores abiertos por la derecha: [0,20) [20,40) [40,60) [60,80) [80,100].
_LIMITES: Final[tuple[float, ...]] = (20.0, 40.0, 60.0, 80.0)

_NIVELES: Final[tuple[tuple[str, str], ...]] = (
    ("Sin necesidad de ahorro", "Ninguna"),
    ("Ahorro leve", "Recomendaciones de uso eficiente"),
    ("Ahorro moderado", "Apagar equipos no esenciales"),
    ("Ahorro alto", "Reducir cargas de forma activa"),
    ("Ahorro crítico", "Desconectar cargas no prioritarias"),
)


def interpretar(salida_pct: float) -> tuple[str, str]:
    """Traduce el nivel de ahorro (%) a ``(interpretación, acción sugerida)``.

    Semántica de intervalos: cerrados por la izquierda y abiertos por la derecha,
    salvo el último: ``[0,20)``, ``[20,40)``, ``[40,60)``, ``[60,80)``, ``[80,100]``.
    La clasificación usa el valor exacto (sin redondear).

    Raises:
        EntradaFueraDeRangoError: Si el valor no es finito o queda fuera de ``[0, 100]``.
    """
    if not math.isfinite(salida_pct) or not 0.0 <= salida_pct <= 100.0:
        raise EntradaFueraDeRangoError(f"salida_pct fuera de [0, 100]: {salida_pct}")
    return _NIVELES[bisect_right(_LIMITES, salida_pct)]
