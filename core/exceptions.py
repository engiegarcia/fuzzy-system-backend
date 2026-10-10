"""Jerarquía de excepciones de dominio del motor difuso.

Todas las excepciones heredan de :class:`MotorDifusoError`, de modo que la capa
de servicio y la API puedan capturar una única clase base. Cada excepción expone
un ``codigo`` estable (útil como ``error_code`` en las respuestas HTTP).

No existe ``SinRecomendacionError``: la base de 36 reglas es completa y, para
cualquier entrada válida, activa al menos una regla, por lo que siempre hay salida.
"""

from __future__ import annotations


class MotorDifusoError(Exception):
    """Error base de cualquier fallo del motor de inferencia difusa."""

    codigo: str = "MOTOR_DIFUSO_ERROR"


class EntradaFueraDeRangoError(MotorDifusoError):
    """Una entrada es NaN/inf o cae fuera del universo de discurso.

    Es una defensa en profundidad: la capa de esquemas (Pydantic) ya rechaza
    estos valores, pero el motor nunca debe recortarlos (clamp) en silencio.
    """

    codigo = "ENTRADA_FUERA_DE_RANGO"


class ConfiguracionReglasError(MotorDifusoError):
    """La base de reglas está incompleta o es inconsistente."""

    codigo = "CONFIGURACION_REGLAS_INVALIDA"


class DefuzzificacionError(MotorDifusoError):
    """El área agregada es nula (o el centroide no es válido)."""

    codigo = "DEFUZZIFICACION_ERROR"
