"""Núcleo del sistema de inferencia difusa tipo Mamdani."""

from fuzzy.interpretacion import interpretar
from fuzzy.motor import ReglaActivada, ResultadoInferencia, evaluar
from fuzzy.reglas import REGLAS, Regla

__all__ = [
    "REGLAS",
    "Regla",
    "ReglaActivada",
    "ResultadoInferencia",
    "evaluar",
    "interpretar",
]
