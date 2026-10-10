"""Pruebas de la API REST."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.config import get_settings
from core.exceptions import DefuzzificacionError

PNG = b"\x89PNG\r\n\x1a\n"
VALIDO = {"consumo_w": 1900, "personas": 3, "hora": 12}


def test_evaluar_caso_del_informe(client: TestClient) -> None:
    r = client.post("/api/evaluar", json={"id_evaluacion": "caso-informe-3", **VALIDO})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["id_evaluacion"] == "caso-informe-3"
    assert cuerpo["entradas"] == {"consumo_w": 1900.0, "personas": 3.0, "hora": 12.0}
    assert cuerpo["salida_pct"] == pytest.approx(46.72, abs=0.05)
    assert cuerpo["interpretacion"] == "Ahorro moderado"
    assert cuerpo["accion_sugerida"] == "Apagar equipos no esenciales"
    assert cuerpo["fuzzificacion"] == {
        "consumo": {"bajo": 0.0, "medio": 0.4286, "alto": 0.1429},
        "personas": {"pocas": 0.0, "moderadas": 1.0, "muchas": 0.0},
        "hora": {"madrugada": 0.0, "manana": 0.25, "tarde": 0.25, "noche": 0.0},
    }
    reglas = cuerpo["reglas_activadas"]
    assert [(x["regla"], x["salida"], x["alpha"]) for x in reglas] == [
        ("R18", "Bajo", 0.25),
        ("R19", "Medio", 0.25),
        ("R30", "Alto", 0.1429),
        ("R31", "Alto", 0.1429),
    ]
    assert "universo" not in cuerpo and "agregado" not in cuerpo


def test_evaluar_redondea_solo_en_la_presentacion(client: TestClient) -> None:
    assert client.post("/api/evaluar", json=VALIDO).json()["salida_pct"] == 46.72


@pytest.mark.parametrize(
    "cuerpo",
    [
        {**VALIDO, "consumo_w": -1},
        {**VALIDO, "consumo_w": 3001},
        {**VALIDO, "personas": 7},
        {**VALIDO, "hora": 24.5},
        {"personas": 3, "hora": 12},
        {"consumo_w": 1900, "hora": 12},
        {"consumo_w": 1900, "personas": 3},
        {**VALIDO, "consumo_w": "abc"},
        {},
    ],
)
def test_evaluar_422(client: TestClient, cuerpo: dict) -> None:  # type: ignore[type-arg]
    r = client.post("/api/evaluar", json=cuerpo)
    assert r.status_code == 422
    assert r.json()["error_code"] == "VALIDATION_ERROR"
    assert r.json()["detail"]


@pytest.mark.parametrize("valor", ["NaN", "Infinity", "-Infinity"])
def test_evaluar_rechaza_nan_e_inf(client: TestClient, valor: str) -> None:
    contenido = f'{{"consumo_w": {valor}, "personas": 3, "hora": 12}}'.encode()
    r = client.post("/api/evaluar", content=contenido, headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert "finito" in r.json()["detail"]


def test_lote_valido(client: TestClient) -> None:
    cuerpo = {
        "evaluaciones": [
            {"id_evaluacion": "a", "consumo_w": 300, "personas": 5, "hora": 15},
            {"id_evaluacion": "b", **VALIDO},
        ]
    }
    r = client.post("/api/evaluar/lote", json=cuerpo)
    assert r.status_code == 200
    datos = r.json()
    assert datos["total"] == 2
    assert [x["id_evaluacion"] for x in datos["resultados"]] == ["a", "b"]
    assert datos["resultados"][0]["salida_pct"] == pytest.approx(9.28, abs=0.05)
    assert datos["resultados"][1]["salida_pct"] == pytest.approx(46.72, abs=0.05)


def test_lote_vacio_422(client: TestClient) -> None:
    assert client.post("/api/evaluar/lote", json={"evaluaciones": []}).status_code == 422


def test_lote_supera_max_lote_422(client: TestClient) -> None:
    exceso = [VALIDO] * (get_settings().max_lote + 1)
    r = client.post("/api/evaluar/lote", json={"evaluaciones": exceso})
    assert r.status_code == 422


def test_lote_item_invalido_422_con_indice(client: TestClient) -> None:
    cuerpo = {"evaluaciones": [VALIDO, VALIDO, {**VALIDO, "hora": 99}, VALIDO]}
    r = client.post("/api/evaluar/lote", json=cuerpo)
    assert r.status_code == 422
    assert "evaluaciones[2].hora" in r.json()["detail"]
    assert r.json()["errors"][0]["campo"] == "evaluaciones[2].hora"


def test_barrido_hora_circular(client: TestClient) -> None:
    cuerpo = {
        "variable": "hora",
        "desde": 0,
        "hasta": 24,
        "pasos": 5,
        "consumo_w": 1900,
        "personas": 3,
    }
    r = client.post("/api/barrido", json=cuerpo)
    assert r.status_code == 200
    puntos = r.json()["puntos"]
    assert r.json()["variable"] == "hora"
    assert [p["valor"] for p in puntos] == [0.0, 6.0, 12.0, 18.0, 24.0]
    assert puntos[0]["salida_pct"] == puntos[-1]["salida_pct"] == pytest.approx(63.52, abs=0.05)
    assert puntos[2]["salida_pct"] == pytest.approx(46.72, abs=0.05)


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"variable": "hora", "desde": 0, "hasta": 24, "pasos": 1, "consumo_w": 1, "personas": 1},
        {"variable": "hora", "desde": 0, "hasta": 24, "pasos": 501, "consumo_w": 1, "personas": 1},
        {"variable": "hora", "desde": 0, "hasta": 30, "pasos": 5, "consumo_w": 1, "personas": 1},
        {"variable": "hora", "desde": 10, "hasta": 5, "pasos": 5, "consumo_w": 1, "personas": 1},
        {"variable": "hora", "desde": 0, "hasta": 24, "pasos": 5, "consumo_w": 1},
        {"variable": "otra", "desde": 0, "hasta": 24, "pasos": 5},
    ],
)
def test_barrido_422(client: TestClient, cuerpo: dict) -> None:  # type: ignore[type-arg]
    assert client.post("/api/barrido", json=cuerpo).status_code == 422


def test_reglas_devuelve_exactamente_36(client: TestClient) -> None:
    r = client.get("/api/reglas")
    assert r.status_code == 200
    reglas = r.json()
    assert len(reglas) == 36
    assert reglas[0] == {
        "id": "R1",
        "consumo": "Bajo",
        "personas": "Pocas",
        "hora": "Madrugada",
        "salida": "Medio",
    }


def test_membresias(client: TestClient) -> None:
    r = client.get("/api/membresias")
    assert r.status_code == 200
    variables = r.json()["variables"]
    assert set(variables) == {"consumo", "personas", "hora", "salida"}
    hora = variables["hora"]
    assert set(hora["conjuntos"]) == {"madrugada", "manana", "tarde", "noche"}
    assert hora["x"][0] == 0.0 and hora["x"][-1] == 24.0
    assert hora["conjuntos"]["madrugada"][0] == hora["conjuntos"]["madrugada"][-1] == 1.0
    assert hora["conjuntos"]["noche"][0] == hora["conjuntos"]["noche"][-1] == 1.0
    assert all(len(c) == len(hora["x"]) for c in hora["conjuntos"].values())


def test_grafico_agregacion_png(client: TestClient) -> None:
    r = client.get("/api/grafico/agregacion", params=VALIDO)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == PNG


def test_grafico_agregacion_valida_entrada(client: TestClient) -> None:
    r = client.get("/api/grafico/agregacion", params={**VALIDO, "hora": 30})
    assert r.status_code == 422


@pytest.mark.parametrize("n", [1, 2, 3])
def test_grafico_membresias_png(client: TestClient, n: int) -> None:
    r = client.get(f"/api/grafico/membresias/{n}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == PNG


@pytest.mark.parametrize("n", [0, 4, 99])
def test_grafico_membresias_404(client: TestClient, n: int) -> None:
    r = client.get(f"/api/grafico/membresias/{n}")
    assert r.status_code == 404
    assert r.json()["error_code"] == "FIGURA_NO_ENCONTRADA"


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_degradado_devuelve_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client.app.state.servicio, "health_check", lambda: False)
    assert client.get("/health").status_code == 503


def test_error_inesperado_del_motor_devuelve_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def falla(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("fallo simulado de NumPy")

    monkeypatch.setattr("fuzzy.motor.evaluar", falla)
    r = client.post("/api/evaluar", json=VALIDO)
    assert r.status_code == 500
    cuerpo = r.json()
    assert cuerpo["error_code"] == "MOTOR_DIFUSO_ERROR"
    assert "fallo simulado" in cuerpo["detail"]
    assert "1900" in cuerpo["detail"]  # contexto de la entrada que falló


def test_error_de_dominio_del_motor_devuelve_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def falla(*_args: object, **_kwargs: object) -> None:
        raise DefuzzificacionError("área nula")

    monkeypatch.setattr("fuzzy.motor.evaluar", falla)
    r = client.post("/api/evaluar", json=VALIDO)
    assert r.status_code == 500
    assert r.json()["error_code"] == "DEFUZZIFICACION_ERROR"


def test_cors_usa_origenes_configurados(client: TestClient) -> None:
    permitido = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert permitido.headers.get("access-control-allow-origin") == "http://localhost:3000"
    ajeno = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in ajeno.headers


def test_openapi_documenta_422_y_500(client: TestClient) -> None:
    ruta = client.get("/openapi.json").json()["paths"]["/api/evaluar"]["post"]["responses"]
    assert {"200", "422", "500"} <= set(ruta)
