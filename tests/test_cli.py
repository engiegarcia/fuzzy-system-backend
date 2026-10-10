"""Pruebas de la CLI (modos directo, lote, interactivo, errores y figuras)."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

import cli

RAIZ = Path(__file__).resolve().parent.parent
CASOS_CSV = RAIZ / "data" / "casos_informe.csv"


def test_modo_directo_tabla(capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cli.main(["--consumo", "1900", "--personas", "3", "--hora", "12"])
    salida = capsys.readouterr().out
    assert codigo == 0
    assert "46,72" in salida
    assert "Ahorro moderado" in salida


def test_modo_directo_json(capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cli.main(
        ["--consumo", "1900", "--personas", "3", "--hora", "12", "--formato", "json", "--id", "x"]
    )
    datos = json.loads(capsys.readouterr().out)
    assert codigo == 0
    assert datos["id_evaluacion"] == "x"
    assert datos["salida_pct"] == pytest.approx(46.72, abs=0.05)
    assert [r["regla"] for r in datos["reglas_activadas"]] == ["R18", "R19", "R30", "R31"]


def test_hora_hh_mm_equivale_a_decimal(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["--consumo", "1900", "--personas", "3", "--hora", "14:30", "--formato", "json"])
    con_hhmm = json.loads(capsys.readouterr().out)
    cli.main(["--consumo", "1900", "--personas", "3", "--hora", "14.5", "--formato", "json"])
    con_decimal = json.loads(capsys.readouterr().out)
    assert con_hhmm["entradas"]["hora"] == 14.5
    assert con_hhmm["salida_pct"] == con_decimal["salida_pct"]


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("14:30", 14.5), ("0:00", 0.0), ("24:00", 24.0), ("7.25", 7.25), ("7,25", 7.25)],
)
def test_parsear_hora(texto: str, esperado: float) -> None:
    assert cli.parsear_hora(texto) == pytest.approx(esperado)


@pytest.mark.parametrize("texto", ["12:60", "abc", "12:5:3", ""])
def test_parsear_hora_invalida(texto: str) -> None:
    with pytest.raises(ValueError):
        cli.parsear_hora(texto)


def test_detalle_muestra_pasos_y_centroide(capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cli.main(["--consumo", "1900", "--personas", "3", "--hora", "12", "--detalle"])
    salida = capsys.readouterr().out
    assert codigo == 0
    for fragmento in ("Fuzzificación", "R18", "R31", "0,1429", "y* = 46,72 %"):
        assert fragmento in salida


def test_modo_lote_contra_casos_del_informe(capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cli.main(["--csv", str(CASOS_CSV), "--formato", "json"])
    datos = json.loads(capsys.readouterr().out)
    assert codigo == 0
    assert len(datos) == 4
    assert [d["id_evaluacion"] for d in datos] == ["caso-1", "caso-2", "caso-3", "caso-4"]
    assert [d["salida_pct"] for d in datos] == pytest.approx([9.28, 22.54, 46.72, 90.72], abs=0.05)


def test_modo_lote_con_salida_csv(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    destino = tmp_path / "res" / "resultados.csv"
    codigo = cli.main(["--csv", str(CASOS_CSV), "--salida", str(destino)])
    assert codigo == 0
    assert "4 resultados" in capsys.readouterr().out
    with destino.open(newline="", encoding="utf-8") as archivo:
        filas = list(csv.DictReader(archivo))
    assert len(filas) == 4
    assert float(filas[2]["salida_pct"]) == pytest.approx(46.72, abs=0.05)
    assert filas[3]["interpretacion"] == "Ahorro crítico"


def test_modo_lote_con_detalle(capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cli.main(["--csv", str(CASOS_CSV), "--detalle"])
    salida = capsys.readouterr().out
    assert codigo == 0
    assert salida.count("═══ Evaluación") == 4
    assert "y* = 46,72 %" in salida


def test_csv_con_fila_invalida_no_evalua_nada(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entrada = tmp_path / "malo.csv"
    entrada.write_text("id,consumo_w,personas,hora\na,100,1,5\nb,9999,1,5\nc,100,1,xx\n")
    codigo = cli.main(["--csv", str(entrada)])
    captura = capsys.readouterr()
    assert codigo != 0
    assert captura.out == ""
    assert "Línea 3" in captura.err
    assert "Línea 4" in captura.err
    assert "Traceback" not in captura.err


def test_csv_inexistente_o_sin_columnas(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--csv", str(tmp_path / "no_existe.csv")]) != 0
    sin_columnas = tmp_path / "x.csv"
    sin_columnas.write_text("id,consumo_w\na,100\n")
    assert cli.main(["--csv", str(sin_columnas)]) != 0
    assert "Faltan columnas" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argumentos",
    [
        ["--consumo", "-5", "--personas", "3", "--hora", "12"],
        ["--consumo", "3001", "--personas", "3", "--hora", "12"],
        ["--consumo", "100", "--personas", "7", "--hora", "12"],
        ["--consumo", "100", "--personas", "3", "--hora", "24.5"],
        ["--consumo", "100", "--personas", "3", "--hora", "nan"],
        ["--consumo", "100", "--personas", "3"],
        ["--consumo", "abc", "--personas", "3", "--hora", "12"],
        ["--detalle"],
    ],
)
def test_entrada_invalida_devuelve_codigo_distinto_de_cero(
    argumentos: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(argumentos) != 0
    assert "Traceback" not in capsys.readouterr().err


def test_entrada_invalida_via_subprocess() -> None:
    proceso = subprocess.run(
        [sys.executable, "cli.py", "--consumo", "-5", "--personas", "3", "--hora", "12"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proceso.returncode != 0
    assert "Traceback" not in proceso.stderr
    assert "consumo_w" in proceso.stderr


def test_directo_via_subprocess() -> None:
    proceso = subprocess.run(
        [sys.executable, "cli.py", "--consumo", "1900", "--personas", "3", "--hora", "12"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proceso.returncode == 0
    assert "46,72" in proceso.stdout


def test_barrido(capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cli.main(
        [
            "--barrido", "hora", "--desde", "0", "--hasta", "24", "--pasos", "3",
            "--consumo", "1900", "--personas", "3", "--formato", "json",
        ]  # fmt: skip
    )
    puntos = json.loads(capsys.readouterr().out)["puntos"]
    assert codigo == 0
    assert [p["valor"] for p in puntos] == [0.0, 12.0, 24.0]
    assert puntos[0]["salida_pct"] == puntos[2]["salida_pct"]


def test_barrido_sin_valores_fijos_falla(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--barrido", "hora", "--desde", "0", "--hasta", "24"]) != 0
    assert "Falta el valor fijo" in capsys.readouterr().err


def test_figuras_informe_crea_los_4_png(tmp_path: Path) -> None:
    destino = tmp_path / "figs"
    assert cli.main(["--figuras-informe", str(destino)]) == 0
    for numero in range(1, 5):
        archivo = destino / f"figura_{numero}.png"
        assert archivo.is_file() and archivo.stat().st_size > 0
        assert archivo.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_grafico_guarda_figura_4(tmp_path: Path) -> None:
    ruta = tmp_path / "agregacion.png"
    codigo = cli.main(
        ["--consumo", "1900", "--personas", "3", "--hora", "12", "--grafico", str(ruta)]
    )
    assert codigo == 0
    assert ruta.read_bytes()[:4] == b"\x89PNG"


def test_modo_interactivo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    respuestas = iter(["1900", "3", "12:00", "5000", "3", "12", "abc", "q"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(respuestas))
    codigo = cli.main([])
    salida = capsys.readouterr().out
    assert codigo == 0
    assert "46,72" in salida  # primera evaluación válida
    assert "Entrada inválida" in salida  # 5000 W rechazado sin cerrar el bucle
    assert "no es un número válido" in salida  # 'abc' vuelve a pedir
