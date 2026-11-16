"""API FastAPI del cv-server (ADR-001).

Capa HTTP tipada con Pydantic sobre la lógica de negocio de server.
Coexiste con Flask; se migra endpoint por endpoint. Servir con:  uvicorn api:app
"""
import hmac
import hashlib

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import server
import usuarias
import base_de_datos
from server import CVError, generar_cv_core, generar_carta_core

app = FastAPI(title="cv-server API", version="0.1.0")

# CORS: replica de server.py (_RUTAS_CON_CORS). En FastAPI se aplica globalmente;
# las rutas de máquina (n8n) no pasan por aquí porque no envían Origin.
_ORIGENES = [o.strip() for o in (server.ORIGENES_PERMITIDOS or []) if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGENES,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ClaveApiRequest(BaseModel):
    proveedor: str = "anthropic"
    api_key: str = Field(min_length=10)


class ClaveApiEstado(BaseModel):
    proveedor: str
    configurada: bool
    trial_restante: int
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
    # True = el master leido es de otro idioma que el del CV.
    master_traducido: bool = False
    # GUARDRAILS. Van declarados aqui a proposito: `response_model` FILTRA todo campo
    # que no figure en el modelo, asi que un guardrail sin declarar se calcula, se
    # loguea y NUNCA llega a quien llama. Vacio = nada que revisar.
    cifras_no_respaldadas: list[str] = []
    tecnologias_no_respaldadas: list[str] = []
    titular_fuera_de_contrato: list[str] = []
    # Guardrails skipped because the master is in another language (translated mode).
    no_evaluables: list[str] = []
    descripcion_oferta: DescripcionOferta | None = None
    # Tokens que gasto la generacion (ADR-004: lo paga la clave de la usuaria).
    consumo: dict | None = None


def requiere_clave_maquina(x_clave_maquina: str = Header(default="")):
    """Lo mismo que el decorador de server.py (ADR-003): sin la clave, 401. Falla cerrado."""
    clave = server.CLAVE_MAQUINA
    if not clave or not hmac.compare_digest(x_clave_maquina.encode(), clave.encode()):
        raise HTTPException(status_code=401, detail="no autorizado")


def get_current_user(authorization: str = Header(default="")):
    """Resuelve la identidad y el usuario_id de Neon a partir del token de Google."""
    try:
        identidad = server.identificar(authorization, server.CONFIG_OIDC, server.CLAVES,
                                     autorizar=lambda id_: True)  # invitadas por lista en config
    except (server.ErrorDeAutenticacion, server.NoInvitada, server.ProveedorNoDisponible) as e:
        raise HTTPException(status_code=401, detail=str(e))
    # resolver en Neon (si hay BD)
    usuario_id = None
    if base_de_datos.configurada():
        try:
            with base_de_datos.transaccion() as conexion:
                usuario_id = usuarias.resolver_o_crear(identidad, conexion=conexion)
        except Exception:
            usuario_id = None
    if usuario_id is None:
        raise HTTPException(status_code=403, detail="acceso no permitido")
    return identidad, usuario_id



@app.get("/clave-api", response_model=ClaveApiEstado)
def estado_clave_api(proveedor: str = "anthropic", user=Depends(get_current_user)):
    if proveedor not in {"anthropic", "groq"}:
        raise HTTPException(status_code=422, detail="proveedor no válido")
    identidad, usuario_id = user
    from repositorio import RepositorioDeUsuaria
    with base_de_datos.transaccion() as conexion:
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        return {
            "proveedor": proveedor,
            "configurada": repo.tiene_clave_api(proveedor),
            "trial_restante": repo.trial_restante(),
        }


@app.put("/clave-api")
def guardar_clave_api(req: ClaveApiRequest, user=Depends(get_current_user)):
    if req.proveedor not in {"anthropic", "groq"}:
        raise HTTPException(status_code=422, detail="proveedor no válido")
    identidad, usuario_id = user
    from repositorio import RepositorioDeUsuaria
    with base_de_datos.transaccion() as conexion:
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        try:
            repo.guardar_clave_api(req.proveedor, req.api_key)
        except Exception:
            raise HTTPException(status_code=422, detail="no se pudo guardar la clave")
    return {"configurada": True, "proveedor": req.proveedor}


@app.delete("/clave-api/{proveedor}")
def borrar_clave_api(proveedor: str, user=Depends(get_current_user)):
    if proveedor not in {"anthropic", "groq"}:
        raise HTTPException(status_code=422, detail="proveedor no válido")
    identidad, usuario_id = user
    from repositorio import RepositorioDeUsuaria
    with base_de_datos.transaccion() as conexion:
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        repo.borrar_clave_api(proveedor)
    return {"ok": True}


class GenerarCartaRequest(BaseModel):
    email: str = Field(min_length=1)
    empresa: str = Field(min_length=1)
    puesto: str = Field(min_length=1)
    descripcion: str = ""
    idioma: str | None = None
    contacto: str | None = None


class GenerarCartaResponse(BaseModel):
    ok: bool
    carta: str
    modelo_usado: str
    consumo: dict | None = None
    email: str
    cv_master_usado: bool
    master_traducido: bool = False
    avisos: list = []
    no_evaluables: list = []


@app.get("/health")
def health():
    return {"ok": True, "service": "cv-server", "framework": "fastapi"}


@app.post("/cv-master/check", dependencies=[Depends(requiere_clave_maquina)])
async def cv_master_check(request: Request):
    """Diagnóstico del CV maestro (port de server.py /cv-master/check)."""
    import checker

    datos = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    texto = datos.get("markdown") or datos.get("texto") or datos.get("text") or ""
    if not texto.strip():
        raise HTTPException(status_code=400, detail="Texto vacío")

    normalizado = checker.normalizar_cv(texto)
    claims = checker.detectar_claims_sin_metrica(texto)
    skills = checker.detectar_skills_sin_evidencia(texto)
    gaps = checker.detectar_gaps_temporales(texto)
    secciones_faltantes = checker.detectar_secciones_recuperables(normalizado)

    findings = []
    for claim in claims:
        findings.append({"type": "needs-evidence", "message": "Claim sin métrica ni evidencia.", "evidence": claim})
    for skill in skills:
        findings.append({"type": "unsupported-skill", "message": "Skill declarada sin evidencia en experiencia.", "evidence": skill})
    for gap in gaps:
        findings.append({"type": "gap", "message": "Gap temporal detectado.", "evidence": gap})
    for seccion in secciones_faltantes:
        findings.append({"type": "missing-section", "message": "Sección recomendada ausente.", "evidence": seccion})

    if not normalizado["secciones_presentes"]:
        status = checker.Status.INSUFFICIENT_CONTENT.value
    elif findings:
        status = checker.Status.WARNING.value
    else:
        status = checker.Status.OK.value

    proposals = [{"type": "section", "message": f"Añadir o completar la sección `{s}`.", "section": s} for s in secciones_faltantes]

    hash_cv = hashlib.sha256(normalizado["texto_normalizado"].encode("utf-8")).hexdigest()
    persistido = checker.persistir_analisis(hash_cv, {
        "status": status, "findings": findings, "proposals": proposals,
        "hash_cv": hash_cv, "version_label": datos.get("version_label"),
    })

    return {"ok": True, "analisis": persistido}


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
        return JSONResponse(status_code=e.status, content={"ok": False, "error": e.message, **e.extra})
    return result


@app.post("/generar-carta", response_model=GenerarCartaResponse, dependencies=[Depends(requiere_clave_maquina)])
def generar_carta(req: GenerarCartaRequest):
    """Ruta FastAPI: delega en generar_carta_core (ADR-001)."""
    try:
        result = generar_carta_core(
            email=req.email,
            empresa=req.empresa,
            puesto=req.puesto,
            descripcion=req.descripcion,
            idioma_in=(req.idioma or "").strip().lower(),
            contacto=(req.contacto or "").strip(),
        )
    except CVError as e:
        return JSONResponse(status_code=e.status, content={"ok": False, "error": e.message, **e.extra})
    return result
