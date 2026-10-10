"""CLI de uso general del sistema difuso (reutiliza ``DifusoService`` y los esquemas de la API).

Modos:
    Directo      ``python cli.py --consumo 1900 --personas 3 --hora 12``
    Interactivo  ``python cli.py`` (sin argumentos; pide valores hasta ``q``)
    Lote         ``python cli.py --csv entradas.csv --salida resultados.csv``

Decisión: se usa ``argparse`` (biblioteca estándar) en lugar de ``typer`` para no
añadir dependencias al conjunto fijado en ``requirements.txt``.

Códigos de salida: ``0`` éxito · ``1`` error del motor/inesperado · ``2`` error de
uso o de validación de entradas. Nunca se muestra un traceback crudo al usuario
(use ``--verbose`` para ver el detalle en el log).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.exceptions import MotorDifusoError
from core.logging_config import configure_logging
from fuzzy import graficos
from fuzzy.membresias import VARIABLES
from schemas.difuso import (
    BarridoRequest,
    BarridoResponse,
    EvaluacionRequest,
    EvaluacionResponse,
)
from services.difuso_service import DifusoService

logger = logging.getLogger("cli")

_VARIABLES_BARRIDO = {"consumo": "consumo_w", "personas": "personas", "hora": "hora"}
_COLUMNAS_CSV = ("id", "consumo_w", "personas", "hora")
_COLUMNAS_RESULTADO = (
    "id",
    "consumo_w",
    "personas",
    "hora",
    "salida_pct",
    "interpretacion",
    "accion_sugerida",
)
_PATRON_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_SALIR = {"q", "quit", "salir", "exit"}

# clave técnica → etiqueta legible, por variable (para el modo --detalle).
_ETIQUETAS = {
    clave: {c.clave: c.etiqueta for c in variable.conjuntos}
    for clave, variable in VARIABLES.items()
}


class ErrorCLI(Exception):
    """Error de uso o de datos de entrada (código de salida 2)."""


# --------------------------------------------------------------------------- #
# Parseo de números y horas
# --------------------------------------------------------------------------- #
def parsear_numero(texto: str) -> float:
    """Convierte ``"1900"``, ``"14.5"`` o ``"14,5"`` a ``float``.

    Raises:
        ValueError: Si el texto no es numérico.
    """
    try:
        return float(texto.strip().replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"'{texto}' no es un número válido") from exc


def parsear_hora(texto: str) -> float:
    """Acepta hora decimal (``14.5``) o ``HH:MM`` (``14:30``) y devuelve horas decimales.

    Raises:
        ValueError: Si el formato es inválido o los minutos no están en 0–59.
    """
    limpio = texto.strip()
    coincidencia = _PATRON_HHMM.match(limpio)
    if coincidencia:
        horas, minutos = int(coincidencia.group(1)), int(coincidencia.group(2))
        if minutos > 59:
            raise ValueError(f"'{texto}': los minutos deben estar entre 00 y 59")
        return horas + minutos / 60
    try:
        return parsear_numero(limpio)
    except ValueError as exc:
        raise ValueError(f"'{texto}' no es una hora válida (use 14.5 o 14:30)") from exc


def formatear_hora(hora: float) -> str:
    """Hora decimal → ``HH:MM`` (14.5 → ``"14:30"``)."""
    minutos_totales = round(hora * 60)
    return f"{minutos_totales // 60:02d}:{minutos_totales % 60:02d}"


def _tipo_numero(texto: str) -> float:
    try:
        return parsear_numero(texto)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _tipo_hora(texto: str) -> float:
    try:
        return parsear_hora(texto)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


# --------------------------------------------------------------------------- #
# Presentación
# --------------------------------------------------------------------------- #
def _coma(valor: float, decimales: int = 2) -> str:
    return f"{valor:.{decimales}f}".replace(".", ",")


def _num(valor: float) -> str:
    return f"{valor:g}".replace(".", ",")


def _id_visible(resp: EvaluacionResponse, indice: int) -> str:
    return resp.id_evaluacion or str(indice + 1)


def _alinear(filas: Sequence[Sequence[str]]) -> list[str]:
    """Alinea columnas con relleno a la derecha."""
    anchos = [max(len(fila[i]) for fila in filas) for i in range(len(filas[0]))]
    return ["  ".join(c.ljust(anchos[i]) for i, c in enumerate(fila)).rstrip() for fila in filas]


def render_tabla(respuestas: Sequence[EvaluacionResponse]) -> str:
    """Tabla de texto con una fila por evaluación (coma decimal)."""
    filas: list[list[str]] = [
        ["id", "Consumo (W)", "Personas", "Hora", "Salida (%)", "Interpretación", "Acción sugerida"]
    ]
    for i, r in enumerate(respuestas):
        filas.append(
            [
                _id_visible(r, i),
                _num(r.entradas.consumo_w),
                _num(r.entradas.personas),
                formatear_hora(r.entradas.hora),
                _coma(r.salida_pct),
                r.interpretacion,
                r.accion_sugerida,
            ]
        )
    return "\n".join(_alinear(filas))


def render_detalle(resp: EvaluacionResponse, indice: int = 0) -> str:
    """Paso a paso (formato Tabla 9): fuzzificación, reglas activadas, α y centroide."""
    e = resp.entradas
    lineas = [
        f"═══ Evaluación {_id_visible(resp, indice)} ═══",
        f"Entradas: Consumo = {_num(e.consumo_w)} W · Personas = {_num(e.personas)} · "
        f"Hora = {formatear_hora(e.hora)} ({_num(e.hora)} h)",
        "",
        "1. Fuzzificación (grados de pertenencia)",
    ]
    for variable, nombre in (("consumo", "Consumo"), ("personas", "Personas"), ("hora", "Hora")):
        grados = " | ".join(
            f"{_ETIQUETAS[variable][clave]} = {_coma(mu, 4)}"
            for clave, mu in resp.fuzzificacion[variable].items()
        )
        lineas.append(f"   {nombre:<9}: {grados}")

    lineas += ["", "2. Reglas activadas (α = mín de los antecedentes)"]
    if resp.reglas_activadas:
        filas = [["Regla", "Consumo", "Personas", "Hora", "Salida", "α", "Cálculo"]]
        for r in resp.reglas_activadas:
            filas.append(
                [r.regla, r.consumo, r.personas, r.hora, r.salida, _coma(r.alpha, 4), r.calculo]
            )
        lineas += [f"   {linea}" for linea in _alinear(filas)]
    else:
        lineas.append("   (ninguna)")

    lineas += [
        "",
        "3. Implicación (MIN) y agregación (MAX) de los conjuntos de salida",
        "4. Defuzzificación por centroide",
        f"   y* = {_coma(resp.salida_pct)} %",
        "",
        f"Interpretación: {resp.interpretacion} → {resp.accion_sugerida}",
    ]
    return "\n".join(lineas)


def render_csv(respuestas: Sequence[EvaluacionResponse]) -> str:
    """CSV de resultados (punto decimal)."""
    buffer = io.StringIO()
    escritor = csv.writer(buffer, lineterminator="\n")
    escritor.writerow(_COLUMNAS_RESULTADO)
    for i, r in enumerate(respuestas):
        escritor.writerow(
            [
                _id_visible(r, i),
                r.entradas.consumo_w,
                r.entradas.personas,
                r.entradas.hora,
                f"{r.salida_pct:.2f}",
                r.interpretacion,
                r.accion_sugerida,
            ]
        )
    return buffer.getvalue()


def render_json(respuestas: Sequence[EvaluacionResponse], lote: bool) -> str:
    """JSON: un objeto para una evaluación, una lista para un lote."""
    datos: Any = [r.model_dump() for r in respuestas]
    if not lote:
        datos = datos[0]
    return json.dumps(datos, ensure_ascii=False, indent=2)


def render_barrido(resp: BarridoResponse, formato: str) -> str:
    """Barrido en tabla, JSON o CSV."""
    if formato == "json":
        return json.dumps(resp.model_dump(), ensure_ascii=False, indent=2)
    if formato == "csv":
        buffer = io.StringIO()
        escritor = csv.writer(buffer, lineterminator="\n")
        escritor.writerow(("valor", "salida_pct", "interpretacion"))
        for p in resp.puntos:
            escritor.writerow((p.valor, f"{p.salida_pct:.2f}", p.interpretacion))
        return buffer.getvalue()
    filas = [[f"{resp.variable}", "Salida (%)", "Interpretación"]]
    for p in resp.puntos:
        valor = formatear_hora(p.valor) if resp.variable == "hora" else _num(p.valor)
        filas.append([valor, _coma(p.salida_pct), p.interpretacion])
    return "\n".join(_alinear(filas))


def _renderizar(
    respuestas: Sequence[EvaluacionResponse], formato: str, detalle: bool, lote: bool
) -> str:
    """Elige la representación según ``--formato`` y ``--detalle``."""
    if formato == "json":
        return render_json(respuestas, lote)
    if formato == "csv":
        return render_csv(respuestas)
    if detalle:
        return "\n\n".join(render_detalle(r, i) for i, r in enumerate(respuestas))
    return render_tabla(respuestas)


def _info(mensaje: str) -> None:
    """Mensajes informativos a stderr (no contaminan json/csv en stdout)."""
    print(mensaje, file=sys.stderr)


# --------------------------------------------------------------------------- #
# Entradas
# --------------------------------------------------------------------------- #
def formatear_validacion(exc: ValidationError) -> str:
    """Resume un ``ValidationError`` de Pydantic en líneas legibles."""
    lineas = []
    for error in exc.errors():
        campo = ".".join(str(p) for p in error["loc"])
        mensaje = str(error["msg"]).removeprefix("Value error, ")
        lineas.append(f"  - {campo + ': ' if campo else ''}{mensaje}")
    return "\n".join(lineas)


def leer_csv(ruta: Path) -> list[EvaluacionRequest]:
    """Lee y valida (atómicamente) un CSV ``id,consumo_w,personas,hora``.

    Raises:
        ErrorCLI: Si el archivo no existe, faltan columnas o alguna fila es inválida
            (se informan todas las filas inválidas, con su número de línea).
    """
    if not ruta.is_file():
        raise ErrorCLI(f"No existe el archivo CSV: {ruta}")
    with ruta.open(newline="", encoding="utf-8-sig") as archivo:
        lector = csv.DictReader(archivo)
        columnas = [c.strip().lower() for c in (lector.fieldnames or [])]
        faltantes = [c for c in _COLUMNAS_CSV[1:] if c not in columnas]
        if faltantes:
            raise ErrorCLI(
                f"Faltan columnas en el CSV: {', '.join(faltantes)} "
                f"(se esperan: {', '.join(_COLUMNAS_CSV)})"
            )
        lector.fieldnames = columnas
        solicitudes: list[EvaluacionRequest] = []
        problemas: list[str] = []
        for fila in lector:
            linea = lector.line_num
            if not any((v or "").strip() for v in fila.values() if isinstance(v, str)):
                continue
            try:
                solicitudes.append(
                    EvaluacionRequest(
                        id_evaluacion=(fila.get("id") or "").strip() or None,
                        consumo_w=parsear_numero(fila["consumo_w"] or ""),
                        personas=parsear_numero(fila["personas"] or ""),
                        hora=parsear_hora(fila["hora"] or ""),
                    )
                )
            except ValidationError as exc:
                problemas.append(f"Línea {linea}:\n{formatear_validacion(exc)}")
            except ValueError as exc:
                problemas.append(f"Línea {linea}:\n  - {exc}")
    if problemas:
        raise ErrorCLI("CSV inválido; no se evaluó ninguna fila.\n" + "\n".join(problemas))
    if not solicitudes:
        raise ErrorCLI(f"El CSV no contiene filas de datos: {ruta}")
    return solicitudes


# --------------------------------------------------------------------------- #
# Modos
# --------------------------------------------------------------------------- #
def _guardar_graficos(
    servicio: DifusoService, solicitudes: Sequence[EvaluacionRequest], destino: str
) -> None:
    """Guarda la Figura 4 (una por fila en lotes, con sufijo de id)."""
    base = Path(destino)
    base.parent.mkdir(parents=True, exist_ok=True)
    for i, req in enumerate(solicitudes):
        ruta = base
        if len(solicitudes) > 1:
            sufijo = re.sub(r"[^A-Za-z0-9_.-]", "_", req.id_evaluacion or str(i + 1))
            ruta = base.with_name(f"{base.stem}_{sufijo}{base.suffix or '.png'}")
        ruta.write_bytes(servicio.grafico_agregacion(req))
        _info(f"Figura 4 guardada en {ruta}")


def _modo_directo(
    servicio: DifusoService, args: argparse.Namespace, solicitudes: list[EvaluacionRequest]
) -> None:
    respuestas = servicio.evaluar_lote(solicitudes).resultados
    print(_renderizar(respuestas, args.formato or "tabla", args.detalle, lote=False))
    if args.grafico:
        _guardar_graficos(servicio, solicitudes, args.grafico)


def _modo_lote(servicio: DifusoService, args: argparse.Namespace) -> None:
    solicitudes = leer_csv(Path(args.csv))
    respuestas = servicio.evaluar_lote(solicitudes).resultados
    if args.salida:
        formato = args.formato or "csv"
        contenido = _renderizar(respuestas, formato, False, lote=True)
        destino = Path(args.salida)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(contenido + ("" if contenido.endswith("\n") else "\n"), encoding="utf-8")
        if args.detalle and formato == "csv":
            print(_renderizar(respuestas, "tabla", True, lote=True))
        print(f"{len(respuestas)} resultados escritos en {destino}")
    else:
        print(_renderizar(respuestas, args.formato or "tabla", args.detalle, lote=True))
    if args.grafico:
        _guardar_graficos(servicio, solicitudes, args.grafico)


def _modo_barrido(servicio: DifusoService, args: argparse.Namespace) -> None:
    if args.desde is None or args.hasta is None:
        raise ErrorCLI("--barrido requiere --desde y --hasta")
    variable = _VARIABLES_BARRIDO[args.barrido]
    req = BarridoRequest(
        variable=variable,  # type: ignore[arg-type]
        desde=args.desde,
        hasta=args.hasta,
        pasos=args.pasos,
        consumo_w=args.consumo,
        personas=args.personas,
        hora=args.hora,
    )
    print(render_barrido(servicio.barrido(req), args.formato or "tabla"))


def _pedir(etiqueta: str, convertir: Any) -> float | None:
    """Pide un valor hasta que sea numérico; ``None`` si el usuario escribe ``q``."""
    while True:
        texto = input(f"{etiqueta}: ").strip()
        if texto.lower() in _SALIR:
            return None
        try:
            return float(convertir(texto))
        except ValueError as exc:
            print(f"  Error: {exc}")


def _modo_interactivo(servicio: DifusoService, args: argparse.Namespace) -> int:
    print("Modo interactivo. Escriba 'q' en cualquier momento para salir.")
    while True:
        try:
            consumo = _pedir("Consumo (W, 0-3000)", parsear_numero)
            if consumo is None:
                return 0
            personas = _pedir("Personas (0-6)", parsear_numero)
            if personas is None:
                return 0
            hora = _pedir("Hora (14.5 o 14:30, 0-24)", parsear_hora)
            if hora is None:
                return 0
        except EOFError:
            return 0
        try:
            req = EvaluacionRequest(consumo_w=consumo, personas=personas, hora=hora)
            _modo_directo(servicio, args, [req])
        except ValidationError as exc:
            print(f"  Entrada inválida:\n{formatear_validacion(exc)}")
        except MotorDifusoError as exc:
            print(f"  Error del motor: {exc}")
        print()


# --------------------------------------------------------------------------- #
# Punto de entrada
# --------------------------------------------------------------------------- #
def construir_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos."""
    p = argparse.ArgumentParser(
        prog="cli.py",
        description="Sistema difuso Mamdani: nivel de ahorro energético (0-100 %) según "
        "consumo (W), personas y hora. Sin argumentos: modo interactivo.",
    )
    entradas = p.add_argument_group("entradas (modo directo)")
    entradas.add_argument("--consumo", type=_tipo_numero, metavar="W", help="Potencia (0-3000 W)")
    entradas.add_argument("--personas", type=_tipo_numero, metavar="N", help="Personas (0-6)")
    entradas.add_argument(
        "--hora", type=_tipo_hora, metavar="H", help="Hora decimal (14.5) o HH:MM (14:30)"
    )
    entradas.add_argument("--id", dest="id_evaluacion", help="Identificador opcional")

    lote = p.add_argument_group("modo lote")
    lote.add_argument("--csv", metavar="ENTRADAS.csv", help="CSV con id,consumo_w,personas,hora")
    lote.add_argument("--salida", metavar="RESULTADOS", help="Archivo de resultados")

    barrido = p.add_argument_group("barrido (el resto de variables, fijas con --consumo/...)")
    barrido.add_argument("--barrido", choices=sorted(_VARIABLES_BARRIDO), help="Variable a variar")
    barrido.add_argument("--desde", type=_tipo_numero, metavar="X")
    barrido.add_argument("--hasta", type=_tipo_numero, metavar="Y")
    barrido.add_argument("--pasos", type=int, default=21, metavar="N", help="Puntos (def. 21)")

    comunes = p.add_argument_group("opciones transversales")
    comunes.add_argument("--detalle", action="store_true", help="Paso a paso (formato Tabla 9)")
    comunes.add_argument("--grafico", metavar="RUTA.png", help="Guarda la Figura 4")
    comunes.add_argument(
        "--figuras-informe", metavar="DIRECTORIO", help="Genera figura_1.png … figura_4.png"
    )
    comunes.add_argument("--formato", choices=("tabla", "json", "csv"), help="Formato de salida")
    comunes.add_argument("-v", "--verbose", action="store_true", help="Log detallado en stderr")
    return p


def _ejecutar(args: argparse.Namespace, sin_argumentos: bool) -> int:
    """Despacha al modo correspondiente."""
    servicio = DifusoService()
    if sin_argumentos:
        return _modo_interactivo(servicio, args)

    directo = [args.consumo, args.personas, args.hora]
    hay_directo = any(v is not None for v in directo)
    if args.csv and (args.barrido or hay_directo):
        raise ErrorCLI("--csv no se combina con --barrido ni con --consumo/--personas/--hora")

    hizo_algo = False
    if args.figuras_informe:
        rutas = graficos.generar_todas(args.figuras_informe)
        _info(f"{len(rutas)} figuras generadas en {args.figuras_informe}")
        hizo_algo = True

    if args.csv:
        _modo_lote(servicio, args)
    elif args.barrido:
        _modo_barrido(servicio, args)
    elif hay_directo:
        faltan = [
            nombre
            for nombre, valor in zip(("--consumo", "--personas", "--hora"), directo, strict=True)
            if valor is None
        ]
        if faltan:
            raise ErrorCLI(f"Faltan argumentos: {', '.join(faltan)}")
        req = EvaluacionRequest(
            id_evaluacion=args.id_evaluacion,
            consumo_w=args.consumo,
            personas=args.personas,
            hora=args.hora,
        )
        _modo_directo(servicio, args, [req])
    elif not hizo_algo:
        raise ErrorCLI(
            "Indique --consumo/--personas/--hora, --csv, --barrido o --figuras-informe "
            "(sin argumentos se abre el modo interactivo)"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta la CLI y devuelve el código de salida (no llama a ``sys.exit``)."""
    lista = list(sys.argv[1:] if argv is None else argv)
    parser = construir_parser()
    try:
        args = parser.parse_args(lista)
    except SystemExit as exc:  # argparse sale con 0 (--help) o 2 (uso incorrecto)
        return int(exc.code or 0) if isinstance(exc.code, int | None) else 2

    configure_logging("DEBUG" if args.verbose else "WARNING", json_format=False)
    try:
        return _ejecutar(args, sin_argumentos=not lista)
    except ErrorCLI as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        print(f"Error de validación:\n{formatear_validacion(exc)}", file=sys.stderr)
        return 2
    except MotorDifusoError as exc:
        print(f"Error del motor difuso: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error de archivo: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrumpido.", file=sys.stderr)
        return 130
    except Exception as exc:
        logger.debug("Error inesperado", exc_info=True)
        print(f"Error inesperado: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
