"""Fachada del motor difuso, compartida por la API y la CLI.

Centraliza la conversión ``ResultadoInferencia`` → esquemas (aquí se redondea), el
logging y el manejo de errores: cualquier excepción inesperada de NumPy o
scikit-fuzzy se envuelve en :class:`MotorDifusoError` con el contexto de la entrada.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import numpy as np

from core.config import Settings, get_settings
from core.exceptions import EntradaFueraDeRangoError, MotorDifusoError
from fuzzy import graficos, motor
from fuzzy.membresias import VARIABLES, funciones_salida, muestrear_variable
from fuzzy.reglas import REGLAS, TOTAL_REGLAS
from schemas.difuso import (
    BarridoPunto,
    BarridoRequest,
    BarridoResponse,
    CurvasVariable,
    EntradasEco,
    EvaluacionRequest,
    EvaluacionResponse,
    LoteResponse,
    MembresiasResponse,
    ReglaActivadaItem,
    ReglaItem,
)

logger = logging.getLogger(__name__)

#: Caso de verificación (ejemplo del informe) usado por ``health_check``.
_CASO_SALUD = (1900.0, 3.0, 12.0)
_SALIDA_SALUD = 46.72
_TOLERANCIA_SALUD = 0.05
_PUNTOS_MEMBRESIAS = 241


class DifusoService:
    """Fachada sin estado mutable: segura para usarse desde varias hebras."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Crea el servicio y precalcula las funciones de salida (una sola vez).

        Args:
            settings: Configuración; si es ``None`` se usa ``get_settings()``.
        """
        self._settings = settings or get_settings()
        self._paso = self._settings.paso_salida
        salida = funciones_salida(self._paso)
        logger.info(
            "Servicio difuso iniciado",
            extra={
                "paso_salida": self._paso,
                "puntos_universo_salida": int(salida.universo.size),
                "reglas": len(REGLAS),
            },
        )

    # ------------------------------------------------------------------ #
    # Núcleo
    # ------------------------------------------------------------------ #
    def _inferir(self, consumo_w: float, personas: float, hora: float) -> motor.ResultadoInferencia:
        """Llama al motor envolviendo cualquier excepción ajena al dominio."""
        try:
            return motor.evaluar(consumo_w, personas, hora, self._paso)
        except MotorDifusoError:
            logger.exception(
                "Error de dominio en la evaluación",
                extra={"consumo_w": consumo_w, "personas": personas, "hora": hora},
            )
            raise
        except Exception as exc:
            logger.exception(
                "Fallo inesperado en el motor",
                extra={"consumo_w": consumo_w, "personas": personas, "hora": hora},
            )
            raise MotorDifusoError(
                f"Fallo inesperado evaluando consumo_w={consumo_w}, personas={personas}, "
                f"hora={hora}: {type(exc).__name__}: {exc}"
            ) from exc

    @staticmethod
    def _a_respuesta(
        resultado: motor.ResultadoInferencia, id_evaluacion: str | None
    ) -> EvaluacionResponse:
        """Convierte el resultado exacto del motor a la respuesta redondeada."""
        return EvaluacionResponse(
            id_evaluacion=id_evaluacion,
            entradas=EntradasEco(**resultado.entradas),
            salida_pct=round(resultado.salida_pct, 2),
            interpretacion=resultado.interpretacion,
            accion_sugerida=resultado.accion_sugerida,
            fuzzificacion={
                variable: {k: round(v, 4) for k, v in grados.items()}
                for variable, grados in resultado.fuzzificacion.items()
            },
            reglas_activadas=[
                ReglaActivadaItem(
                    regla=r.regla,
                    consumo=r.consumo,
                    personas=r.personas,
                    hora=r.hora,
                    salida=r.salida,
                    alpha=round(r.alpha, 4),
                    calculo=r.calculo,
                )
                for r in resultado.reglas_activadas
            ],
        )

    def _evaluar_req(self, req: EvaluacionRequest) -> motor.ResultadoInferencia:
        return self._inferir(req.consumo_w, req.personas, req.hora)

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def evaluar(self, req: EvaluacionRequest) -> EvaluacionResponse:
        """Evalúa una entrada y registra el resultado (sin datos personales)."""
        resultado = self._evaluar_req(req)
        logger.info(
            "Evaluación id=%s consumo_w=%s personas=%s hora=%s → salida_pct=%.2f",
            req.id_evaluacion,
            req.consumo_w,
            req.personas,
            req.hora,
            resultado.salida_pct,
            extra={
                "id_evaluacion": req.id_evaluacion,
                "consumo_w": req.consumo_w,
                "personas": req.personas,
                "hora": req.hora,
                "salida_pct": round(resultado.salida_pct, 2),
            },
        )
        logger.debug(
            "Reglas activadas: %s",
            [(r.regla, round(r.alpha, 4)) for r in resultado.reglas_activadas],
            extra={"id_evaluacion": req.id_evaluacion},
        )
        return self._a_respuesta(resultado, req.id_evaluacion)

    def evaluar_lote(self, reqs: Sequence[EvaluacionRequest]) -> LoteResponse:
        """Evalúa un lote en el orden recibido."""
        logger.info("Evaluando lote", extra={"tamano_lote": len(reqs)})
        resultados: list[EvaluacionResponse] = []
        for req in reqs:
            resultado = self._evaluar_req(req)
            logger.debug(
                "Ítem de lote evaluado",
                extra={
                    "id_evaluacion": req.id_evaluacion,
                    "salida_pct": round(resultado.salida_pct, 2),
                },
            )
            resultados.append(self._a_respuesta(resultado, req.id_evaluacion))
        return LoteResponse(total=len(resultados), resultados=resultados)

    def barrido(self, req: BarridoRequest) -> BarridoResponse:
        """Varía una variable entre ``desde`` y ``hasta`` manteniendo fijas las otras."""
        logger.info(
            "Barrido",
            extra={
                "variable": req.variable,
                "desde": req.desde,
                "hasta": req.hasta,
                "pasos": req.pasos,
            },
        )
        # El esquema garantiza que las dos variables no barridas tienen valor fijo.
        fijos: dict[str, float] = {
            nombre: float(valor)
            for nombre, valor in (
                ("consumo_w", req.consumo_w),
                ("personas", req.personas),
                ("hora", req.hora),
            )
            if nombre != req.variable and valor is not None
        }
        puntos: list[BarridoPunto] = []
        for valor in np.linspace(req.desde, req.hasta, req.pasos):
            entradas = {**fijos, req.variable: float(valor)}
            resultado = self._inferir(entradas["consumo_w"], entradas["personas"], entradas["hora"])
            puntos.append(
                BarridoPunto(
                    valor=round(float(valor), 6),
                    salida_pct=round(resultado.salida_pct, 2),
                    interpretacion=resultado.interpretacion,
                )
            )
        return BarridoResponse(variable=req.variable, puntos=puntos)

    @staticmethod
    def reglas() -> list[ReglaItem]:
        """Las 36 reglas de la Tabla 8."""
        return [
            ReglaItem(
                id=r.id,
                consumo=r.consumo,
                personas=r.personas,
                hora=r.hora,
                salida=r.salida,
            )
            for r in REGLAS
        ]

    @staticmethod
    def membresias() -> MembresiasResponse:
        """Curvas muestreadas de las cuatro variables."""
        variables: dict[str, CurvasVariable] = {}
        for clave, variable in VARIABLES.items():
            x, curvas = muestrear_variable(variable, _PUNTOS_MEMBRESIAS)
            variables[clave] = CurvasVariable(
                nombre=variable.nombre,
                unidad=variable.unidad,
                x=[round(float(v), 4) for v in x],
                conjuntos={k: [round(float(v), 4) for v in mu] for k, mu in curvas.items()},
            )
        return MembresiasResponse(variables=variables)

    def grafico_agregacion(self, req: EvaluacionRequest) -> bytes:
        """Figura 4 (PNG) para la entrada dada."""
        resultado = self._evaluar_req(req)
        try:
            return graficos.figura_4_agregacion(resultado)
        except Exception as exc:
            logger.exception("Fallo al generar la figura de agregación")
            raise MotorDifusoError(f"No se pudo generar el gráfico: {exc}") from exc

    @staticmethod
    def grafico_membresias(n: int) -> bytes:
        """Figuras 1–3 (PNG) de funciones de pertenencia.

        Raises:
            EntradaFueraDeRangoError: Si ``n`` no es 1, 2 o 3.
        """
        generadores = {
            1: graficos.figura_1_consumo_personas,
            2: graficos.figura_2_hora,
            3: graficos.figura_3_salida,
        }
        if n not in generadores:
            raise EntradaFueraDeRangoError(f"La figura de membresías debe ser 1, 2 o 3 (n={n})")
        try:
            return generadores[n]()
        except Exception as exc:
            logger.exception("Fallo al generar la figura %s", n)
            raise MotorDifusoError(f"No se pudo generar la figura {n}: {exc}") from exc

    def health_check(self) -> bool:
        """Verifica reglas, funciones de salida y una evaluación de prueba (1900/3/12)."""
        try:
            if len(REGLAS) != TOTAL_REGLAS:
                return False
            if funciones_salida(self._paso).universo.size < 2:
                return False
            salida = motor.evaluar(*_CASO_SALUD, self._paso).salida_pct
            return abs(salida - _SALIDA_SALUD) <= _TOLERANCIA_SALUD
        except Exception:
            logger.exception("Health check fallido")
            return False
