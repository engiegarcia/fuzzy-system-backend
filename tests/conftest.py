"""Fixtures compartidas. La configuración se fija por entorno para que las pruebas
sean herméticas (no dependen de un ``.env`` local)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

# Debe ejecutarse antes de importar cualquier módulo que lea la configuración.
os.environ.update(
    {
        "PASO_SALIDA": "0.01",
        "MAX_LOTE": "1000",
        "MAX_PASOS_BARRIDO": "500",
        "LOG_LEVEL": "WARNING",
        "LOG_JSON": "false",
        "ENVIRONMENT": "dev",
        "CORS_ALLOWED_ORIGINS": '["http://localhost:3000"]',
    }
)


@pytest.fixture(scope="session")
def servicio():
    """``DifusoService`` independiente (sin pasar por HTTP)."""
    from core.config import get_settings
    from services.difuso_service import DifusoService

    get_settings.cache_clear()
    return DifusoService()


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """``TestClient`` con el ciclo de vida (``lifespan``) activo."""
    from main import create_app

    with TestClient(create_app()) as cliente:
        yield cliente
