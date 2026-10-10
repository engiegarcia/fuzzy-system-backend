"""Pruebas de universos, funciones de pertenencia y fuzzificación (Tablas 2-6)."""

from __future__ import annotations

import numpy as np
import pytest
import skfuzzy as fuzz

from core.exceptions import EntradaFueraDeRangoError
from fuzzy import membresias as m


@pytest.mark.parametrize(
    ("funcion", "x", "esperado"),
    [
        # Consumo: Bajo trap[0,0,500,1200], Medio tri[700,1500,2200], Alto trap[1800,2500,3000,3000]
        (m.fuzzificar_consumo, 0, {"bajo": 1.0, "medio": 0.0, "alto": 0.0}),
        (m.fuzzificar_consumo, 500, {"bajo": 1.0, "medio": 0.0, "alto": 0.0}),
        (m.fuzzificar_consumo, 850, {"bajo": 0.5, "medio": 0.1875, "alto": 0.0}),
        (m.fuzzificar_consumo, 1200, {"bajo": 0.0, "medio": 0.625, "alto": 0.0}),
        (m.fuzzificar_consumo, 1500, {"bajo": 0.0, "medio": 1.0, "alto": 0.0}),
        (m.fuzzificar_consumo, 2150, {"bajo": 0.0, "medio": 0.07142857142857142, "alto": 0.5}),
        (m.fuzzificar_consumo, 2500, {"bajo": 0.0, "medio": 0.0, "alto": 1.0}),
        (m.fuzzificar_consumo, 3000, {"bajo": 0.0, "medio": 0.0, "alto": 1.0}),
        # Personas: Pocas trap[0,0,1,2], Moderadas tri[1,3,5], Muchas trap[4,5,6,6]
        (m.fuzzificar_personas, 0, {"pocas": 1.0, "moderadas": 0.0, "muchas": 0.0}),
        (m.fuzzificar_personas, 1.5, {"pocas": 0.5, "moderadas": 0.25, "muchas": 0.0}),
        (m.fuzzificar_personas, 3, {"pocas": 0.0, "moderadas": 1.0, "muchas": 0.0}),
        (m.fuzzificar_personas, 4.5, {"pocas": 0.0, "moderadas": 0.25, "muchas": 0.5}),
        (m.fuzzificar_personas, 6, {"pocas": 0.0, "moderadas": 0.0, "muchas": 1.0}),
    ],
)
def test_fuzzificacion_puntos_clave(funcion, x, esperado) -> None:  # type: ignore[no-untyped-def]
    assert funcion(x) == pytest.approx(esperado, abs=1e-12)


@pytest.mark.parametrize(
    ("h", "madrugada", "manana", "tarde", "noche"),
    [
        (0, 1.0, 0.0, 0.0, 1.0),
        (1, 1.0, 0.0, 0.0, 0.5),
        (2, 1.0, 0.0, 0.0, 0.0),
        (4, 1.0, 0.0, 0.0, 0.0),
        (5.5, 0.5, 0.125, 0.0, 0.0),
        (7, 0.0, 0.5, 0.0, 0.0),
        (9, 0.0, 1.0, 0.0, 0.0),
        (12, 0.0, 0.25, 0.25, 0.0),
        (15, 0.0, 0.0, 1.0, 0.0),
        (19, 0.0, 0.0, 0.0, 0.5),
        (21, 0.0, 0.0, 0.0, 1.0),
        (23, 0.5, 0.0, 0.0, 1.0),
        (24, 1.0, 0.0, 0.0, 1.0),
    ],
)
def test_fuzzificacion_hora(h, madrugada, manana, tarde, noche) -> None:  # type: ignore[no-untyped-def]
    esperado = {"madrugada": madrugada, "manana": manana, "tarde": tarde, "noche": noche}
    assert m.fuzzificar_hora(h) == pytest.approx(esperado, abs=1e-12)


def test_hora_circular_0_y_24_identicas() -> None:
    assert m.fuzzificar_hora(0) == m.fuzzificar_hora(24)
    assert m.fuzzificar_hora(0) == {"madrugada": 1.0, "manana": 0.0, "tarde": 0.0, "noche": 1.0}


def test_casos_degenerados_en_los_extremos() -> None:
    x = np.array([0.0, 24.0])
    assert list(fuzz.trapmf(x, [22, 24, 24, 24])) == [0.0, 1.0]
    assert fuzz.trapmf(np.array([0.0]), [0, 0, 0, 2])[0] == 1.0
    assert fuzz.trapmf(np.array([0.0]), [0, 0, 500, 1200])[0] == 1.0
    assert fuzz.trapmf(np.array([100.0]), [75, 90, 100, 100])[0] == 1.0
    assert fuzz.trapmf(np.array([3000.0]), [1800, 2500, 3000, 3000])[0] == 1.0


def test_conjunto_noche_es_maximo_de_dos_trapecios() -> None:
    x = np.linspace(0, 24, 241)
    noche = m.HORA.conjunto("Noche").evaluar(x)
    esperado = np.fmax(fuzz.trapmf(x, [17, 21, 24, 24]), fuzz.trapmf(x, [0, 0, 0, 2]))
    np.testing.assert_array_equal(noche, esperado)


def test_grados_sin_redondear_caso_informe() -> None:
    assert m.fuzzificar_consumo(1900)["medio"] == pytest.approx(3 / 7, abs=1e-15)
    assert m.fuzzificar_consumo(1900)["alto"] == pytest.approx(1 / 7, abs=1e-15)


@pytest.mark.parametrize("variable", [m.CONSUMO, m.PERSONAS, m.HORA, m.SALIDA])
def test_cobertura_suma_positiva_en_todo_el_universo(variable: m.VariableDifusa) -> None:
    x = np.linspace(variable.minimo, variable.maximo, 5001)
    curvas = variable.curvas(x)
    total = sum(curvas.values())
    assert np.all(total > 0)


def test_funciones_salida_precalculadas_y_de_solo_lectura() -> None:
    salida = m.funciones_salida(0.01)
    assert salida is m.funciones_salida(0.01)  # cacheada: se calcula una sola vez
    assert salida.universo.size == 10001
    assert not salida.universo.flags.writeable
    for curva in salida.funciones.values():
        assert not curva.flags.writeable
        with pytest.raises(ValueError):
            curva[0] = 0.5


def test_centroides_propios_de_los_conjuntos_extremos() -> None:
    salida = m.funciones_salida(0.01)
    muy_bajo = fuzz.defuzz(salida.universo, salida.funciones["muy_bajo"], "centroid")
    muy_alto = fuzz.defuzz(salida.universo, salida.funciones["muy_alto"], "centroid")
    assert muy_bajo == pytest.approx(9.3, abs=0.05)
    assert muy_alto == pytest.approx(90.7, abs=0.05)


@pytest.mark.parametrize(
    ("funcion", "valor"),
    [
        (m.fuzzificar_consumo, -0.01),
        (m.fuzzificar_consumo, 3000.01),
        (m.fuzzificar_personas, 6.5),
        (m.fuzzificar_hora, 24.5),
        (m.fuzzificar_hora, float("nan")),
        (m.fuzzificar_hora, float("inf")),
    ],
)
def test_fuera_de_rango_no_se_recorta(funcion, valor) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(EntradaFueraDeRangoError):
        funcion(valor)


@pytest.mark.parametrize("paso", [0, -1, 1.5, float("nan")])
def test_paso_de_salida_invalido(paso: float) -> None:
    with pytest.raises(EntradaFueraDeRangoError):
        m.funciones_salida(paso)
