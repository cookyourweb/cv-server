"""API FastAPI del cv-server (ADR-001).

Capa HTTP tipada con Pydantic sobre la lógica de negocio de server.
Coexiste con Flask; se migra endpoint por endpoint. Servir con:  uvicorn api:app
"""
import hmac

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import server
from server import CVError, generar_cv_core

app = FastAPI(title="cv-server API", version="0.1.0")


class GenerarCVRequest(BaseModel):
    email: str = Field(min_length=1)
    empresa: str = Field(min_length=1)
    puesto: str = Field(min_length=1)
    descripcion: str = ""
    idioma: str | None = None  # "en" | "es"


class DescripcionOferta(BaseModel):
    """¿Habia material en la oferta para adaptar el CV? Guardrail de ENTRADA."""
    suficiente: bool
    chars: int
    aviso: str


class GenerarCVResponse(BaseModel):
    ok: bool
    link: str
    modelo_usado: str
    archivo: str
    email: str
    cv_master_usado: bool
    idioma: str
    cv_master_url: str
    # GUARDRAILS. Van declarados aqui a proposito: `response_model` FILTRA todo campo
    # que no figure en el modelo, asi que un guardrail sin declarar se calcula, se
    # loguea y NUNCA llega a quien llama. Vacio = nada que revisar.
    cifras_no_respaldadas: list[str] = []
    tecnologias_no_respaldadas: list[str] = []
    titular_fuera_de_contrato: list[str] = []
    descripcion_oferta: DescripcionOferta | None = None
    # Tokens que gasto la generacion (ADR-004: lo paga la clave de la usuaria).
    consumo: dict | None = None


def requiere_clave_maquina(x_clave_maquina: str = Header(default="")):
    """Lo mismo que el decorador de server.py (ADR-003): sin la clave, 401. Falla cerrado."""
    clave = server.CLAVE_MAQUINA
    if not clave or not hmac.compare_digest(x_clave_maquina.encode(), clave.encode()):
        raise HTTPException(status_code=401, detail="no autorizado")


@app.post("/generar-cv", response_model=GenerarCVResponse, dependencies=[Depends(requiere_clave_maquina)])
def generar_cv(req: GenerarCVRequest):
    """Ruta FastAPI: contrato Pydantic + delega en generar_cv_core (ADR-001)."""
    try:
        result = generar_cv_core(
            email=req.email,
            empresa=req.empresa,
            puesto=req.puesto,
            descripcion=req.descripcion,
            idioma_in=(req.idioma or ""),
        )
    except CVError as e:
        return JSONResponse(status_code=e.status, content={"ok": False, "error": e.message})
    return result
