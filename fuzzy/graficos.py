"""Figuras del informe (membresías y agregación + centroide).

Decisión: se usa ``matplotlib.figure.Figure`` (API orientada a objetos) con
``FigureCanvasAgg`` en lugar de ``matplotlib.pyplot``. ``pyplot`` mantiene un
estado global (figura/ejes actuales y un gestor de figuras) que no es seguro entre
hilos; con ``Figure`` cada llamada trabaja solo con objetos locales, por lo que
puede ejecutarse concurrentemente en el threadpool de FastAPI.

Las figuras se renderizan con el backend ``Agg`` (sin pantalla) a 200 dpi y se
devuelven como ``bytes`` PNG listos para insertar en un documento Word.

Color: cada conjunto de salida conserva el mismo color en la Figura 3 y en la 4
(el color sigue a la entidad). La identidad nunca depende solo del color: todas
las curvas llevan etiqueta directa además de la leyenda.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from numpy.typing import NDArray

from fuzzy.membresias import (
    CONSUMO,
    HORA,
    PERSONAS,
    SALIDA,
    VariableDifusa,
    muestrear_variable,
)
from fuzzy.motor import ResultadoInferencia, evaluar

FloatArray = NDArray[np.float64]

DPI: Final[int] = 200
_SUPERFICIE: Final[str] = "#fcfcfb"
_TINTA: Final[str] = "#0b0b0b"
_TINTA_SECUNDARIA: Final[str] = "#52514e"
_GRILLA: Final[str] = "#e4e3df"

# Colores categóricos en orden fijo (azul, naranja, aqua, amarillo, magenta).
_PALETA: Final[tuple[str, ...]] = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4")

#: Color estable por conjunto de salida (misma entidad → mismo color en Figuras 3 y 4).
_COLOR_SALIDA: Final[dict[str, str]] = dict(zip(SALIDA.claves, _PALETA, strict=True))

_CASO_INFORME: Final[tuple[float, float, float]] = (1900.0, 3.0, 12.0)


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def _coma(valor: float, decimales: int = 2) -> str:
    """Formatea con coma decimal (convención del informe)."""
    return f"{valor:.{decimales}f}".replace(".", ",")


def _a_png(fig: Figure) -> bytes:
    """Renderiza la figura con Agg y devuelve los bytes PNG."""
    FigureCanvasAgg(fig)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=DPI, facecolor=fig.get_facecolor())
    return buffer.getvalue()


def _nueva_figura(ancho: float, alto: float) -> Figure:
    return Figure(figsize=(ancho, alto), facecolor=_SUPERFICIE, layout="constrained")


def _estilo_ejes(ax: Axes, titulo: str, xlabel: str, ylabel: str) -> None:
    """Aplica estilo recesivo (rejilla suave, sin marco superior/derecho)."""
    ax.set_facecolor(_SUPERFICIE)
    ax.set_title(titulo, fontsize=11, color=_TINTA, loc="left", fontweight="bold")
    ax.set_xlabel(xlabel, fontsize=9.5, color=_TINTA_SECUNDARIA)
    ax.set_ylabel(ylabel, fontsize=9.5, color=_TINTA_SECUNDARIA)
    ax.grid(True, color=_GRILLA, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=_TINTA_SECUNDARIA, labelsize=8.5)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(_TINTA_SECUNDARIA)


def _centro_meseta(x: FloatArray, mu: FloatArray) -> float:
    """Centro de la meseta más larga (μ ≈ 1); sirve para ubicar la etiqueta directa."""
    cima = mu >= 0.999
    if not cima.any():
        return float(x[int(np.argmax(mu))])
    mejor_inicio = mejor_largo = 0
    inicio: int | None = None
    for i, activo in enumerate(np.append(cima, False)):
        if activo and inicio is None:
            inicio = i
        elif not activo and inicio is not None:
            if i - inicio > mejor_largo:
                mejor_inicio, mejor_largo = inicio, i - inicio
            inicio = None
    return float(x[mejor_inicio : mejor_inicio + mejor_largo].mean())


def _graficar_variable(
    ax: Axes,
    variable: VariableDifusa,
    titulo: str,
    xlabel: str,
    colores: Sequence[str] = _PALETA,
    n_puntos: int = 1201,
) -> None:
    """Dibuja todos los conjuntos de una variable con etiqueta directa y leyenda."""
    x, curvas = muestrear_variable(variable, n_puntos)
    for conjunto, color in zip(variable.conjuntos, colores, strict=False):
        mu = curvas[conjunto.clave]
        ax.plot(x, mu, color=color, linewidth=2.0, label=conjunto.etiqueta)
        ax.text(
            _centro_meseta(x, mu),
            1.05,
            conjunto.etiqueta,
            color=_TINTA,
            fontsize=8.5,
            ha="center",
            va="bottom",
        )
    _estilo_ejes(ax, titulo, xlabel, "Grado de pertenencia μ")
    ax.set_xlim(variable.minimo, variable.maximo)
    ax.set_ylim(0, 1.18)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.2),
        ncols=len(variable.conjuntos),
        frameon=False,
        fontsize=8.5,
    )


# --------------------------------------------------------------------------- #
# Figuras del informe
# --------------------------------------------------------------------------- #
def figura_1_consumo_personas() -> bytes:
    """Figura 1: funciones de pertenencia de consumo eléctrico y de personas (2 paneles)."""
    fig = _nueva_figura(12.0, 4.8)
    ax_consumo, ax_personas = fig.subplots(1, 2)
    _graficar_variable(
        ax_consumo,
        CONSUMO,
        "Consumo eléctrico",
        "Potencia demandada (W)",
    )
    _graficar_variable(
        ax_personas,
        PERSONAS,
        "Cantidad de personas",
        "Personas presentes (n.º de personas)",
    )
    fig.suptitle(
        "Figura 1. Funciones de pertenencia de las entradas: consumo y personas",
        fontsize=12,
        color=_TINTA,
    )
    return _a_png(fig)


def figura_2_hora() -> bytes:
    """Figura 2: hora del día con tratamiento circular (continuidad 24:00 ≡ 00:00)."""
    fig = _nueva_figura(11.0, 5.0)
    ax = fig.subplots()
    _graficar_variable(ax, HORA, "Hora del día (variable circular)", "Hora del día (h)")
    ax.set_xticks(range(0, 25, 2))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 25, 2)])
    # Continuidad circular: en 24:00 y en 00:00 Madrugada y Noche valen 1.
    ax.axvline(0, color=_TINTA_SECUNDARIA, linestyle=":", linewidth=1.0)
    ax.axvline(24, color=_TINTA_SECUNDARIA, linestyle=":", linewidth=1.0)
    ax.annotate(
        "24:00 ≡ 00:00\nMadrugada = Noche = 1",
        xy=(0, 1.0),
        xytext=(2.3, 0.1),
        fontsize=8.5,
        color=_TINTA,
        arrowprops={"arrowstyle": "->", "color": _TINTA_SECUNDARIA, "linewidth": 1.0},
    )
    ax.annotate(
        "continúa en 00:00",
        xy=(24, 1.0),
        xytext=(20.3, 0.62),
        fontsize=8.5,
        color=_TINTA,
        arrowprops={"arrowstyle": "->", "color": _TINTA_SECUNDARIA, "linewidth": 1.0},
    )
    fig.suptitle("Figura 2. Funciones de pertenencia de la hora del día", fontsize=12, color=_TINTA)
    return _a_png(fig)


def figura_3_salida() -> bytes:
    """Figura 3: funciones de pertenencia del nivel de ahorro energético."""
    fig = _nueva_figura(11.0, 5.0)
    ax = fig.subplots()
    colores = [_COLOR_SALIDA[c.clave] for c in SALIDA.conjuntos]
    _graficar_variable(
        ax, SALIDA, "Nivel de ahorro energético", "Nivel de ahorro energético (%)", colores
    )
    fig.suptitle("Figura 3. Funciones de pertenencia de la salida", fontsize=12, color=_TINTA)
    return _a_png(fig)


def figura_4_agregacion(resultado: ResultadoInferencia) -> bytes:
    """Figura 4: conjuntos recortados por α, área agregada y centroide ``y*``.

    Args:
        resultado: Resultado de :func:`fuzzy.motor.evaluar` para la entrada a graficar.
    """
    universo = resultado.universo
    fig = _nueva_figura(11.0, 6.2)
    ax = fig.subplots()

    # Contexto: conjuntos de salida completos, tenues.
    for conjunto in SALIDA.conjuntos:
        ax.plot(
            universo,
            conjunto.evaluar(universo),
            color=_COLOR_SALIDA[conjunto.clave],
            linewidth=1.0,
            linestyle=":",
            alpha=0.55,
        )

    # Conjuntos recortados al nivel α de cada regla activa.
    for activada in resultado.reglas_activadas:
        clave = SALIDA.clave_de(activada.salida)
        recorte = np.minimum(activada.alpha, SALIDA.conjunto(activada.salida).evaluar(universo))
        ax.fill_between(universo, recorte, color=_COLOR_SALIDA[clave], alpha=0.28, linewidth=0)
        ax.plot(
            universo,
            recorte,
            color=_COLOR_SALIDA[clave],
            linewidth=1.8,
            label=f"{activada.regla} → {activada.salida} (α = {_coma(activada.alpha, 4)})",
        )

    # Área agregada (MAX) y centroide.
    ax.fill_between(
        universo,
        resultado.agregado,
        color=_TINTA_SECUNDARIA,
        alpha=0.12,
        linewidth=0,
        label="Área agregada (MAX)",
    )
    ax.plot(universo, resultado.agregado, color=_TINTA, linewidth=2.0)
    y_star = resultado.salida_pct
    ax.axvline(
        y_star,
        color=_TINTA,
        linestyle="--",
        linewidth=1.6,
        label=f"Centroide y* = {_coma(y_star)} %",
    )
    ax.annotate(
        f"y* = {_coma(y_star)} %",
        xy=(y_star, 1.0),
        xytext=(6, -2),
        textcoords="offset points",
        fontsize=10,
        fontweight="bold",
        color=_TINTA,
        ha="left",
        va="top",
    )

    consumo = resultado.entradas["consumo_w"]
    personas = resultado.entradas["personas"]
    hora = resultado.entradas["hora"]
    _estilo_ejes(
        ax,
        f"Consumo = {_coma(consumo, 0)} W · Personas = {_coma(personas, 0)} · "
        f"Hora = {_coma(hora, 1)} h",
        "Nivel de ahorro energético (%)",
        "Grado de pertenencia μ",
    )
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 1.08)
    fig.suptitle(
        "Figura 4. Agregación (MAX) de los conjuntos recortados y defuzzificación por centroide",
        fontsize=12,
        color=_TINTA,
    )
    fig.legend(loc="outside lower center", ncols=2, frameon=False, fontsize=8.5)
    return _a_png(fig)


def generar_todas(
    directorio: str | Path, resultado_caso_informe: ResultadoInferencia | None = None
) -> list[Path]:
    """Guarda ``figura_1.png`` … ``figura_4.png`` en ``directorio``.

    Args:
        directorio: Carpeta de destino (se crea si no existe).
        resultado_caso_informe: Resultado para la Figura 4. Si es ``None`` se evalúa
            el caso del informe 1900 W / 3 personas / 12 h.

    Returns:
        Las cuatro rutas escritas, en orden.
    """
    destino = Path(directorio)
    destino.mkdir(parents=True, exist_ok=True)
    resultado = resultado_caso_informe or evaluar(*_CASO_INFORME)
    contenidos = (
        figura_1_consumo_personas(),
        figura_2_hora(),
        figura_3_salida(),
        figura_4_agregacion(resultado),
    )
    rutas: list[Path] = []
    for numero, png in enumerate(contenidos, start=1):
        ruta = destino / f"figura_{numero}.png"
        ruta.write_bytes(png)
        rutas.append(ruta)
    return rutas
