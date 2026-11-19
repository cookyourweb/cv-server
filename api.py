from dotenv import load_dotenv
load_dotenv()

"""API FastAPI del cv-server (ADR-001).

Capa HTTP tipada con Pydantic sobre la lógica de negocio de server.
Coexiste con Flask; se migra endpoint por endpoint. Servir con:  uvicorn api:app
"""
import hmac
import hashlib
import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import server
import usuarias
import cuota
from server import registrar_invitada
import puntuacion
import notion
import notion_resumen
import rag
import real_jobs
import base_de_datos
import time
import alta_core
import encaje_core
from repositorio import RepositorioDeUsuaria, PerfilEntrada, ConsentimientoEntrada, InteresEntrada
import base_de_datos
from server import CVError, generar_cv_core, generar_carta_core

app = FastAPI(title="cv-server API", version="0.1.0")

# Paridad con Flask: CVError -> {"ok": False, "error": ..., **extra} con el status del error.
@app.exception_handler(CVError)
async def _cv_error_handler(request, exc):
    return JSONResponse(status_code=exc.status, content={"ok": False, "error": exc.message, **exc.extra})

# CORS: replica de server.py (_RUTAS_CON_CORS). En FastAPI se aplica globalmente;
# las rutas de máquina (n8n) no pasan por aquí porque no envían Origin.
_ORIGENES = [o.strip() for o in (server.ORIGENES_PERMITIDOS or []) if o.strip()]
if "http://localhost:4200" not in _ORIGENES:
    _ORIGENES.append("http://localhost:4200")
if "http://127.0.0.1:4200" not in _ORIGENES:
    _ORIGENES.append("http://127.0.0.1:4200")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGENES,
    allow_origin_regex=r"https://panel-empleo-[A-Za-z0-9-]+-cookyourwebs-projects\.vercel\.app",
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

class AjusteDeExtraccion(BaseModel):
    activa: bool

class EncajesRequest(BaseModel):
    ids: list[str] = []

class RagPregunta(BaseModel):
    email: str = Field(min_length=1)
    pregunta: str = Field(min_length=1)
    idioma: str = "es"
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
    if usuario_id is None:
        raise HTTPException(status_code=401, detail="usuario no registrado en la base de datos")
    from repositorio import RepositorioDeUsuaria, PerfilEntrada, ConsentimientoEntrada, InteresEntrada
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
    if usuario_id is None:
        raise HTTPException(status_code=401, detail="usuario no registrado en la base de datos")
    from repositorio import RepositorioDeUsuaria, PerfilEntrada, ConsentimientoEntrada, InteresEntrada
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
    if usuario_id is None:
        raise HTTPException(status_code=401, detail="usuario no registrado en la base de datos")
    from repositorio import RepositorioDeUsuaria, PerfilEntrada, ConsentimientoEntrada, InteresEntrada
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
        import logging; logging.getLogger(__name__).warning("usuarios: error %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="servicio no disponible")
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
        import logging; logging.getLogger(__name__).warning("buscar_ofertas_reales: error %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="servicio no disponible")


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
        import logging; logging.getLogger(__name__).warning("crear_oferta: error %s", type(e).__name__)
        raise HTTPException(status_code=502, detail="servicio no disponible")
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

    # T7: cuota Neon — no procesar si la usuaria agotó su cuota (solo no exentas).
    if not cuota.es_exenta(email or ""):
        estado = cuota.estado_de_usuaria(usuario_id, email or "")
        if estado is not None and estado.get("unidades_restantes", 1) <= 0:
            raise HTTPException(status_code=429, detail="cuota agotada")

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


@app.post("/interes", status_code=201)
def registrar_interes(interes: InteresEntrada, user=Depends(get_current_user)):
    identidad, usuario_id = user
    if usuario_id is None:
        raise HTTPException(status_code=403, detail="acceso no permitido")
    from repositorio import RepositorioDeUsuaria
    with base_de_datos.transaccion() as conexion:
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        organizacion = repo.registrar_interes(interes.tipo, interes.organizacion)
    return {"tipo": interes.tipo, "organizacion": organizacion}


@app.delete("/cuenta", status_code=204)
def borrar_cuenta(user=Depends(get_current_user)):
    identidad, usuario_id = user
    if usuario_id is None:
        raise HTTPException(status_code=403, detail="acceso no permitido")
    from repositorio import RepositorioDeUsuaria
    with base_de_datos.transaccion() as conexion:
        repo = RepositorioDeUsuaria(conexion, usuario_id)
        ok = repo.borrar_cuenta()
    if not ok:
        raise HTTPException(status_code=404, detail="no encontrado")
    return ""


@app.get("/buscar-para-usuaria/progress")
async def buscar_para_usuaria_progress(usuario_id: str, email: str = "", top_n: int = 5, token: str = ""):
    """SSE: emite progreso de la búsqueda en tiempo real.

    EventSource no puede enviar cabeceras, así que el token de máquina va en la URL
    (?token=...). Se valida con comparación en tiempo constante (fail-closed).
    """
    import hmac
    clave = server.CLAVE_MAQUINA
    autorizado = bool(clave) and hmac.compare_digest(token.encode(), clave.encode())
    # Opcion B: aceptar tambien un JWT de Google del panel (token en URL por EventSource).
    if not autorizado and token:
        try:
            identidad = server.identificar(f"Bearer {token}", server.CONFIG_OIDC, server.CLAVES)
            # The token says who the caller is: the search runs for the Neon user
            # that owns the token's email, never for the usuario_id in the query
            # (the panel sends its Google sub there). That also rules out IDOR.
            if (identidad.email or "").strip().lower():
                if base_de_datos.configurada():
                    with base_de_datos.transaccion() as conexion:
                        uid = usuarias.id_por_emails([identidad.email], conexion)
                        if uid is not None:
                            usuario_id = str(uid)
                            autorizado = True
                else:
                    # Modo heredado: aceptar si el email del token coincide con el param email.
                    if email and identidad.email.strip().lower() == email.strip().lower():
                        autorizado = True
        except Exception:
            autorizado = False
    if not autorizado:
        raise HTTPException(status_code=401, detail="no autorizado")
    import asyncio, json, threading

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    def enqueue(event):
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def progress_cb(event):
        enqueue(event)

    def worker():
        try:
            import base_de_datos, real_jobs
            from repositorio import RepositorioDeUsuaria
            if not base_de_datos.configurada():
                enqueue({"stage": "error", "detail": "BD no configurada"})
                return
            with base_de_datos.motor().begin() as conexion:
                repo = RepositorioDeUsuaria(conexion, usuario_id)
                perfil = repo.obtener_perfil()
            if perfil is None:
                enqueue({"stage": "error", "detail": "perfil no encontrado"})
                return
            resultado = real_jobs.buscar_ofertas_reales(perfil=perfil, top_n=top_n, progress_cb=progress_cb)
            enqueue({"stage": "done", "summary": {"ok": resultado.get("ok"), "creadas": len(resultado.get("ofertas", []))}})
        except Exception as e:
            enqueue({"stage": "error", "detail": "error interno"})
        finally:
            enqueue(None)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    async def event_stream():
        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"
            await asyncio.sleep(0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.get("/health")
def health():
    return {
        "ok": True,
        "status": "ok",
        "version": "v2.4",
        "modelos": {
            "cv": server.CV_MODEL,
            "carta": server.CARTA_MODEL,
            "fallback": server.GROQ_MODEL,
        },
        "fallbacks": {
            "gemini": bool(server.GEMINI_API_KEY),
            "claude": bool(server.CLAUDE_API_KEY),
        },
        "deploy": {
            "branch": os.environ.get("RENDER_GIT_BRANCH", "local"),
            "commit": (os.environ.get("RENDER_GIT_COMMIT", "") or "")[:7],
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


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


@app.get("/resumen-pendientes", dependencies=[Depends(requiere_clave_maquina)])
def resumen_pendientes():
    """Resumen operativo (solo lectura) de las ofertas en estado 'Pendiente' del CRM de Notion.

    Devuelve Markdown legible + total + número de incompletas. No modifica Notion.
    """
    import logging
    log = logging.getLogger(__name__)
    try:
        ofertas = notion_resumen.listar_ofertas_pendientes()
    except Exception as e:
        log.warning("resumen_pendientes: Notion falló: %s", type(e).__name__)
        raise HTTPException(status_code=502, detail="No se pudo leer Notion")
    markdown = notion_resumen.resumen_pendientes_markdown(ofertas)
    incompletas = sum(1 for o in ofertas if notion_resumen.es_incompleta(o))
    return {"ok": True, "markdown": markdown, "total": len(ofertas), "incompletas": incompletas}


@app.post("/rag/preguntar")
def rag_preguntar(req: RagPregunta, user=Depends(get_current_user)):
    """RAG con citas sobre el CV master de la usuaria. Delega en rag.py.

    La identidad del token es la fuente de verdad para el email (anti-IDOR):
    se ignora req.email si no coincide.
    """
    identidad, usuario_id = user
    email = (identidad.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="no autorizado")
    if req.email and req.email.strip().lower() != email:
        raise HTTPException(status_code=403, detail="no autorizado")
    usuario = server.buscar_usuario_por_email(email)
    if not usuario:
        raise HTTPException(status_code=404, detail="usuario no encontrado")
    try:
        master = server._resolver_master(usuario, req.idioma, email)
        cv_texto = master.texto
    except Exception:
        cv_texto = ""
    if not cv_texto:
        raise HTTPException(status_code=404, detail="no hay CV master")
    try:
        return rag.preguntar_cv(email, req.pregunta, cv_texto)
    except CVError as e:
        raise HTTPException(status_code=e.status, detail=e.message)


@app.post("/extraccion")
def extraer_perfil(user=Depends(get_current_user)):
    """Extracción owner-paid del perfil. Delega en alta_core (body ignorado)."""
    _identidad, usuario_id = user
    return alta_core.extraer_perfil_core(usuario_id)


@app.post("/cv", status_code=201)
def subir_cv(archivo: UploadFile = File(...), user=Depends(get_current_user)):
    """Sube y cifra un CV. Delega en alta_core (consentimiento antes de parsear)."""
    identidad, usuario_id = user
    # Tope a nivel de framework (3 MB) antes de leer completo (REQ: LIMITE_BYTES=2 MB lógico).
    LIMITE_FRAMEWORK = 3 * 1024 * 1024
    contenido = archivo.file.read(LIMITE_FRAMEWORK + 1)
    if len(contenido) > LIMITE_FRAMEWORK:
        raise HTTPException(status_code=413, detail="archivo demasiado grande")
    return alta_core.subir_cv_core(usuario_id, contenido)


@app.get("/ofertas/{oferta_id}/encaje")
def encaje_de_oferta(oferta_id: str, user=Depends(get_current_user)):
    identidad, usuario_id = user
    return encaje_core.encaje_de_oferta_core(usuario_id, identidad.email, oferta_id)


@app.post("/encajes")
def encajes_batch(req: EncajesRequest, user=Depends(get_current_user)):
    identidad, usuario_id = user
    return encaje_core.encajes_batch_core(usuario_id, identidad.email, req.ids)


@app.get("/cv")
def listar_cvs(user=Depends(get_current_user)):
    """Lista los CVs guardados (solo metadatos). Delega en alta_core."""
    _identidad, usuario_id = user
    return alta_core.listar_cvs_core(usuario_id)


@app.delete("/cv/{idioma}", status_code=204)
def borrar_cv(idioma: str, user=Depends(get_current_user)):
    """Borra el CV del idioma indicado. Delega en alta_core."""
    _identidad, usuario_id = user
    alta_core.borrar_cv_core(usuario_id, idioma)
    return None


@app.put("/ajustes/extraccion", dependencies=[Depends(requiere_clave_maquina)])
def fijar_extraccion(req: AjusteDeExtraccion):
    """Kill switch del gasto de extracción (solo machine key). Delega en alta_core."""
    return alta_core.fijar_extraccion_core(req.activa)

