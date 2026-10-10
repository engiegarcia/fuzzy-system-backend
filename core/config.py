"""Configuración de la aplicación vía variables de entorno / ``.env``."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

APP_NAME = "Sistema Difuso de Gestión del Consumo Eléctrico Doméstico"
APP_VERSION = "1.0.0"


class Settings(BaseSettings):
    """Parámetros de ejecución del backend.

    Se cargan desde variables de entorno o desde un archivo ``.env``. Las variables
    de entorno reales tienen prioridad sobre el archivo.

    Attributes:
        cors_allowed_origins: Orígenes permitidos por CORS. Admite una lista JSON
            (``["http://localhost:3000"]``) o valores separados por comas.
        log_level: Nivel de logging (``DEBUG``, ``INFO``, ``WARNING``...).
        log_json: Si es ``True`` los logs se emiten como una línea JSON.
        environment: ``dev`` o ``prod``.
        paso_salida: Resolución del universo de salida para el centroide
            (``0 < paso <= 1``). Un paso menor es más preciso y más lento.
        max_lote: Máximo de evaluaciones aceptadas en ``/api/evaluar/lote``.
        max_pasos_barrido: Máximo de puntos aceptados en ``/api/barrido``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cors_allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    log_level: str = "INFO"
    log_json: bool = False
    environment: Literal["dev", "prod"] = "dev"
    paso_salida: float = 0.01
    max_lote: int = 1000
    max_pasos_barrido: int = 500

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _parsear_origenes(cls, valor: Any) -> Any:
        """Acepta lista JSON o cadena separada por comas."""
        if isinstance(valor, str):
            texto = valor.strip()
            if texto.startswith("["):
                return json.loads(texto)
            return [item.strip() for item in texto.split(",") if item.strip()]
        return valor

    @field_validator("log_level")
    @classmethod
    def _validar_nivel(cls, valor: str) -> str:
        """Normaliza y valida el nivel de logging."""
        nivel = valor.upper()
        if nivel not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError(f"log_level inválido: {valor!r}")
        return nivel

    @field_validator("paso_salida")
    @classmethod
    def _validar_paso(cls, valor: float) -> float:
        """El paso del universo de salida debe cumplir ``0 < paso <= 1``."""
        if not 0 < valor <= 1:
            raise ValueError("paso_salida debe cumplir 0 < paso <= 1")
        return valor

    @field_validator("max_lote", "max_pasos_barrido")
    @classmethod
    def _validar_positivo(cls, valor: int) -> int:
        """Los límites de lote y barrido deben ser enteros positivos."""
        if valor < 1:
            raise ValueError("el límite debe ser >= 1")
        return valor


@lru_cache
def get_settings() -> Settings:
    """Devuelve la instancia única de :class:`Settings`.

    Está cacheada con ``lru_cache``; en pruebas puede reiniciarse con
    ``get_settings.cache_clear()`` tras modificar variables de entorno.
    """
    return Settings()
