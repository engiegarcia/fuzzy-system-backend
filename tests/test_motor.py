"""Pruebas del motor Mamdani: casos de referencia, pureza y concurrencia."""

from __future__ import annotations

import itertools
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
import skfuzzy as fuzz

from core.exceptions import DefuzzificacionError, EntradaFueraDeRangoError
from fuzzy import motor
from fuzzy.membresias import SALIDA, funciones_salida
from fuzzy.motor import evaluar

CASOS_REFERENCIA = [
    # (consumo, personas, hora, salida esperada, interpretación, reglas activas)
    (300, 5, 15, 9.28, "Sin necesidad de ahorro", {"R11"}),
    (1000, 4, 8, 22.54, "Ahorro leve", {"R6", "R18"}),
    (1900, 3, 12, 46.72, "Ahorro moderado", {"R18", "R19", "R30", "R31"}),
    (2800, 1, 2, 90.72, "Ahorro crítico", {"R25"}),
    (2500, 6, 19, 70.00, "Ahorro alto", {"R36"}),
    (100, 0, 3, 50.00, "Ahorro moderado", {"R1"}),
    (1900, 3, 24, 63.52, "Ahorro alto", {"R17", "R20", "R29", "R32"}),
    (1900, 3, 0, 63.52, "Ahorro alto", {"R17", "R20", "R29", "R32"}),
]


@pytest.mark.parametrize(
    ("consumo", "personas", "hora", "esperado", "interpretacion", "reglas"), CASOS_REFERENCIA
)
def test_casos_de_referencia(consumo, personas, hora, esperado, interpretacion, reglas) -> None:  # type: ignore[no-untyped-def]
    resultado = evaluar(consumo, personas, hora)
    assert resultado.salida_pct == pytest.approx(esperado, abs=0.05)
    assert resultado.interpretacion == interpretacion
    assert {r.regla for r in resultado.reglas_activadas} == reglas


def test_caso_3_activacion_exacta_de_reglas() -> None:
    resultado = evaluar(1900, 3, 12)
    alphas = {r.regla: r.alpha for r in resultado.reglas_activadas}
    assert alphas == {
        "R18": pytest.approx(0.25, abs=1e-12),
        "R19": pytest.approx(0.25, abs=1e-12),
        "R30": pytest.approx(1 / 7, abs=1e-12),
        "R31": pytest.approx(1 / 7, abs=1e-12),
    }
    assert resultado.fuzzificacion["consumo"] == pytest.approx(
        {"bajo": 0.0, "medio": 3 / 7, "alto": 1 / 7}, abs=1e-12
    )
    primera = resultado.reglas_activadas[0]
    assert (primera.consumo, primera.personas, primera.hora, primera.salida) == (
        "Medio",
        "Moderadas",
        "Mañana",
        "Bajo",
    )
    assert primera.calculo == "mín(0,4286; 1,0000; 0,2500)"


def test_caso_7_alphas() -> None:
    alphas = {r.regla: r.alpha for r in evaluar(1900, 3, 24).reglas_activadas}
    assert alphas["R17"] == pytest.approx(3 / 7)
    assert alphas["R20"] == pytest.approx(3 / 7)
    assert alphas["R29"] == pytest.approx(1 / 7)
    assert alphas["R32"] == pytest.approx(1 / 7)


def test_resultado_incluye_fuzzificacion_con_ceros_y_arreglos() -> None:
    resultado = evaluar(1900, 3, 12)
    assert resultado.fuzzificacion["hora"]["madrugada"] == 0.0
    assert set(resultado.fuzzificacion) == {"consumo", "personas", "hora"}
    assert resultado.universo.shape == resultado.agregado.shape == (10001,)
    assert not resultado.agregado.flags.writeable


def test_salida_no_se_redondea_en_el_motor() -> None:
    assert evaluar(1900, 3, 12).salida_pct != round(evaluar(1900, 3, 12).salida_pct, 2)


def test_salida_dentro_de_los_centroides_extremos_en_malla_aleatoria() -> None:
    rng = np.random.default_rng(12345)
    consumos = np.append(rng.uniform(0, 3000, 100), [0, 3000])
    personas = np.append(rng.uniform(0, 6, 100), [0, 6])
    horas = np.append(rng.uniform(0, 24, 100), [0, 24])
    for c, p, h in zip(consumos, personas, horas, strict=True):
        salida = evaluar(float(c), float(p), float(h)).salida_pct
        assert 9.0 <= salida <= 91.0, (c, p, h, salida)


def test_hora_0_y_24_equivalentes() -> None:
    for consumo, personas in itertools.product((0, 700, 1900, 3000), (0, 2.5, 6)):
        a = evaluar(consumo, personas, 0)
        b = evaluar(consumo, personas, 24)
        assert a.salida_pct == b.salida_pct
        assert a.fuzzificacion["hora"] == b.fuzzificacion["hora"]
        assert [r.regla for r in a.reglas_activadas] == [r.regla for r in b.reglas_activadas]


def test_llamadas_repetidas_y_orden_no_afectan() -> None:
    entradas = [(c, p, h) for c, p, h, *_ in CASOS_REFERENCIA]
    primera = [evaluar(*e).salida_pct for e in entradas]
    segunda = [evaluar(*e).salida_pct for e in entradas]
    invertida = [evaluar(*e).salida_pct for e in reversed(entradas)][::-1]
    assert primera == segunda == invertida


def test_hebras_en_paralelo_igual_que_secuencial() -> None:
    rng = np.random.default_rng(7)
    entradas = [
        (float(c), float(p), float(h))
        for c, p, h in zip(
            rng.uniform(0, 3000, 40), rng.uniform(0, 6, 40), rng.uniform(0, 24, 40), strict=True
        )
    ]
    secuencial = [evaluar(*e).salida_pct for e in entradas]
    with ThreadPoolExecutor(max_workers=8) as pool:
        paralelo = list(pool.map(lambda e: evaluar(*e).salida_pct, entradas * 2))
    assert paralelo == secuencial * 2


def test_alpha_exacto_difiere_del_alpha_redondeado() -> None:
    """Con 1/7 → 46,72 %; con 0,14 sería 46,62 %: nunca se redondea antes de defuzzificar."""
    exacto = evaluar(1900, 3, 12)
    salida = funciones_salida(0.01)
    agregado = np.zeros_like(salida.universo)
    for regla in exacto.reglas_activadas:
        alpha = round(regla.alpha, 2)
        recorte = np.minimum(alpha, SALIDA.conjunto(regla.salida).evaluar(salida.universo))
        agregado = np.maximum(agregado, recorte)
    redondeado = fuzz.defuzz(salida.universo, agregado, "centroid")
    assert exacto.salida_pct == pytest.approx(46.72, abs=0.05)
    assert redondeado == pytest.approx(46.62, abs=0.05)
    assert abs(exacto.salida_pct - redondeado) > 0.05


def test_distinto_paso_de_salida_da_resultado_cercano() -> None:
    assert evaluar(1900, 3, 12, paso_salida=0.1).salida_pct == pytest.approx(46.72, abs=0.05)


@pytest.mark.parametrize(
    "entrada", [(-1, 3, 12), (3001, 3, 12), (100, 7, 12), (100, 3, 24.5), (float("nan"), 3, 12)]
)
def test_entradas_invalidas_lanzan_error_de_dominio(entrada) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(EntradaFueraDeRangoError):
        evaluar(*entrada)


def test_area_nula_lanza_defuzzificacion_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensa: si ninguna regla se activara no se divide por cero."""
    monkeypatch.setattr(motor, "_REGLAS_INDEXADAS", ())
    with pytest.raises(DefuzzificacionError):
        evaluar(1900, 3, 12)


def test_hay_siempre_al_menos_una_regla_activa() -> None:
    malla = itertools.product((0, 1200, 1500, 1900, 3000), (0, 2, 3, 6), (0, 6, 12, 18, 24))
    for c, p, h in malla:
        assert evaluar(c, p, h).reglas_activadas, (c, p, h)
