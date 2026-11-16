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
from server import registrar_invitada
import puntuacion
import notion
import real_jobs
import base_de_datos
import time
from repositorio import RepositorioDeUsuaria, PerfilEntrada, ConsentimientoEntrada
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


def _autorizar_invitada(identidad):
    """Callback de invitacion: usa la BD si esta configurada, si no la lista de config."""
    if not base_de_datos.configurada():
        return identidad.email.strip().lower() in (server.CONFIG_OIDC.invitadas or set())
    try:
        with base_de_datos.transaccion() as conexion:
            uid = usuarias.id_por_emails([identidad.email], conexion)
            if uid is not None:
                return True
            # sin fila en Neon: solo si esta en la lista heredada
            return identidad.email.strip().lower() in (server.CONFIG_OIDC.invitadas or set())
    except Exception:
        return False


def get_current_user(authorization: str = Header(default="")):
    """Resuelve la identidad y el usuario_id de Neon a partir del token de Google."""
    try:
        identidad = server.identificar(authorization, server.CONFIG_OIDC, server.CLAVES,
                                     autorizar=_autorizar_invitada)
    except (server.ErrorDeAutenticacion, server.NoInvitada, server.ProveedorNoDisponible) as e:
        raise HTTPException(status_code=401, detail=str(e))
    usuario_id = None
    if base_de_datos.configurada():
        try:
            with base_de_datos.transaccion() as conexion:
                usuario_id = usuarias.resolver_o_crear(identidad, conexion=conexion)
        except Exception:
            usuario_id = None
    if usuario_id is None:
        # modo heredado sin BD: None permitido para rutas que no requieren Neon
        pass
    return identidad, usuario_id



@app.get("/clave-api", response_model=ClaveApiEstado)
def estado_clave_api(proveedor: str = "anthropic", user=Depends(get_current_user)):
    if proveedor not in {"anthropic", "groq"}:
        raise HTTPException(status_code=422, detail="proveedor no válido")
    identidad, usuario_id = user
    from repositorio import RepositorioDeUsuaria, PerfilEntrada, ConsentimientoEntrada
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
    from repositorio import RepositorioDeUsuaria, PerfilEntrada, ConsentimientoEntrada
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
    from repositorio import RepositorioDeUsuaria, PerfilEntrada, ConsentimientoEntrada
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


@app.post("/puntuar-ofertas", dependencies=[Depends(requiere_clave_maquina)])
def puntuar_ofertas():
    """Thin route: scores every exempt user's pending offers (ADR-011)."""
    try:
        return puntuacion.puntuar_ofertas_core()
    except Exception as e:
        raise HTTPException(status_code=502, detail="Notion no disponible")



@app.get("/usuarios", dependencies=[Depends(requiere_clave_maquina)])
def usuarios(formato: str = None):
    """Consulta usuarios activos en Notion."""
    if not server.NOTION_DB_USUARIOS:
        raise HTTPException(status_code=500, detail="NOTION_DB_USUARIOS no configurada")
    try:
        results = notion.paginas_usuarios_activos()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if formato == "notion":
        return {"ok": True, "results": results}
    usuarios_list = []
    for p in results:
        props = p.get("properties", {})
        usuarios_list.append({
            "id":     p["id"],
            "nombre": props.get("Name", {}).get("title", [{}])[0].get("plain_text", ""),
            "email":  props.get("Email", {}).get("email", ""),
            "activo": props.get("Activo", {}).get("checkbox", False),
        })
    return {"ok": True, "usuarios": usuarios_list, "total": len(usuarios_list)}


class BuscarOfertasRequest(BaseModel):
    perfil: str = ""
    rol: str = ""
    stack: list = []
    salario_min: int = 0
    modalidad: list = []
    ciudad: str = ""
    top_n: int = 5


@app.post("/buscar-ofertas-reales", dependencies=[Depends(requiere_clave_maquina)])
def buscar_ofertas_reales(req: BuscarOfertasRequest):
    try:
        return real_jobs.buscar_ofertas_reales(
            perfil=req.perfil, rol=req.rol, stack=req.stack,
            salario_min=req.salario_min, modalidad=req.modalidad,
            ciudad=req.ciudad, top_n=req.top_n)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CrearOfertaRequest(BaseModel):
    email: str = ""
    empresa: str = Field(min_length=1)
    puesto: str = Field(min_length=1)
    descripcion: str = ""
    modalidad: str = ""
    ubicacion: str = ""
    salario: str = ""
    tipo_contrato: str = ""
    link: str = ""
    fecha_publicacion: str = ""
    logo_empresa: str = ""
    tags: list = []


@app.post("/crear-oferta", dependencies=[Depends(requiere_clave_maquina)])
def crear_oferta(req: CrearOfertaRequest):
    oferta = req.model_dump()
    if not oferta.get("empresa") or not oferta.get("puesto"):
        raise HTTPException(status_code=400, detail="empresa y puesto son requeridos")
    idioma = server.idioma_de_oferta(oferta["puesto"], oferta.get("descripcion", ""), oferta["empresa"])
    usuario_notion_id = ""
    if req.email:
        u = server.buscar_usuario_por_email(req.email)
        if u:
            usuario_notion_id = u.get("notion_id", "")
    try:
        page = server.crear_oferta_en_notion(oferta, idioma, usuario_notion_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"ok": True, "notion_page_id": page.get("id", ""), "idioma": idioma}


class BuscarParaUsuariaRequest(BaseModel):
    usuario_id: str = Field(min_length=1)
    email: str = ""
    top_n: int = 5


@app.post("/buscar-para-usuaria", dependencies=[Depends(requiere_clave_maquina)])
def buscar_para_usuaria(req: BuscarParaUsuariaRequest):
    if not base_de_datos.configurada():
        raise HTTPException(status_code=503, detail="BD no configurada")
    inicio = time.monotonic()
    usuario_id = req.usuario_id
    email = req.email.strip().lower() if req.email else ""
    try:
        with base_de_datos.motor().begin() as conexion:
            repo = RepositorioDeUsuaria(conexion, usuario_id)
            perfil = repo.obtener_perfil()
    except Exception:
        raise HTTPException(status_code=503, detail="BD no disponible")
    if perfil is None and email:
        try:
            with base_de_datos.motor().begin() as conexion:
                uid_interno = usuarias.id_por_emails([email], conexion)
            if uid_interno and uid_interno != usuario_id:
                usuario_id = uid_interno
                with base_de_datos.motor().begin() as conexion:
                    repo = RepositorioDeUsuaria(conexion, usuario_id)
                    perfil = repo.obtener_perfil()
        except Exception:
            pass
    if perfil is None:
        raise HTTPException(status_code=404, detail="perfil no encontrado")

    errores = []
    try:
        resultado = real_jobs.buscar_ofertas_reales(perfil=perfil, top_n=req.top_n)
    except Exception as e:
        errores.append(str(e))
        resultado = {"ok": False, "ofertas": [], "total_encontradas": 0, "total_filtradas": 0}

    usuario_notion_id = ""
    if email:
        u = server.buscar_usuario_por_email(email)
        if u:
            usuario_notion_id = u.get("notion_id", "")

    ofertas_creadas = 0
    notion_page_ids = []
    for oferta in (resultado.get("ofertas") or []):
        try:
            idioma = server.idioma_de_oferta(oferta.get("puesto", ""), oferta.get("descripcion", ""), oferta.get("empresa", ""))
            page = server.crear_oferta_en_notion(oferta, idioma, usuario_notion_id)
            pid = page.get("id", "") if isinstance(page, dict) else ""
            if pid:
                notion_page_ids.append(pid)
                oferta["notion_page_id"] = pid
            ofertas_creadas += 1
        except Exception as e:
            errores.append(f"notion: {oferta.get('empresa','?')}/{oferta.get('puesto','?')}")

    duracion_ms = int((time.monotonic() - inicio) * 1000)
    return {
        "ok": len(errores) == 0,
        "usuario_id": usuario_id,
        "ofertas_encontradas": resultado.get("total_encontradas", 0),
        "ofertas_creadas": ofertas_creadas,
        "notion_page_ids": notion_page_ids,
        "ofertas_descartadas": max(0, resultado.get("total_encontradas", 0) - resultado.get("total_filtradas", 0)),
        "errores": errores,
        "duracion_ms": duracion_ms,
        "ofertas": resultado.get("ofertas", []),
    }


class RegistroRequest(BaseModel):
    email: str = Field(min_length=1)


@app.post("/registro", dependencies=[Depends(requiere_clave_maquina)])
def registro(req: RegistroRequest):
    datos = req.model_dump()
    email = (req.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email requerido")
    try:
        perfil, creado, disparada = registrar_invitada(email, datos)
    except Exception:
        raise HTTPException(status_code=500, detail="no se pudo completar el registro")
    if not creado:
        mensaje = ("Ya estabas registrado. Buscando ofertas ahora mismo."
                   if disparada else
                   "Ya estabas registrado. No se pudo lanzar la búsqueda ahora; "
                   "entrarás en el barrido de las 9:00.")
    else:
        mensaje = ("Usuario registrado. Buscando tus primeras ofertas ahora mismo."
                   if disparada else
                   "Usuario registrado. Recibirás ofertas en el barrido de las 9:00.")
    return {"ok": True, "mensaje": mensaje, "email": email, "busqueda_disparada": disparada}


@app.get("/yo")
def yo(user=Depends(get_current_user)):
    """Quien es la usuaria que llama, segun su token de Google."""
    identidad, usuario_id = user
    estado_cuota = server.cuota.estado_de_usuaria(usuario_id, identidad.email)
    body = {"sub": identidad.sub, "email": identidad.email, "nombre": identidad.nombre}
    body.update(server._estado_del_perfil(usuario_id, identidad.email))
    body.update(server._consentimientos_de(usuario_id))
    if estado_cuota is not None:
        body["cuota"] = estado_cuota
    return body


@app.get("/perfil")
def leer_perfil(user=Depends(get_current_user)):
    identidad, usuario_id = user
    if usuario_id is None:
        raise HTTPException(status_code=403, detail="acceso no permitido")
    from repositorio import RepositorioDeUsuaria
    with base_de_datos.transaccion() as conexion:
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        perfil = repo.obtener_perfil()
    if perfil is None:
        raise HTTPException(status_code=404, detail="perfil no encontrado")
    return perfil


@app.put("/perfil")
def guardar_perfil(perfil: PerfilEntrada, user=Depends(get_current_user)):
    identidad, usuario_id = user
    if usuario_id is None:
        raise HTTPException(status_code=403, detail="acceso no permitido")
    from repositorio import RepositorioDeUsuaria
    with base_de_datos.transaccion() as conexion:
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        repo.guardar_perfil(perfil)
        return repo.obtener_perfil()


@app.post("/consentimientos", status_code=201)
def registrar_consentimiento(consentimiento: ConsentimientoEntrada, user=Depends(get_current_user)):
    identidad, usuario_id = user
    if usuario_id is None:
        raise HTTPException(status_code=403, detail="acceso no permitido")
    from repositorio import RepositorioDeUsuaria
    with base_de_datos.transaccion() as conexion:
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        repo.registrar_consentimiento(consentimiento.tipo, consentimiento.version)
    return {"tipo": consentimiento.tipo, "version": consentimiento.version}


@app.delete("/consentimientos/{tipo}")
def revocar_consentimiento(tipo: str, user=Depends(get_current_user)):
    if tipo not in ("almacenar_cv", "enviar_cv_a_ia"):
        raise HTTPException(status_code=422, detail="datos no validos")
    identidad, usuario_id = user
    if usuario_id is None:
        raise HTTPException(status_code=403, detail="acceso no permitido")
    from repositorio import RepositorioDeUsuaria
    with base_de_datos.transaccion() as conexion:
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        repo.revocar_consentimiento(tipo)
    return "", 204

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
