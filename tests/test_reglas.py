"""Pruebas de la base de reglas (Tabla 8) y de su validación."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pytest

from core.exceptions import ConfiguracionReglasError
from fuzzy.membresias import CONSUMO, HORA, PERSONAS, SALIDA
from fuzzy.reglas import REGLAS, generar_reglas_heuristica, validar_reglas


def test_hay_36_reglas_con_ids_consecutivos() -> None:
    assert len(REGLAS) == 36
    assert [r.id for r in REGLAS] == [f"R{i}" for i in range(1, 37)]
    assert len({r.id for r in REGLAS}) == 36


def test_combinaciones_de_antecedentes_completas_sin_duplicados() -> None:
    combinaciones = [(r.consumo, r.personas, r.hora) for r in REGLAS]
    assert len(set(combinaciones)) == 36
    assert len(CONSUMO.etiquetas) * len(PERSONAS.etiquetas) * len(HORA.etiquetas) == 36


def test_distribucion_de_salidas_7_7_8_7_7() -> None:
    conteo = Counter(r.salida for r in REGLAS)
    assert [conteo[e] for e in SALIDA.etiquetas] == [7, 7, 8, 7, 7]


def test_reglas_son_inmutables() -> None:
    assert isinstance(REGLAS, tuple)
    with pytest.raises(AttributeError):
        REGLAS[0].salida = "Alto"  # type: ignore[misc]


def test_heuristica_reproduce_exactamente_la_tabla() -> None:
    assert generar_reglas_heuristica() == REGLAS


@pytest.mark.parametrize(
    ("indice", "esperado"),
    [(0, "Medio"), (10, "Muy bajo"), (17, "Bajo"), (24, "Muy alto"), (35, "Alto")],
)
def test_reglas_puntuales_de_la_tabla(indice: int, esperado: str) -> None:
    assert REGLAS[indice].salida == esperado


def test_monotonia_a_nivel_de_etiquetas_de_regla() -> None:
    """Por franja horaria: la salida no baja al subir el consumo ni sube al subir las personas.

    Solo se prueba en las etiquetas; el centroide continuo NO es monótono.
    """
    nivel = {etiqueta: i for i, etiqueta in enumerate(SALIDA.etiquetas)}
    tabla = {(r.consumo, r.personas, r.hora): nivel[r.salida] for r in REGLAS}
    for hora in HORA.etiquetas:
        for personas in PERSONAS.etiquetas:
            niveles = [tabla[(c, personas, hora)] for c in CONSUMO.etiquetas]
            assert niveles == sorted(niveles), (hora, personas)
        for consumo in CONSUMO.etiquetas:
            niveles = [tabla[(consumo, p, hora)] for p in PERSONAS.etiquetas]
            assert niveles == sorted(niveles, reverse=True), (hora, consumo)


def test_validacion_rechaza_base_incompleta() -> None:
    with pytest.raises(ConfiguracionReglasError):
        validar_reglas(REGLAS[:-1])


def test_validacion_rechaza_combinacion_duplicada() -> None:
    mala = list(REGLAS)
    mala[1] = replace(
        mala[1], consumo=mala[0].consumo, personas=mala[0].personas, hora=mala[0].hora
    )
    with pytest.raises(ConfiguracionReglasError):
        validar_reglas(mala)


def test_validacion_rechaza_etiqueta_invalida() -> None:
    mala = list(REGLAS)
    mala[0] = replace(mala[0], salida="Altísimo")
    with pytest.raises(ConfiguracionReglasError):
        validar_reglas(mala)


def test_validacion_rechaza_ids_no_consecutivos() -> None:
    mala = list(REGLAS)
    mala[0], mala[1] = mala[1], mala[0]
    with pytest.raises(ConfiguracionReglasError):
        validar_reglas(mala)
