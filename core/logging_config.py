"""Configuración de logging.

Decisión: se usa el módulo estándar ``logging`` con un formateador JSON propio en
lugar de ``structlog``. Cubre los requisitos (JSON opcional, campos extra,
stacktraces) sin añadir una dependencia más al conjunto fijado en
``requirements.txt``.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Atributos estándar de LogRecord: lo que no esté aquí se considera "extra".
_ATRIBUTOS_ESTANDAR = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys() | {"message", "asctime", "taskName"}
)
_MARCA_HANDLER = "_difuso_handler"


class JsonFormatter(logging.Formatter):
    """Formatea cada registro como una línea JSON (apto para agregadores de logs)."""

    def format(self, record: logging.LogRecord) -> str:
        """Serializa el registro, incluyendo campos ``extra`` y stacktrace."""
        datos: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for clave, valor in record.__dict__.items():
            if clave not in _ATRIBUTOS_ESTANDAR and not clave.startswith("_"):
                datos[clave] = valor
        if record.exc_info:
            datos["exception"] = self.formatException(record.exc_info)
        return json.dumps(datos, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", json_format: bool = False) -> None:
    """Configura el logger raíz. Es idempotente (no duplica handlers).

    Args:
        level: Nivel de logging (p. ej. ``"INFO"``).
        json_format: Si es ``True`` emite JSON; si no, texto legible.
    """
    raiz = logging.getLogger()
    for handler in list(raiz.handlers):
        if getattr(handler, _MARCA_HANDLER, False):
            raiz.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    setattr(handler, _MARCA_HANDLER, True)
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    raiz.addHandler(handler)
    raiz.setLevel(level.upper())
