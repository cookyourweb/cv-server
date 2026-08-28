#!/usr/bin/env python3
"""
server.py  —  v2.3-groq
LLM: Groq (primario) → Gemini (fallback) → Claude (fallback)

Formulario multi-pantalla:
  1a. Email only → detecta si existe
  2a. Si existe → "¡Hola de nuevo!" + botones Buscar ahora / Mañana 9am
  1.  Si nuevo → formulario completo + botón Buscar ahora
"""

import os
import io
import re
import logging
import requests
from datetime import datetime, timezone
from typing import NamedTuple
from flask import Flask, request, jsonify, render_template, make_response

# Google Drive / OAuth
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Claude (calidad — CV y textos que van a empresas)
import anthropic

# DOCX
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

# Búsqueda de ofertas reales (Fase 3.0)
from real_jobs import buscar_ofertas_reales

# ─────────────────────────────────────────────
# CONFIGURACIÓN — solo variables de entorno
# ─────────────────────────────────────────────

# Los modelos y sus claves viven en `llm.py`, que es quien los usa. Aqui estaban
# duplicados: dos definiciones del mismo valor acaban separandose siempre.

# Las credenciales y carpetas de Drive viven en `drive.py`, que es quien las usa.

# ── Notion ────────────────────────────────────
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_DB_USUARIOS = os.getenv("NOTION_DB_USUARIOS", "")
NOTION_DB_OFERTAS  = os.getenv("NOTION_DB_OFERTAS", "33d11515-f4b2-8176-947b-000bbafd1ca7")

# ── Webhooks n8n ──────────────────────────────
# OJO (28ago2026): los paths `buscar-ahora` y `nuevo-usuario` NO EXISTEN en la
# instancia. Se barrieron los 10 workflows nodo a nodo. Lo que la documentacion
# llamaba WF1 nunca llego a estar dado de alta, y estas llamadas se comian un 404
# en silencio. El unico webhook vivo que lanza una busqueda para un usuario es
# `buscar-para-user`, dentro del workflow de PROD `CsvmtPcLVmGIZg6C`.
N8N_HOST = os.getenv("N8N_HOST", "https://n8n-asistente-correo.onrender.com")
WEBHOOK_BUSCAR_AHORA = os.getenv(
    "WEBHOOK_BUSCAR_AHORA", f"{N8N_HOST}/webhook/buscar-para-user"
)

# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Configuracion: se lee, pero su ausencia NO impide importar ────────────────
# Antes cada modulo hacia `os.environ["CLAVE"]` a nivel de modulo, o sea que
# exigia el entorno para poder IMPORTARSE. Dos consecuencias medidas: la suite
# tenia que inyectar credenciales falsas antes de empezar, y nadie podia abrir el
# repositorio e importar `guardrails` para leer que hace sin montarse un `.env`.
#
# Ahora la validacion vive aqui, en el unico sitio donde importa de verdad, y
# reporta TODAS las que faltan de una vez en vez de reventar con la primera.
CREDENCIALES_REQUERIDAS = (
    "GROQ_API_KEY",
    "NOTION_TOKEN",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
)


def credenciales_que_faltan(entorno=None) -> list:
    """Las credenciales requeridas que no estan puestas o estan vacias."""
    entorno = os.environ if entorno is None else entorno
    return [c for c in CREDENCIALES_REQUERIDAS if not (entorno.get(c) or "").strip()]


_faltan = credenciales_que_faltan()
if _faltan:
    logger.error(
        "FALTAN CREDENCIALES: %s. El servicio arranca igual, pero fallara en la "
        "primera peticion que las necesite.", ", ".join(_faltan),
    )


app = Flask(__name__)


class CVError(Exception):
    """Error de negocio del cv-server: status HTTP + mensaje.

    El core (generar_cv_core, ...) la lanza; cada capa HTTP (Flask/FastAPI)
    la mapea a su formato de respuesta. Ver docs/ADR-001."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ══════════════════════════════════════════════
# CAPA LLM — Groq primario, Gemini/Claude fallback
# ══════════════════════════════════════════════

# La capa LLM vive en `llm.py`. Se reexporta para no cambiar la superficie
# publica del modulo.
from llm import (  # noqa: F401
    CARTA_MODEL,
    CLAUDE_API_KEY,
    CLAUDE_MODEL,
    CV_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    RespuestaLLM,
    call_claude,
    call_llm,
    call_llm_calidad,
    get_anthropic_client,
)



# Los guardrails viven en `guardrails.py`. Se reexportan aqui para no cambiar la
# superficie publica del modulo: los endpoints y los tests los siguen viendo en
# `server`.
import guardrails
from guardrails import (  # noqa: F401
    DESCRIPCION_MINIMA,
    construir_titular,
    detectar_cifras_no_respaldadas,
    detectar_experiencia_mal_atribuida,
    detectar_skills_no_respaldadas,
    detectar_tecnologias_no_respaldadas,
    detectar_titular_fuera_de_contrato,
    evaluar_descripcion_oferta,
    _TEC_ALIAS,
    _TEC_PATRONES,
    _tecnologias_en,
)


# ══════════════════════════════════════════════
# GOOGLE DRIVE
# ══════════════════════════════════════════════

# El acceso a Drive vive en `drive.py`. Se reexporta para no cambiar la
# superficie publica del modulo.
from drive import (  # noqa: F401
    FOLDER_CV_GENERADOS,
    FOLDER_CV_MASTERS,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REFRESH_TOKEN,
    MasterCV,
    MasterElegido,
    elegir_master,
    get_drive_service,
    leer_cv_master_desde_drive,
    subir_cv_a_drive,
)



# ══════════════════════════════════════════════
# IDIOMA
# ══════════════════════════════════════════════

import re as _re_idioma

_ES_ACENTOS = _re_idioma.compile(r"[ñáéíóúü¿¡]", _re_idioma.IGNORECASE)
_ES_PALABRAS = {
    "experiencia", "equipo", "desarrollo", "empresa", "puesto", "requisitos",
    "conocimientos", "años", "trabajo", "ofrecemos", "buscamos", "gestión",
    "liderazgo", "desarrollador", "programador", "aplicaciones", "datos",
    "proyecto", "cliente", "habilidades", "capacidad", "valorable",
    "imprescindible", "nivel", "sector", "jornada", "remoto",
}
_EN_PALABRAS = {
    "experience", "team", "development", "company", "position", "requirements",
    "skills", "years", "work", "we", "you", "our", "developer", "engineer",
    "manage", "ability", "strong", "knowledge", "including", "required",
    "preferred", "remote", "build", "design", "role", "looking",
}


def _señales_idioma(texto: str) -> tuple:
    """Cuenta señales de español e inglés en un texto. Devuelve (es, en).
    Los acentos y signos ¿¡ pesan doble: son señal fuerte de español."""
    t = (texto or "").lower()
    if not t.strip():
        return (0, 0)
    palabras = set(_re_idioma.findall(r"[a-záéíóúñü]+", t))
    es = len(_ES_ACENTOS.findall(t)) * 2
    es += sum(1 for w in _ES_PALABRAS if w in palabras)
    en = sum(1 for w in _EN_PALABRAS if w in palabras)
    return (es, en)


def detectar_idioma(*textos) -> str:
    """Heuristica simple: devuelve 'es' o 'en' segun señales del texto de la oferta.
    Empate -> 'es' (mercado principal de la usuaria)."""
    es = en = 0
    for t in textos:
        e, n = _señales_idioma(t)
        es += e
        en += n
    return "en" if en > es else "es"


def idioma_de_oferta(puesto: str, descripcion: str, empresa: str) -> str:
    """Idioma del anuncio, priorizando el PUESTO.

    El titulo del puesto viene tal cual del anuncio, en su idioma. La descripcion,
    en cambio, la reescribe la tarea programada casi siempre en español, asi que
    ahogaba la señal del titulo (caso Revolut, 23jul2026: titulo ingles, carta en
    español). El puesto pesa x3, pero no es absoluto: una descripcion con señal
    española muy marcada todavia puede ganar (oferta española titulada en ingles).

    Un idioma explicito (body o campo Idioma de Notion) manda sobre esta deteccion:
    esta funcion es solo el ultimo recurso. Empate y vacio -> 'es'."""
    es_p, en_p = _señales_idioma(puesto)
    if es_p != en_p:
        # El titulo tiene señal neta: manda. No lo contamina la descripcion.
        return "en" if en_p > es_p else "es"
    # Titulo vacio o ambiguo: caemos a la descripcion y la empresa.
    es_d, en_d = _señales_idioma(descripcion)
    es_e, en_e = _señales_idioma(empresa)
    return "en" if (en_d + en_e) > (es_d + es_e) else "es"


def _slug(texto: str) -> str:
    """Slug en minúsculas sin acentos para nombres de archivo."""
    s = (texto or "").lower().strip()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"),
                 ("ú", "u"), ("ñ", "n"), ("ü", "u")):
        s = s.replace(a, b)
    s = _re_idioma.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _nombre_archivo_cv(nombre: str, puesto: str) -> str:
    """Convención: cv-<nombre>-<puesto>-<año>.docx (ej: cv-veronica-serna-frontend-developer-2026.docx)."""
    partes = ["cv", _slug(nombre) or "candidato"]
    puesto_slug = _slug(puesto)
    if puesto_slug:
        partes.append(puesto_slug)
    partes.append(str(datetime.now(timezone.utc).year))
    return "-".join(partes) + ".docx"


def _tiene_algun_master(usuario: dict) -> bool:
    """True si el usuario tiene configurado un master en cualquier idioma."""
    return bool(
        (usuario.get("cv_master_file_id") or "").strip()
        or (usuario.get("cv_master_url") or "").strip()
        or (usuario.get("cv_master_url_es") or "").strip()
    )


# ══════════════════════════════════════════════
# NOTION
# ══════════════════════════════════════════════

# El acceso a Notion vive en `notion.py`. Se reexporta para no cambiar la
# superficie publica del modulo.
from notion import (  # noqa: F401
    CAMPO_EMAILS_ALIAS,
    _ALIAS_ACEPTADOS,
    _SEPARADORES_EMAIL,
    _ES_EMAIL,
    notion_headers,
    _es_campo_de_alias,
    campos_alias_candidatos,
    emails_de_usuario,
    usuario_tiene_email,
    _consultar_usuario,
    usuario_atiende,
    buscar_usuario_por_email,
    buscar_oferta_en_notion,
    guardar_link_cv_en_notion,
    _extraer_drive_file_id,
    crear_usuario_en_notion,
    crear_oferta_en_notion,
)



# ══════════════════════════════════════════════
# GENERACIÓN DOCX
# ══════════════════════════════════════════════

# El render del DOCX vive en `docx_render.py`. Se reexporta para no cambiar la
# superficie publica del modulo.
from docx_render import (  # noqa: F401
    generar_docx,
    generar_docx_con_cabecera,
    sanear_tipografia,
)
# El formulario de alta vive en `templates/alta.html`. Estaba aqui dentro como
# 237 lineas de HTML, CSS y JavaScript en una cadena de Python, en el mismo
# fichero que los prompts y la logica de Notion.



# ══════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════

@app.route("/")
def index():
    # Sin cache. El HTML lleva dentro el JavaScript del formulario, asi que una
    # pagina cacheada es LOGICA cacheada: el 28-ago-2026 se desplego el arreglo
    # del mensaje de "Buscar ahora" y el navegador siguio ejecutando la version
    # anterior. Son 8 KB: no hay nada que ahorrar cacheandolo.
    respuesta = make_response(render_template("alta.html"))
    respuesta.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return respuesta


@app.route("/health")
def health():
    return jsonify({
        "status":       "ok",
        "version":      "v2.4",
        # QUE MODELO escribe cada cosa, leido de las variables reales. Antes esto
        # devolvia las constantes "groq" y "v2.3-groq", que era falso: Groq es solo el
        # fallback si Claude falla. Sin esto no se puede verificar desde fuera un
        # cambio de CV_MODEL en Render, que es justo cuando mas falta hace.
        "modelos":      {
            "cv":       CV_MODEL,
            "carta":    CARTA_MODEL,
            "fallback": GROQ_MODEL,
        },
        "fallbacks":    {
            "gemini":  bool(GEMINI_API_KEY),
            "claude":  bool(CLAUDE_API_KEY),
        },
        "deploy":       {
            "branch": os.environ.get("RENDER_GIT_BRANCH", "local"),
            "commit": (os.environ.get("RENDER_GIT_COMMIT", "") or "")[:7],
        },
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    })


@app.route("/debug")
def debug():
    """Prueba rápida del LLM activo (Groq primero)."""
    try:
        r = call_llm("Responde solo: 'Groq funcionando correctamente en cv_server v2.3'")
        return jsonify({"ok": True, "respuesta": r.contenido, "modelo": r.modelo})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/check-email", methods=["POST"])
def check_email():
    """Comprueba si un email ya existe en Notion. Devuelve {existe, nombre}."""
    datos = request.get_json(force=True)
    email = (datos.get("email") or "").strip().lower()
    if not email:
        return jsonify({"existe": False, "error": "email requerido"}), 400

    try:
        usuario = buscar_usuario_por_email(email)
    except Exception as e:
        logger.error("Error check-email: %s", e)
        return jsonify({"existe": False, "error": str(e)}), 500

    if usuario and usuario.get("activo"):
        return jsonify({
            "existe": True,
            "nombre": usuario.get("nombre", ""),
            "email":  email,
        })
    return jsonify({"existe": False, "email": email})


def payload_buscar_para_user(usuario: dict) -> dict:
    """Traduce un usuario al contrato que espera el webhook `buscar-para-user`.

    El contrato no es invento: es el que produce el nodo `Code — Normalizar users
    (schedule)` del workflow de PROD, que es por donde entra el disparo de las 9:00.
    Dos nombres NO coinciden con los del perfil que devuelve Notion, y por eso
    existe esta funcion: `Salario min` viaja como `salario`, y el id de la pagina
    como `user_id`.

    Acepta las dos formas del usuario: la que devuelve `buscar_usuario_por_email`
    y la cruda del formulario de alta (`rol_objetivo`, `salario`).
    """
    u = usuario or {}
    return {
        "user_id":       u.get("notion_id") or u.get("user_id") or "",
        "nombre":        u.get("nombre", ""),
        "email":         u.get("email", ""),
        "email_usuario": u.get("email", ""),
        "perfil":        u.get("perfil", ""),
        "rol":           u.get("rol") or u.get("rol_objetivo") or "",
        "stack":         u.get("stack") or [],
        "salario":       u.get("salario_min") or u.get("salario") or 0,
        "modalidad":     u.get("modalidad") or [],
        "ciudad":        u.get("ciudad", ""),
        "linkedin":      u.get("linkedin", ""),
        "cv_master_url": u.get("cv_master_url", ""),
        "source":        "cv-server",
    }


def disparar_busqueda(usuario: dict) -> bool:
    """Pide a n8n una búsqueda para este usuario. Devuelve si n8n la aceptó.

    Devuelve un bool a propósito. Antes esto era fire & forget con un `warning`
    y quien llamaba no tenía forma de saber si había pasado algo, así que la API
    respondía `ok: true` con el webhook devolviendo 404. Un 404 aquí significa
    que el path no está dado de alta en n8n: es un fallo de configuración que hay
    que ver, no un aviso que se traga el log.
    """
    if not usuario or not WEBHOOK_BUSCAR_AHORA:
        logger.error("Búsqueda NO disparada: falta usuario o WEBHOOK_BUSCAR_AHORA")
        return False
    try:
        # 45s, no 8. El webhook esta en `responseMode: lastNode`: n8n no contesta
        # hasta terminar los 15 nodos (Notion + tres fuentes de ofertas). Medido en
        # produccion el 28-ago-2026: 10,7s con la instancia caliente. Con 8s el
        # servidor se rendia antes de tiempo y la pantalla decia que la busqueda no
        # se habia lanzado cuando SI se habia lanzado y acabo en success.
        r = requests.post(
            WEBHOOK_BUSCAR_AHORA, json=payload_buscar_para_user(usuario), timeout=45
        )
    except Exception as e:
        logger.error("Búsqueda NO disparada, n8n no responde (%s): %s", WEBHOOK_BUSCAR_AHORA, e)
        return False
    if r.status_code >= 400:
        logger.error(
            "Búsqueda NO disparada, n8n devolvió %s en %s. Un 404 aquí = el webhook "
            "no existe en la instancia.", r.status_code, WEBHOOK_BUSCAR_AHORA,
        )
        return False
    logger.info("Búsqueda disparada para %s", usuario.get("email", ""))
    return True


@app.route("/accion-existente", methods=["POST"])
def accion_existente():
    """Usuario existente pulsa 'Buscar ahora' o 'Mañana 9am'."""
    datos = request.get_json(force=True)
    email = (datos.get("email") or "").strip().lower()
    accion = datos.get("accion", "")

    if not email:
        return jsonify({"ok": False, "error": "email requerido"}), 400

    disparada = False
    if accion == "ahora":
        # El perfil hace falta ENTERO: mandando solo email y nombre, n8n buscaba
        # ofertas sin rol, sin stack y sin salario, o sea para nadie.
        try:
            usuario = buscar_usuario_por_email(email)
        except Exception as e:
            logger.error("No se pudo leer el usuario %s en Notion: %s", email, e)
            usuario = None
        disparada = disparar_busqueda(usuario)

    return jsonify({
        "ok": True,
        "accion": accion,
        "email": email,
        "busqueda_disparada": disparada,
    })


@app.route("/registro", methods=["POST"])
def registro():
    """Registra usuario nuevo en Notion y dispara webhook n8n."""
    datos = request.get_json(force=True)
    email = (datos.get("email") or "").strip().lower()
    if not email:
        return jsonify({"ok": False, "error": "email requerido"}), 400

    # Si ya existe, no duplicar
    try:
        existente = buscar_usuario_por_email(email)
    except Exception:
        existente = None

    if existente:
        # Usuario ya existe → disparar búsqueda igual
        disparada = disparar_busqueda(existente)
        return jsonify({
            "ok": True,
            "mensaje": ("Ya estabas registrado. Buscando ofertas ahora mismo."
                        if disparada else
                        "Ya estabas registrado. No se pudo lanzar la búsqueda ahora; "
                        "entrarás en el barrido de las 9:00."),
            "email": email,
            "busqueda_disparada": disparada,
        })

    # Crear en Notion
    try:
        notion_page = crear_usuario_en_notion(datos)
        notion_id = notion_page.get("id", "")
    except Exception as e:
        logger.error("Notion error: %s", e)
        return jsonify({"ok": False, "error": f"Error creando usuario en Notion: {e}"}), 500

    # El alta ya está hecha en Notion. Esto lanza la primera búsqueda: iba al
    # webhook `nuevo-usuario`, que no existe, así que quien se registraba no
    # recibía nada hasta el barrido de las 9:00 del día siguiente.
    disparada = disparar_busqueda({**datos, "notion_id": notion_id})

    return jsonify({
        "ok":      True,
        "mensaje": ("Usuario registrado. Buscando tus primeras ofertas ahora mismo."
                    if disparada else
                    "Usuario registrado. Recibirás ofertas en el barrido de las 9:00."),
        "email":   email,
        "busqueda_disparada": disparada,
    })


def generar_cv_core(email: str, empresa: str, puesto: str,
                    descripcion: str = "", idioma_in: str = "") -> dict:
    """Núcleo de /generar-cv (sin Flask): orquesta Notion/Drive/LLM y devuelve
    el dict de respuesta. Lanza CVError(status, msg) en los errores. Lo comparten
    la ruta Flask y la ruta FastAPI. Ver docs/ADR-001."""
    if not email or not empresa or not puesto:
        raise CVError(400, "email, empresa y puesto son requeridos")

    # Idioma autoritativo: el que n8n decidió de la descripción REAL al crear la
    # oferta (la de Notion suele ser un resumen en español que confunde la
    # detección). Prioridad: body.idioma > Idioma guardado en Notion > detección.
    idioma_in = (idioma_in or "").strip().lower()
    if not descripcion.strip() or idioma_in not in ("en", "es"):
        oferta = buscar_oferta_en_notion(empresa, puesto)
        if oferta:
            descripcion = descripcion or oferta.get("descripcion", "")
            idioma_in = idioma_in or (oferta.get("idioma") or "").strip().lower()

    # 1. Leer perfil completo del usuario desde Notion
    usuario = buscar_usuario_por_email(email)
    if not usuario:
        raise CVError(404, f"Usuario {email} no encontrado en Notion")

    nombre = usuario.get("nombre") or email.split("@")[0]

    # 2. Resolver idioma y leer el CV master en ese idioma
    idioma = idioma_in if idioma_in in ("en", "es") else idioma_de_oferta(puesto, descripcion, empresa)
    tiene_master_configurado = _tiene_algun_master(usuario)
    try:
        master     = leer_cv_master_desde_drive(usuario, idioma)
        cv_master  = master.texto
    except Exception as e:
        # get_drive_service() -> creds.refresh() puede fallar (token caducado)
        # ANTES del try interno de la lectura: sin este guard, sale un 500 HTML
        # opaco. Devolvemos el error REAL en JSON para poder diagnosticar.
        logger.error("Drive auth/lectura falló en /generar-cv: %s", e)
        raise CVError(502, f"No se pudo autenticar/leer el CV master en Drive: {e}")

    # Guardrail: si hay un master configurado pero lo leído es ilegible
    # (basura binaria de un .docx sin parsear, o sin acceso), NO generamos
    # nada. Mejor fallar claro que mandar un CV con datos inventados.
    def _es_legible(t: str) -> bool:
        if not t:
            return False
        if t.lstrip().startswith("PK"):  # firma ZIP de un .docx no parseado
            return False
        imprimibles = sum(1 for c in t if c.isprintable() or c in "\n\r\t")
        return imprimibles / len(t) >= 0.85

    if tiene_master_configurado and not _es_legible(cv_master):
        logger.error("CV master ILEGIBLE para %s (largo=%d) — abortando para no inventar",
                     email, len(cv_master or ""))
        raise CVError(502, "No se pudo leer tu CV master desde Drive (archivo ilegible o sin acceso). "
                           "NO se generó un CV para evitar enviar datos inventados. "
                           "Revisá el archivo y los permisos en Drive.")

    if cv_master:
        logger.info("CV master leído (%d chars) para %s", len(cv_master), email)
    else:
        logger.warning("CV master no encontrado para %s — usando solo perfil de Notion", email)

    # 3. Construir contexto del candidato
    ciudad = usuario.get("ciudad", "Madrid")
    rol    = usuario.get("rol", "")
    stack  = ", ".join(usuario.get("stack", [])) or "React, TypeScript"

    # 4. Prompt con 4 fases + CV master real
    if cv_master:
        contexto_candidato = f"""CV MASTER COMPLETO (usa SOLO esta experiencia, NO inventes):
{cv_master}"""
    else:
        contexto_candidato = f"""PERFIL DEL CANDIDATO (sin CV master disponible):
- Nombre: {nombre}
- Rol objetivo: {rol}
- Stack: {stack}
- Ciudad: {ciudad}
- Perfil: {usuario.get("perfil", "")}"""

    # Titulos de seccion y regla de idioma, en el idioma de la oferta
    idioma_nombre = "English" if idioma == "en" else "Spanish"
    if idioma == "en":
        bloque_formato = """OUTPUT FORMAT (plain text, no markdown):

HEADLINE: [professional title for this offer — see HEADLINE RULES below]

PROFESSIONAL SUMMARY
[2 full paragraphs (4-6 lines each) tailored to the offer, generated from her REAL EXPERIENCE (never copied from PERFIL BASE). Write with NO GRAMMATICAL SUBJECT, standard English CV style: "Frontend Tech Lead with 10+ years...", "Led the migration...". NEVER "She is", "She brings", "Her career spans", and never "I am". First paragraph: the profile itself + core strengths relevant to this role. Second paragraph: depth, domains and the angle that fits this offer.]

PROFESSIONAL EXPERIENCE
[Role] — [Company]
[Start date] - [End date]
- Real achievement from the CV master, XYZ formula, prioritised by relevance
- Real achievement from the CV master, XYZ formula, prioritised by relevance
- Real achievement from the CV master, XYZ formula, prioritised by relevance
- Real achievement from the CV master, XYZ formula, prioritised by relevance
- Real achievement from the CV master, XYZ formula, prioritised by relevance
- Real achievement from the CV master, XYZ formula, prioritised by relevance
(6-9 bullets for recent/relevant roles, 3-4 for older ones — always real, never padded)

TECHNICAL SKILLS
[Skills grouped by category (Frontend, AI, Design Systems, Backend, Cloud, Testing...) with concrete tools/versions, ordered by relevance to this offer]

EDUCATION
[From the CV master]

LANGUAGES
[From the CV master]

FINAL RULES:
- First line MUST be "HEADLINE: ..." — it becomes the header title
- Do NOT include name/email/phone, they are added programmatically
- Do NOT use markdown (**text**, ##, ```)
- Do NOT invent anything not in the CV master
- EXPERIENCE reads as a career story told through ROLES: the job title opens every entry and the company follows it. A recruiter must be able to scan the left edge and see the progression (Tech Lead, then Front-End Developer, then Designer). Never lead with the company.
- Language: the ENTIRE CV must be in English (section titles and content)"""
    else:
        bloque_formato = """FORMATO DE SALIDA (texto plano, sin markdown):

HEADLINE: [titular profesional para esta oferta — ver REGLAS DEL HEADLINE abajo]

PERFIL PROFESIONAL
[2 párrafos completos (4-6 líneas cada uno) adaptados a la oferta, generados desde su EXPERIENCIA real (NUNCA copiados del PERFIL BASE). Primer párrafo: quién es + fortalezas clave relevantes para este puesto. Segundo párrafo: profundidad, dominios y el ángulo que encaja con esta oferta.]

EXPERIENCIA PROFESIONAL
[Puesto] — [Empresa]
[Fecha inicio] - [Fecha fin]
- Logro real del CV master, fórmula XYZ, priorizado por relevancia
- Logro real del CV master, fórmula XYZ, priorizado por relevancia
- Logro real del CV master, fórmula XYZ, priorizado por relevancia
- Logro real del CV master, fórmula XYZ, priorizado por relevancia
- Logro real del CV master, fórmula XYZ, priorizado por relevancia
- Logro real del CV master, fórmula XYZ, priorizado por relevancia
(6-9 bullets en los puestos recientes/relevantes, 3-4 en los antiguos — siempre reales, nunca de relleno)

HABILIDADES TÉCNICAS
[Skills agrupadas por categoría (Frontend, IA, Sistemas de Diseño, Backend, Cloud, Testing...) con herramientas/versiones concretas, ordenadas por relevancia para esta oferta]

FORMACIÓN
[Del CV master]

IDIOMAS
[Del CV master]

REGLAS FINALES:
- La primera línea DEBE ser "HEADLINE: ..." — se usa como titular de la cabecera
- NO incluir nombre/email/tel, se añaden programáticamente
- NO usar markdown (**texto**, ##, ```)
- NO inventar nada que no esté en el CV master
- La EXPERIENCIA se lee como una trayectoria contada a través de los PUESTOS: el puesto abre cada entrada y la empresa va detrás. Quien lee debe poder recorrer el margen izquierdo y ver la progresión (Tech Lead, antes Front-End Developer, antes Diseñadora). Nunca empieces por la empresa.
- Idioma: TODO el CV en español (títulos de sección y contenido)"""

    prompt = f"""Act as a senior tech recruiter who screens 200+ CVs daily. Adapt this candidate's CV for a specific job offer.

The target job offer is written in {idioma_nombre}. Generate the ENTIRE CV in {idioma_nombre} — both the section titles and the content.

PRINCIPIO FUNDAMENTAL: el CV generado NO añade información nueva. Únicamente reorganiza, prioriza y redacta de forma distinta información YA existente y demostrable en el CV Master. Nunca al revés.

REGLA MAESTRA — PROYECCIÓN, NO IDENTIDAD NUEVA (de esta se derivan casi todas las demás): la adaptación debe producir una PROYECCIÓN distinta de la MISMA trayectoria profesional, NUNCA una nueva identidad profesional. El CV de esta oferta y el que se generó para cualquier otra tienen que leerse como la misma persona enfocando distinto, no como profesionales diferentes. Un recruiter que viera tres CV suyos debe reconocer a la misma candidata adaptando el contenido. Si un cambio la hace parecer otra profesional, ese cambio está MAL aunque cada frase por separado sea cierta. Consecuencias directas: no cambies el titular de forma radical, no subas el seniority, no inventes herramientas, no muevas skills a experiencia, no conviertas un proyecto propio en una organización grande. Solo cambia el ÉNFASIS.

JERARQUÍA DE FUENTES (respétala siempre):
- La OFERTA decide QUÉ enfatizar.
- El PERFIL BASE decide DESDE QUÉ IDENTIDAD se responde (quién es la candidata). Es una GUÍA de identidad y coherencia, NO una fuente de contenido, y NUNCA constituye evidencia. No copies literalmente sus frases al CV.
- La EXPERIENCIA (junto con proyectos, formación y conocimientos técnicos) es la ÚNICA fuente de evidencia: decide QUÉ se puede afirmar.
- El CV generado es solo una reorganización de esa evidencia según la oferta.
Ninguna afirmación entra en el CV si no está respaldada por la EXPERIENCIA, proyectos, formación o skills del Master; el PERFIL BASE por sí solo NO basta como evidencia.

{contexto_candidato}

OFERTA TARGET:
- Empresa: {empresa}
- Puesto: {puesto}
- Descripción: {descripcion or "No disponible"}

PASO 1 — ANÁLISIS INTERNO (SOLO mental — NO lo escribas en la respuesta):
Piensa, SIN volcarlo al output, en:
- Skills del CV master que encajan con esta oferta
- Keywords de la oferta que deben aparecer
- Logros que mejor demuestran el fit
- NO inventar experiencia, métricas ni logros
Tu respuesta DEBE empezar EXACTAMENTE con la línea "HEADLINE: ...". Prohibido escribir
análisis, títulos, encabezados o cualquier texto ANTES de esa línea.

PASO 2 — CV ADAPTADO (output principal):
Genera el CV adaptado con estas reglas ESTRICTAS:
1. NO INVENTAR NUNCA: solo experiencia real del CV master. Nada de tecnologías no usadas, responsabilidades no ejercidas, liderazgo de personas o arquitectura que no haya hecho, ni métricas/impacto exagerados. REGLA DE EVIDENCIA: una tecnología o skill SOLO puede aparecer si está respaldada en el Master por experiencia profesional, un proyecto o formación significativa; no basta con haberla tocado puntualmente.
2. Adapta el ORDEN y ÉNFASIS según la oferta, no el contenido
3. Optimización ATS: integra las palabras clave EXACTAS de la oferta cuando formen parte de su experiencia real; el CV debe quedar 100% defendible en entrevista
4. Bullets con fórmula XYZ ("Logré X, medido por Y, haciendo Z") SOLO cuando la cifra de "Y" esté LITERALMENTE en el CV Master. Si el Master no da una cifra, escribe el bullet SIN métrica (X + Z): describe qué construiste y cómo, sin cuantificar. Nada de bullets genéricos tipo "responsable de...".
4bis. PROHIBICIÓN DE CIFRAS (no negociable): no introduzcas NINGÚN número que no aparezca en el CV Master. Ni usuarios, ni porcentajes, ni ingresos, ni tamaños de equipo, ni volúmenes. Prohibido también cuantificar con palabras ("millones de", "miles de", "cientos de", "millions of", "thousands of") si esa magnitud no está en el Master. Ante la duda, describe sin número: un CV sin cifras es defendible en entrevista; uno con una cifra inventada, no.
5. Densidad real: NO recortes ni resumas el CV master. Los puestos recientes/relevantes deben llevar 6-9 bullets; los antiguos 3-4. Si el master tiene el detalle, úsalo entero.
6. Redacta como PERFIL DE PRODUCTO: traducción de necesidades de negocio a soluciones digitales, colaboración con diseño y producto, plataformas B2B y B2C, diseño de flujos y componentes reutilizables, Design Systems.
7. NO OMITAS tecnologías del Master que la oferta valora: si la oferta pide o menciona un área (backend, IA, testing, cloud...) y el Master tiene una tecnología concreta de esa área, esa tecnología DEBE aparecer en HABILIDADES TÉCNICAS y, si encaja, en un bullet. Ejemplo: oferta backend/IA con Python y el Master incluye FastAPI → FastAPI debe salir en Backend. La REGLA DE EVIDENCIA impide inventar; esta regla impide lo contrario, dejarse fuera algo real y relevante.
8. Máximo 2 páginas

IDENTIDAD vs POSICIONAMIENTO (distinción base: no las confundas nunca):
- IDENTIDAD = quién ES la candidata. Es un repertorio CERRADO, declarado en "Identidades permitidas" del PERFIL BASE. No se amplía, no se deduce, no se negocia. Ejemplo de identidades: Frontend Tech Lead, Full-Stack Developer, AI Engineer.
- POSICIONAMIENTO = cómo se PRESENTA esa misma trayectoria ante esta oferta concreta. Es variable y lo fija el ARQUETIPO de la oferta. Ejemplos de posicionamiento: GenAI Adoption, Context Engineering, Applied AI, AI Automation, Design Systems.
- Un posicionamiento NO es una identidad nueva: es la MISMA trayectoria profesional presentada según el problema que la empresa quiere resolver. Por eso el posicionamiento puede cambiar en cada oferta y la identidad no cambia nunca.
- DÓNDE VA CADA COSA EN EL TITULAR: los huecos de IDENTIDAD solo admiten valores de "Identidades permitidas". Los huecos de MODIFICADOR (especialización y stack) son donde vive el posicionamiento. Un posicionamiento JAMÁS ocupa un hueco de identidad ni se coloca delante de las identidades.
- EL POSICIONAMIENTO TAMBIÉN NECESITA RESPALDO: un posicionamiento solo puede usarse si la EXPERIENCIA, proyectos o formación del Master lo respaldan. Un posicionamiento sin evidencia es una identidad inventada con otro nombre, y está igual de prohibido. Si el Master no respalda el posicionamiento que pide la oferta, se usa el que sí esté respaldado, aunque encaje peor.

HEADLINE RULES (primera línea del output — el TITULAR del CV es DATA-DRIVEN):
- EL PERFIL BASE ES UN CONTRATO, NO UNA SUGERENCIA: el bloque "PERFIL BASE" del CV MASTER declara la identidad de la candidata en secciones explícitas. Tu trabajo es LEERLAS, no interpretarlas. No deduzcas nada que esté declarado. Secciones del contrato:
  · "Identidad profesional" → el TITULAR BASE completo. Es el ancla.
  · "Identidades permitidas" → el repertorio CERRADO de identidades. Ninguna otra existe.
  · "Orden del titular" → el orden exacto de los elementos del titular. Es un dato, no una decisión tuya.
  · "Variante permitida" → el único titular alternativo, con la condición que lo habilita.
  · "Nunca permitido" → restricciones que el propio Master declara. Son innegociables.
- CÓMO CONSTRUIR EL TITULAR: parte de "Identidad profesional" tal cual está escrita y respeta el "Orden del titular". Tus ÚNICAS libertades son: (a) SUSTITUIR uno, como mucho dos, MODIFICADORES de especialización o stack por los que esta oferta valora, tomados siempre del Master; (b) OMITIR un modificador que no aporte nada a esta oferta. Las identidades y su orden no se tocan.
- EL ORDEN NO SE ALTERA: el orden de las identidades es branding, no una preferencia. Un recruiter que vea varios CV suyos debe reconocer el mismo titular. Prohibido reordenarlas aunque esta oferta priorice otra cosa, prohibido añadir identidades fuera de "Identidades permitidas", y prohibido reescribir el núcleo del titular para parecerse al título del anuncio.
- ÚNICA EXCEPCIÓN AL ORDEN: usa el titular de "Variante permitida" solo si esta oferta cumple EXACTAMENTE la condición que esa sección declara. Si el Master no declara variante, o la condición no se cumple, no hay excepción.
- LA OFERTA DECIDE QUÉ DESTACAR, NUNCA QUÉ INVENTAR: si la oferta pide un rol/identidad que NO está en "Identidades permitidas", NO lo uses. La oferta solo elige qué modificadores acompañan al titular.
- NADA DE ECO EN LAS IDENTIDADES: no copies calificativos ni adjetivos del título de la oferta a la identidad. Si la oferta se titula "Applied AI Engineer" y el PERFIL BASE dice "AI Engineer", el titular usa "AI Engineer", no "Applied AI Engineer". La identidad sale del PERFIL BASE tal cual está escrita ahí.
- GUARDRAIL POR PRINCIPIO (no escalar el NIVEL JERÁRQUICO): no incrementes el nivel jerárquico, la autoridad ni el alcance organizativo que declara el PERFIL BASE. La prueba NO es si la palabra aparece en una lista: es si el titular sugiere un rango, una autoridad o un alcance MAYOR que el declarado. Queda prohibido cualquier término que eleve el nivel, salvo que esa identidad EXACTA figure en el PERFIL BASE. Ejemplos, y la lista NO es cerrada: Principal, Staff, Head, Director, Architect, Distinguished, Manager, Leader, Chief, VP, Owner, Champion, Evangelist, Authority, o "Lead" de personas. Ante la duda, usa la identidad tal cual está escrita en el PERFIL BASE.
- RESPETA EL POSICIONAMIENTO: si el CV master incluye un bloque "POSICIONAMIENTO" (lo que la candidata NO es), el titular NUNCA debe contradecirlo.
- AUTO-CHEQUEO antes de cerrar el HEADLINE: verifica que CADA identidad del titular aparece en el PERFIL BASE; si alguna no rastrea ahí, elimínala.
- COHERENCIA IDENTIDAD/EXPERIENCIA: el PERFIL BASE define quién es la candidata; la sección EXPERIENCIA demuestra por qué puede afirmarlo. Cada identidad del titular debe poder justificarse leyendo la EXPERIENCIA del Master. Si una identidad del PERFIL BASE no tiene experiencia real que la respalde, NO la uses en el titular.
- FALLBACK: si el CV master NO contiene un bloque "PERFIL BASE", deriva las identidades SOLO de la experiencia real del CV master (nunca inventes) y aplica igualmente el guardrail de no escalar seniority.
- El titular va en el idioma de la oferta; separa identidades/skills con " | " o " · ".
- AÑOS DE EXPERIENCIA: usa el seniority tal como lo declara el PERFIL BASE (dentro de "Identidad profesional" o en una sección propia). No infles el número ni lo subas por encima de lo que dice la fuente.

RESUMEN — ESTABILIDAD (aproximadamente 70-80% estable, 20-30% adaptado): el resumen NO se reescribe desde cero en cada oferta. La mayor parte describe la MISMA trayectoria con las mismas ideas y casi las mismas palabras: de dónde viene la candidata, cómo ha evolucionado y qué la define hoy. Solo la parte final, o los ejemplos concretos que se eligen, se ajustan al arquetipo de esta oferta. El objetivo es que el titular, el resumen y su perfil público cuenten la misma historia; si alguien compara dos CV suyos, tiene que ver a la misma profesional enfocando distinto, nunca dos perfiles inconexos.

RESUMEN / PERFIL — no pierdas experiencia real que no cabe en el titular: si la candidata tiene fortalezas relevantes que el titular de esta oferta no refleja (según el CV Master), inclúyelas en el resumen para no perderlas, redactadas como experiencia real. Si el CV Master incluye un bloque "EVOLUCIÓN PROFESIONAL", úsalo para entender el arco de su carrera y dar el contexto temporal correcto (de dónde viene y hacia dónde ha evolucionado), sin inventar.

PERFIL — ANCLAJE A LA OFERTA (obligatorio): identifica 2-3 requisitos o palabras clave concretas de la DESCRIPCIÓN de la oferta que la candidata YA haya trabajado de verdad (según su CV master), e intégralos en el resumen redactados como experiencia real y demostrable ("con experiencia en X aplicada a Y", "habiendo trabajado Z en..."). PROHIBIDO incluir un requisito de la oferta que NO esté respaldado por su trayectoria real: si la oferta lo pide pero ella no lo ha hecho, NO entra. El objetivo es que el perfil resuene con la oferta usando SOLO lo que es cierto y defendible en entrevista.

PROYECTOS PROPIOS, FREELANCE Y CONSULTORÍA (no sobredimensionar la escala):
- Un proyecto personal, freelance o de consultoría se describe por la COMPLEJIDAD TÉCNICA del trabajo, NUNCA por el tamaño aparente de la organización. El lector debe entender QUÉ SABE HACER la candidata, no cómo de grande era la empresa.
- PROHIBIDO el lenguaje que sugiera equipos, departamentos o estructuras que no existían: "definí la estrategia de IA de la compañía", "lideré la arquitectura de la empresa", "responsable de la plataforma global", "dirección técnica de", "lideré un equipo de". Nada de vocabulario de CEO (estrategia, dirección, organización, transformación digital de la empresa) salvo que la oferta sea justamente para ese tipo de puesto.
- En su lugar, prioriza: qué construyó, qué problemas resolvió, qué tecnologías usó, qué arquitectura diseñó, qué decisiones de ingeniería tomó.
- EL RESUMEN NUNCA GIRA ALREDEDOR DEL PROYECTO PROPIO. El resumen describe la trayectoria COMPLETA; la experiencia actual es el EJEMPLO de la evolución, no el eje de la identidad. La narrativa correcta es un arco: años de trayectoria en el sector, especialización de origen, evolución posterior y especialización actual, todo ello leído del bloque "EVOLUCIÓN PROFESIONAL" o de la experiencia del Master. La narrativa INCORRECTA es identificar a la candidata con su proyecto más reciente ("fundadora de X que hace Y").
- El PESO de una experiencia no depende del tamaño de la empresa, sino de la RELEVANCIA de las competencias para esta oferta. Un proyecto propio puede ir el primero si es lo más reciente y especializado, pero presentado como trabajo de ingeniería, no como si hubiese dirigido una organización.

NIVEL DEL PUESTO (aplica al CUERPO del CV — el TITULAR lo fijan las HEADLINE RULES):
- Si el puesto NO menciona lead/manager/responsable/principal/head/coordinador/director → es un rol de DESARROLLO INDIVIDUAL. En ese caso, en el CUERPO:
  · REDUCE al mínimo el liderazgo: NO abras bullets con "Lideré/Coordiné equipos" ni "formación de equipos". Reformula esos logros hacia el trabajo TÉCNICO concreto (qué construiste, qué migraste, qué arquitectura/componentes/APIs), no hacia la gestión.
  · El liderazgo puede aparecer como contexto breve ("durante 8 años en el equipo frontend..."), NUNCA como la venta principal del perfil.
  · El titular puede reflejar seniority de liderazgo si figura en el PERFIL BASE; NO lo contradice, pero el cuerpo se centra en el trabajo técnico, no en dirigir personas.
- Solo si el puesto pide lead/manager/responsable/principal/head → destaca el ownership y la coordinación técnica.

ARQUETIPO DE LA OFERTA (decide QUÉ se proyecta; jamás QUÉ se inventa):
Antes de escribir, clasifica esta oferta en UN arquetipo leyendo el PUESTO y la DESCRIPCIÓN — no el sector de la empresa ni las tecnologías que nombra de pasada. El arquetipo NO cambia el titular base ni las identidades: cambia qué experiencia del Master va primero, qué bullets se priorizan y qué keywords entran.
- Frontend: React, Vue, TypeScript, arquitectura frontend, design systems, rendimiento, accesibilidad, mentoría técnica.
- Full Stack: el frontend como fortaleza principal, más Node, APIs, bases de datos e integración.
- Tech Lead: ownership técnico, estándares, code review, coordinación con producto, diseño y backend. No afirmes dirección de personas salvo que el Master lo respalde.
- UX Engineer: Figma, design systems, accesibilidad, colaboración con diseño.
- IA / AI Engineer: CONSTRUYE sistemas con IA. LLM, RAG, agentes, APIs, Context Engineering, evaluación, guardrails, pipelines.
- IA / GenAI Adoption: consigue que OTROS desarrolladores trabajen mejor con IA. Formación, workshops, mentoring, pairing, experimentación, herramientas de desarrollo asistido, playbooks, productividad de equipos de ingeniería.
- IA / AI Solutions Architect: DISEÑA sistemas. Arquitectura, escalabilidad, cloud, integración, decisiones técnicas, observabilidad, gobernanza.
- IA / AI Product Engineer: construye PRODUCTO con IA. Métricas, usuarios, experimentos, UX, negocio, iteración.
- IA / AI Automation Engineer: AUTOMATIZA procesos. N8N, MCP, APIs, workflows, integración de procesos de negocio.

"IA" NO es un arquetipo único. Una oferta que busca impulsar la adopción de GenAI en equipos de ingeniería y otra que busca construir sistemas LLM piden CV DISTINTOS aunque las dos digan "IA". Clasifica por el PROBLEMA que la empresa necesita resolver, no por la tecnología que menciona.

REGLA DE PROYECCIÓN: adapta el CV al PROBLEMA que resuelve la empresa que contrata, NO al producto que la candidata construyó. La misma trayectoria se proyecta hacia un arquetipo u otro sin inventar absolutamente nada: cambia el orden, el énfasis y qué se cuenta primero.

LÍMITE DEL ARQUETIPO: si el Master NO respalda el arquetipo de la oferta, no lo fuerces. Proyecta lo que haya y deja el resto fuera. Un arquetipo sin evidencia en el Master es una invitación a inventar, y esa línea no se cruza nunca: es preferible un CV honesto que encaja a medias, a uno que encaja del todo y no se sostiene en entrevista.

HECHOS, NO EFECTOS (separa lo que hizo de lo que eso demuestra):
- Escribe la ACCIÓN concreta y verificable, NUNCA el efecto que se le atribuye, salvo que el Master dé el dato. El lector deduce el efecto solo, y le convence más.
- MAL: "Improved engineering productivity", "Led AI transformation", "proven track record of measurable productivity gains", "measuring adoption impact", "drove AI adoption".
- BIEN: "Delivered technical workshops on Generative AI for engineering teams", "Designed and delivered internal training on prompt engineering".
- Prohibido el vocabulario de resultado no medido cuando el Master no trae el dato: "proven track record", "measurable", "impact", "transformation", "drove", "boosted", "accelerated". Un hecho concreto sin adjetivos vende más que un efecto declarado sin prueba, y además es defendible en entrevista.

POSICIONAMIENTO (adapta el ÉNFASIS a la oferta, nunca inventes):
- Prioriza y reordena las skills y logros del CV Master que esta oferta valora; deja en segundo plano lo que no pide. NUNCA añadas algo que no esté en el Master.
- NO MUEVAS SKILLS A EXPERIENCIA: una tecnología que el Master lista en HABILIDADES pero NO atribuye a un puesto concreto no puede aparecer como logro de ese puesto. Puede seguir en Habilidades, ahí es legítima. Atribuirla a una experiencia donde el Master no la sitúa es inventar, aunque la tecnología sea real y ella la domine.

- PERSONA GRAMATICAL (regla dura, aplica a TODO el CV, perfil y bullets): el CV se escribe SIN SUJETO, que es el estándar en CV anglosajón. Escribe "Frontend Tech Lead with 10+ years building...", "Led the migration from Vue to React", "Established engineering standards". PROHIBIDO en tercera persona ("She led", "Her career spans", "She brings") y PROHIBIDO en primera ("I led", "My career"). Esta instrucción está redactada hablando de la candidata en tercera persona por comodidad; el CV que produces NO debe heredar esa persona gramatical. Un CV que habla de ella desde fuera se lee como escrito por otro, y es de las cosas que más delatan que lo ha redactado una máquina.
- LÍMITE DE POSICIONAMIENTO: si el CV Master incluye un bloque "POSICIONAMIENTO" (lo que la candidata ES y lo que NO es), respétalo como frontera. NUNCA posiciones a la candidata en un rol o especialidad que ese bloque niega, aunque la oferta lo pida.
- EVOLUCIÓN: si el CV Master incluye un bloque "EVOLUCIÓN PROFESIONAL", respeta el arco temporal (de dónde viene, hacia dónde ha evolucionado); no presentes como especialidad actual algo que fue una etapa pasada, ni al revés.
- Una tecnología usada hace años puede presentarse como algo que puede retomar rápido por su experiencia previa, SIN presentarla como especialidad actual salvo que el Master lo respalde.

PASO 3 — REVISION ANTI-IA (aplicar al output antes de entregar):
Elimina TODO rastro de texto generado por IA:
- Cero guiones largos (—) ni dobles guiones (--)
- Cero frases tipo "responsable de...", "encargada de...", "orientada a..."
- Cero adjetivos vacíos ("dinámico", "proactivo", "apasionado", "motivado")
- Cero "passionate about", "I'd love to", "excited to"
- Cero verbos pasivos innecesarios ("fue responsable de..." → "lideró...")
- Si suena a IA, reescríbelo con lenguaje humano y directo
- Mantener tono profesional pero natural, como lo escribiría una persona

{bloque_formato}"""

    try:
        # Claude (calidad) primario; Groq de fallback dentro de call_llm_calidad
        respuesta_llm = call_llm_calidad(prompt, model=CV_MODEL, max_tokens=4096)
        contenido_cv  = respuesta_llm.contenido
    except RuntimeError as e:
        raise CVError(503, str(e))

    # 5. Limpiar output del LLM y extraer el titular (HEADLINE)
    #    Todo lo anterior a la línea HEADLINE se DESCARTA: si el modelo escribe el
    #    "ANÁLISIS INTERNO" pese al "no mostrar", o mete un preámbulo, jamás llega
    #    al DOCX. El cuerpo del CV empieza recién DESPUÉS del HEADLINE.
    titular = ""
    lineas = contenido_cv.split("\n")
    idx_headline = next(
        (i for i, l in enumerate(lineas)
         if l.strip().replace("**", "").replace("`", "").lower().startswith("headline:")),
        None,
    )
    if idx_headline is not None:
        cab = lineas[idx_headline].strip().replace("**", "").replace("`", "")
        titular = cab.split(":", 1)[1].strip()
        lineas = lineas[idx_headline + 1:]

    # 5a. El titular NO se acepta tal cual: se ENSAMBLA desde el PERFIL BASE. El
    #     contrato es cerrado (identidades y orden declarados) y tres formulaciones
    #     distintas de la regla en el prompt no lo sostuvieron: el modelo invirtio el
    #     orden, fusiono identidades con "&" y se comio la seniority. Del modelo solo
    #     se aprovechan los modificadores, y solo si el Master los respalda.
    titular = construir_titular(titular, cv_master)
    lineas_limpias = []
    for linea in lineas:
        limpia = linea.strip().replace("**", "").replace("`", "").replace("##", "").replace("# ", "")
        # Filtrar frases introductorias del LLM
        if limpia.lower().startswith(("aquí", "here is", "here's", "a continuación", "claro", "por supuesto")):
            continue
        lineas_limpias.append(limpia)
    contenido_cv = "\n".join(lineas_limpias)

    # 5b. Guardrail de veracidad: el prompt prohibe inventar metricas, pero eso es
    #     una peticion, no una garantia. Se contrasta la salida contra el Master.
    #     NO se aborta: una cifra sospechosa puede ser legitima (reformulacion) y
    #     abortar dejaria a la usuaria sin CV. Se avisa para que ella lo revise.
    cifras_sospechosas = detectar_cifras_no_respaldadas(contenido_cv, cv_master)
    if cifras_sospechosas:
        logger.warning(
            "CIFRAS NO RESPALDADAS por el CV Master en el CV de %s para %s/%s: %s",
            email, empresa, puesto, cifras_sospechosas,
        )

    #     Lo mismo con las tecnologias: la oferta pide una cosa y el modelo tiende a
    #     devolverla como si la candidata la tuviera. Tampoco se aborta, se avisa.
    tecnologias_sospechosas = detectar_tecnologias_no_respaldadas(contenido_cv, cv_master)
    if tecnologias_sospechosas:
        logger.warning(
            "TECNOLOGIAS NO RESPALDADAS por el CV Master en el CV de %s para %s/%s: %s",
            email, empresa, puesto, tecnologias_sospechosas,
        )

    #     Y la seccion de skills, elemento a elemento: es donde el modelo vuelca el
    #     stack de la oferta y donde el catalogo de arriba es ciego a lo que no
    #     tiene dado de alta, que es precisamente lo nuevo de cada oferta.
    skills_sospechosas = detectar_skills_no_respaldadas(contenido_cv, cv_master)
    if skills_sospechosas:
        logger.warning(
            "SKILLS NO RESPALDADAS por el CV Master en el CV de %s para %s/%s: %s",
            email, empresa, puesto, skills_sospechosas,
        )

    # 5d. Guardrail del titular: que respete el contrato del PERFIL BASE. Es el unico
    #     de los tres que mira la CABECERA, y viene de un fallo medido: los CV de N-iX y
    #     Revolut usaron la Variante permitida sin cumplir su condicion.
    titular_sospechoso = detectar_titular_fuera_de_contrato(titular, cv_master)
    if titular_sospechoso:
        logger.warning(
            "TITULAR FUERA DEL CONTRATO del PERFIL BASE en el CV de %s para %s/%s: %s",
            email, empresa, puesto, titular_sospechoso,
        )

    # 5e. Guardrail de ENTRADA (los otros tres miran la salida): ¿habia material que
    #     adaptar? Las ofertas de LinkedIn e Indeed llegan con 172-245 caracteres, el
    #     titular reformulado. Con eso el CV sale generico y ningun otro guardrail lo
    #     detecta, porque un CV generico no inventa nada: simplemente no dice nada.
    descripcion_evaluada = evaluar_descripcion_oferta(descripcion)
    if not descripcion_evaluada["suficiente"]:
        logger.warning(
            "DESCRIPCION INSUFICIENTE (%s chars) para %s/%s: %s",
            descripcion_evaluada["chars"], empresa, puesto, descripcion_evaluada["aviso"],
        )

    # 6. Generar DOCX con cabecera estructurada (titular adaptado por la oferta)
    nombre_archivo = _nombre_archivo_cv(nombre, puesto)
    docx_bytes = generar_docx_con_cabecera(contenido_cv, usuario, titular, idioma)

    # 7. Subir a Drive
    try:
        link_drive = subir_cv_a_drive(docx_bytes, nombre_archivo)
    except Exception as e:
        logger.error("Drive upload error: %s", e)
        raise CVError(500, f"Error subiendo a Drive: {e}")

    # 8. Anotar el enlace en la ficha de Notion, ahora, no via n8n. Si la cadena
    #    de n8n muere despues (timeout de 120s del nodo que llama aqui), el CV
    #    sigue estando localizable desde la ficha. Ver guardar_link_cv_en_notion.
    link_anotado = guardar_link_cv_en_notion(empresa, puesto, link_drive, nombre_archivo)

    return {
        "ok":              True,
        "link":            link_drive,
        # False = el CV existe en Drive pero no se pudo anotar en la ficha.
        # Revisar a mano: es un CV que Veronica tiene y no sabe que tiene.
        "link_anotado_en_notion": link_anotado,
        "modelo_usado":    respuesta_llm.modelo,
        "archivo":         nombre_archivo,
        "email":           email,
        "cv_master_usado": bool(cv_master),
        "idioma":          idioma,
        "cv_master_url":   master.url,
        # Vacio = todas las cifras del CV estan en el Master. Si trae algo, REVISAR
        # a mano antes de enviar: son datos que el modelo no pudo justificar.
        "cifras_no_respaldadas": cifras_sospechosas,
        # Vacio = todas las tecnologias del CV estan en el Master. Si trae algo, es una
        # tecnologia que la oferta pedia y la candidata NO tiene: quitarla antes de enviar.
        "tecnologias_no_respaldadas": tecnologias_sospechosas,
        # Vacio = el titular respeta el contrato del PERFIL BASE. Si trae algo, el titular
        # cambio la identidad o su orden: revisarlo, es lo primero que lee un recruiter.
        "titular_fuera_de_contrato": titular_sospechoso,
        # suficiente=False significa que la DESCRIPCION no daba material para adaptar:
        # el CV es generico aunque no haya ningun otro aviso. Es lo PRIMERO que hay que
        # mirar, porque los demas guardrails no detectan un CV correcto pero vacio.
        "descripcion_oferta": descripcion_evaluada,
    }


@app.route("/generar-cv", methods=["POST"])
def generar_cv():
    """Ruta Flask fina: parsea el request y delega en generar_cv_core (ADR-001)."""
    datos = request.get_json(force=True)
    try:
        result = generar_cv_core(
            email=datos.get("email", ""),
            empresa=datos.get("empresa", ""),
            puesto=datos.get("puesto", ""),
            descripcion=datos.get("descripcion", ""),
            idioma_in=(datos.get("idioma") or "").strip().lower(),
        )
    except CVError as e:
        return jsonify({"ok": False, "error": e.message}), e.status
    return jsonify(result)


@app.route("/generar-carta", methods=["POST"])
def generar_carta():
    """Genera la carta de presentación con la experiencia real del CV master.
    Usa Claude Sonnet (calidad) — la carta va a la empresa."""
    datos = request.get_json(force=True)
    email       = datos.get("email", "")
    empresa     = datos.get("empresa", "")
    puesto      = datos.get("puesto", "")
    descripcion = datos.get("descripcion", "")

    if not email or not empresa or not puesto:
        return jsonify({"ok": False, "error": "email, empresa y puesto son requeridos"}), 400

    # Idioma autoritativo (igual que en /generar-cv) + persona de contacto para
    # el saludo. Prioridad idioma: body.idioma > Idioma de Notion > detección.
    idioma_in = (datos.get("idioma") or "").strip().lower()
    contacto = (datos.get("contacto") or datos.get("nombre_contacto") or "").strip()
    if not descripcion.strip() or not contacto or idioma_in not in ("en", "es"):
        oferta = buscar_oferta_en_notion(empresa, puesto)
        if oferta:
            descripcion = descripcion or oferta.get("descripcion", "")
            contacto = contacto or oferta.get("nombre_contacto", "").strip()
            idioma_in = idioma_in or (oferta.get("idioma") or "").strip().lower()

    usuario = buscar_usuario_por_email(email)
    if not usuario:
        return jsonify({"ok": False, "error": f"Usuario {email} no encontrado en Notion"}), 404

    nombre = usuario.get("nombre") or email.split("@")[0]

    # Resolver idioma y leer el CV master en ese idioma
    idioma = idioma_in if idioma_in in ("en", "es") else idioma_de_oferta(puesto, descripcion, empresa)
    tiene_master = _tiene_algun_master(usuario)
    try:
        master    = leer_cv_master_desde_drive(usuario, idioma)
        cv_master = master.texto
    except Exception as e:
        # Mismo guard que /generar-cv: get_drive_service() -> creds.refresh() puede
        # fallar (token caducado o revocado) ANTES del try interno de la lectura.
        # Sin esto sale un 500 HTML opaco y el fallo tarda en diagnosticarse: paso
        # el 24-jul-2026, con el GOOGLE_REFRESH_TOKEN caducado, y dejo la cadena de
        # n8n rota sin ningún mensaje util.
        logger.error("Drive auth/lectura falló en /generar-carta: %s", e)
        return jsonify({
            "ok": False,
            "error": f"No se pudo autenticar/leer el CV master en Drive: {e}",
        }), 502

    def _es_legible(t: str) -> bool:
        if not t:
            return False
        if t.lstrip().startswith("PK"):
            return False
        imprimibles = sum(1 for c in t if c.isprintable() or c in "\n\r\t")
        return imprimibles / len(t) >= 0.85

    if tiene_master and not _es_legible(cv_master):
        logger.error("CV master ILEGIBLE para carta de %s — abortando", email)
        return jsonify({
            "ok": False,
            "error": ("No se pudo leer tu CV master desde Drive. NO se generó la carta "
                      "para evitar inventar datos. Revisá el archivo y permisos en Drive."),
        }), 502

    contexto = (f"CV MASTER (usa SOLO esta experiencia real, NO inventes nada):\n{cv_master}"
                if cv_master else
                f"PERFIL: {nombre} — {usuario.get('rol','')} — {usuario.get('perfil','')}")

    # Saludo: si hay persona de contacto real, dirigir la carta a ella; si no,
    # saludo genérico. NUNCA inventar un nombre.
    if contacto:
        instr_saludo = (f'saludo dirigido a la persona de contacto ("A la atención de {contacto}," '
                        f'en español, "Dear {contacto}," en inglés) — usa EXACTAMENTE ese nombre, no lo inventes ni lo cambies')
    else:
        instr_saludo = 'saludo formal genérico ("Estimados/as," en español, "Dear Hiring Team," en inglés)'

    prompt = f"""Eres un experto en cartas de presentación para ofertas de trabajo.
Escribe una carta de presentación profesional para {nombre}.

{contexto}

OFERTA:
- Empresa: {empresa}
- Puesto: {puesto}
- Descripción: {descripcion or "No disponible"}

REGLAS:
- La oferta está en {"inglés" if idioma == "en" else "español"}. Escribe TODA la carta en ese idioma (saludo, cuerpo y despedida).
- Máximo 250 palabras.
- Usa SOLO experiencia real del CV master, y SOLO la relevante para este puesto; conecta esa experiencia con lo que pide la oferta. NO inventes, NO exageres y NO afirmes nada difícil de defender en entrevista (ni gestión de equipos ni arquitectura que no haya hecho).
- NIVEL: si el puesto NO menciona lead/manager/responsable/principal/head, es un rol de DESARROLLO INDIVIDUAL: NO uses la coordinación/liderazgo de equipos como argumento principal (nada de "experiencia coordinando equipos técnicos"). Enfoca el encaje TÉCNICO real (stacks, full-stack, APIs, mobile, capacidad de aprender rápido el stack de la oferta).
- Tono profesional, directo y humano. Cero frases vacías de IA: nada de "apasionada",
  "proactiva", "soluciones innovadoras", "emocionada de la oportunidad", "dinámica".
- Menciona logros o tecnologías concretas del CV que encajen con la oferta.
- Formato carta: {instr_saludo} ... cuerpo ... despedida formal ("Atentamente," / "Sincerely,") seguida de "{nombre}".
- Devuelve SOLO el texto de la carta, sin encabezados ni comentarios."""

    try:
        respuesta_llm = call_llm_calidad(prompt, model=CARTA_MODEL, max_tokens=1500)
        carta         = respuesta_llm.contenido
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 503

    # Limpiar frases introductorias del LLM
    carta = carta.strip()
    for pref in ("aquí tienes", "aquí está", "here is", "here's", "claro", "por supuesto"):
        if carta.lower().startswith(pref):
            carta = carta.split("\n", 1)[-1].strip()
            break
    # Fuera guiones largos y flechas: la carta va a la empresa. Regla NO NEGOCIABLE.
    carta = sanear_tipografia(carta, idioma)

    # GUARDRAILS DE LA CARTA. Hasta el 18-ago-2026 la carta salia SIN NINGUNO: los
    # cuatro detectores existentes se aplicaban solo a `contenido_cv`. Y la carta es
    # lo primero que lee un humano; el CV lo abren despues, si les interesas.
    # Igual que en /generar-cv, esto AVISA y no aborta: un aviso puede ser una
    # reformulacion legitima, y abortar dejaria a la usuaria sin carta.
    # `detectar_skills_no_respaldadas` queda fuera a proposito: lee lineas de skills
    # separadas por puntos, y una carta es prosa. Aplicarlo aqui daria ruido.
    # Este endpoint ya NO sabe cuantos guardrails hay ni cuales aplican: lo pide
    # y el registro decide. Anadir el septimo no toca esta linea.
    avisos = guardrails.revisar(carta, cv_master, guardrails.CARTA)
    for aviso in avisos:
        logger.warning(
            "%s en la CARTA de %s para %s/%s: %s",
            aviso["regla"].upper().replace("_", " "), email, empresa, puesto,
            aviso["hallazgos"],
        )

    return jsonify({
        "ok":              True,
        "carta":           carta,
        "modelo_usado":    respuesta_llm.modelo,
        "email":           email,
        "cv_master_usado": bool(cv_master),
        "avisos":          avisos,
    })


@app.route("/usuarios", methods=["GET"])
def usuarios():
    """Consulta usuarios activos en Notion."""
    if not NOTION_DB_USUARIOS:
        return jsonify({"ok": False, "error": "NOTION_DB_USUARIOS no configurada"}), 500
    try:
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_USUARIOS}/query",
            headers=notion_headers(),
            json={"filter": {"property": "Activo", "checkbox": {"equals": True}}},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        usuarios_list = []
        for p in results:
            props = p.get("properties", {})
            usuarios_list.append({
                "id":     p["id"],
                "nombre": props.get("Name", {}).get("title", [{}])[0].get("plain_text", ""),
                "email":  props.get("Email", {}).get("email", ""),
                "activo": props.get("Activo", {}).get("checkbox", False),
            })
        return jsonify({"ok": True, "usuarios": usuarios_list, "total": len(usuarios_list)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/buscar-ofertas-reales", methods=["POST"])
def buscar_ofertas_reales_endpoint():
    """
    Busca ofertas REALES en Remotive (sustituye al LLM inventando ofertas).

    Body esperado:
    {
        "rol": "frontend developer",        // opcional, default del perfil
        "stack": ["react", "typescript"],    // opcional
        "modalidad": ["Remoto"],             // opcional
        "ciudad": "Madrid",                  // opcional
    }
    """
    datos = request.get_json(force=True)
    perfil = datos.get("perfil", "")
    rol = datos.get("rol", "")
    stack = datos.get("stack", [])
    modalidad = datos.get("modalidad", [])
    ciudad = datos.get("ciudad", "")
    salario_min = datos.get("salario_min", 0)
    top_n = datos.get("top_n", 5)

    try:
        ofertas = buscar_ofertas_reales(perfil=perfil, rol=rol, stack=stack, salario_min=salario_min, modalidad=modalidad, ciudad=ciudad, top_n=top_n)
        return jsonify({"ok": True, "ofertas": ofertas, "total": len(ofertas)})
    except Exception as e:
        logger.error("Error buscando ofertas reales: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/crear-oferta", methods=["POST"])
def crear_oferta():
    """Crea una oferta en Notion con TODOS sus campos.

    n8n llama aquí (una vez por oferta) en vez de mapear campo por campo en su
    nodo de Notion. Body: {"email": "...", "oferta": {...}} — o el objeto oferta
    plano. Detecta y persiste el idioma a partir de la descripción.
    """
    datos = request.get_json(force=True)
    email = (datos.get("email") or "").strip().lower()
    oferta = datos.get("oferta") if isinstance(datos.get("oferta"), dict) else datos

    empresa = oferta.get("empresa", "")
    puesto = oferta.get("puesto", "")
    if not empresa or not puesto:
        return jsonify({"ok": False, "error": "empresa y puesto son requeridos"}), 400

    # Detectar idioma ahora que tenemos la descripción en la mano y persistirlo
    idioma = idioma_de_oferta(puesto, oferta.get("descripcion", ""), empresa)

    # Relacionar la oferta con el usuario (si tenemos email)
    usuario_notion_id = ""
    if email:
        u = buscar_usuario_por_email(email)
        if u:
            usuario_notion_id = u.get("notion_id", "")

    try:
        page = crear_oferta_en_notion(oferta, idioma, usuario_notion_id)
    except requests.RequestException as e:
        logger.error("Error creando oferta en Notion: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 502

    return jsonify({"ok": True, "notion_page_id": page.get("id", ""), "idioma": idioma})


# ══════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)