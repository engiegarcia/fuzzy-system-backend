"""Pruebas de la Tabla 11 (límites cerrados a la izquierda, abiertos a la derecha)."""

from __future__ import annotations

import pytest

from core.exceptions import EntradaFueraDeRangoError
from fuzzy.interpretacion import interpretar


@pytest.mark.parametrize(
    ("valor", "texto", "accion"),
    [
        (0, "Sin necesidad de ahorro", "Ninguna"),
        (19.99, "Sin necesidad de ahorro", "Ninguna"),
        (20, "Ahorro leve", "Recomendaciones de uso eficiente"),
        (39.99, "Ahorro leve", "Recomendaciones de uso eficiente"),
        (40, "Ahorro moderado", "Apagar equipos no esenciales"),
        (59.99, "Ahorro moderado", "Apagar equipos no esenciales"),
        (60, "Ahorro alto", "Reducir cargas de forma activa"),
        (79.99, "Ahorro alto", "Reducir cargas de forma activa"),
        (80, "Ahorro crítico", "Desconectar cargas no prioritarias"),
        (100, "Ahorro crítico", "Desconectar cargas no prioritarias"),
    ],
)
def test_bordes_de_la_tabla_11(valor: float, texto: str, accion: str) -> None:
    assert interpretar(valor) == (texto, accion)


@pytest.mark.parametrize("valor", [-0.01, 100.01, float("nan"), float("inf")])
def test_valores_invalidos(valor: float) -> None:
    with pytest.raises(EntradaFueraDeRangoError):
        interpretar(valor)
