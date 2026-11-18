"""Errores de negocio del cv-server (sin dependencias de framework).

`CVError` se lanza desde los cores (server.py, alta_core.py, encaje_core.py, ...)
y cada capa HTTP (Flask/FastAPI) lo mapea a su formato de respuesta.
Ver docs/ADR-001.
"""


class CVError(Exception):
    """Error de negocio del cv-server: status HTTP + mensaje."""

    def __init__(self, status: int, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        # Extra fields of the JSON body (e.g. `motivo`, `se_renueva` of a quota refusal).
        self.extra = extra or {}

