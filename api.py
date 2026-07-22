"""API FastAPI del cv-server (ADR-001).

Capa HTTP tipada con Pydantic sobre la lógica de negocio de cv_server_railway.
Coexiste con Flask; se migra endpoint por endpoint. Servir con:  uvicorn api:app
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cv_server_railway import CVError, generar_cv_core

app = FastAPI(title="cv-server API", version="0.1.0")


class GenerarCVRequest(BaseModel):
    email: str = Field(min_length=1)
    empresa: str = Field(min_length=1)
    puesto: str = Field(min_length=1)
    descripcion: str = ""
    idioma: str | None = None  # "en" | "es"


class GenerarCVResponse(BaseModel):
    ok: bool
    link: str
    modelo_usado: str
    archivo: str
    email: str
    cv_master_usado: bool
    idioma: str
    cv_master_url: str


@app.post("/generar-cv", response_model=GenerarCVResponse)
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
