"""Acceso a Notion: usuarios y ofertas.

Las dos bases que usa el sistema. Lee sus credenciales del entorno igual que el
servidor, asi que no importa nada de `server`.

Extraido de `server.py` el 28-ago-2026.
"""
import logging
import os
import re
import threading
import time

import requests

logger = logging.getLogger(__name__)

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_DB_USUARIOS = os.getenv("NOTION_DB_USUARIOS", "")
NOTION_DB_OFERTAS = os.getenv("NOTION_DB_OFERTAS", "")

def notion_headers():
    return {
        "Authorization":  f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type":   "application/json",
    }


# Campo de Notion (Users) con las direcciones ADICIONALES por las que entran ofertas
# del mismo usuario. `Email` sigue siendo la principal.
#
# El nombre lo escribe una persona en Notion, asi que se aceptan las variantes
# razonables (singular/plural, mayusculas). Exigir coincidencia exacta produce el
# peor fallo posible: el campo existe, el codigo no lo ve y NO hay error — el
# usuario simplemente se queda sin alias. Paso el 28jul2026 con "Email Alias".
CAMPO_EMAILS_ALIAS = os.getenv("CAMPO_EMAILS_ALIAS", "Emails alias")
_ALIAS_ACEPTADOS = {"emails alias", "email alias", "emails_alias", "email_alias",
                    "emails alternativos", "email alternativo"}


def _es_campo_de_alias(nombre: str) -> bool:
    return nombre.strip().lower() in _ALIAS_ACEPTADOS or nombre == CAMPO_EMAILS_ALIAS


def campos_alias_candidatos() -> list:
    """Nombres con los que INTENTAR la consulta a Notion, en orden.

    Tolerar el nombre al LEER no sirve de nada si al PREGUNTAR se usa uno solo:
    Notion filtra por nombre exacto y devuelve 400 si no existe. Paso el 28jul2026
    con 'Email alias' (la propiedad) frente a 'Emails alias' (lo que se consultaba):
    la busqueda por alias nunca encontraba nada y no habia error visible.
    """
    orden = [CAMPO_EMAILS_ALIAS, "Email alias", "Emails alias",
             "Emails alternativos", "Email alternativo"]
    vistos, out = set(), []
    for n in orden:
        if n.lower() not in vistos:
            vistos.add(n.lower()); out.append(n)
    return out

# --- Caches (per process, in memory) -------------------------------------------
# The Usuarios schema rarely changes, so it is read once per hour. The per-email
# result is kept for a minute: enough for the two GET /yo calls of one sign-in to hit
# Notion once, short enough that an edit in Notion shows up almost immediately.
TTL_ESQUEMA = 3600.0
TTL_USUARIO = 60.0

_candado = threading.Lock()
_esquema_alias: dict = {}      # {"campos": [...], "hasta": monotonic deadline}
_campos_ausentes: set = set()  # alias properties Notion answered 400 "not found" for
_usuarios_cache: dict = {}     # email -> (monotonic deadline, profile or None)


def reiniciar_caches() -> None:
    """Empty every cache. Used by tests."""
    with _candado:
        _esquema_alias.clear()
        _campos_ausentes.clear()
        _usuarios_cache.clear()


def _campos_alias_existentes() -> list:
    """Alias properties to query: the ones the database really has.

    Reads the schema once (GET /v1/databases/{id}) and keeps the properties that
    look like an alias field. If the schema cannot be read (network, permissions) it
    falls back to the candidate names minus the ones already known to be missing,
    and the failure is NOT cached so the next call tries again.
    """
    ahora = time.monotonic()
    with _candado:
        if _esquema_alias and _esquema_alias["hasta"] > ahora:
            return list(_esquema_alias["campos"])
    try:
        resp = requests.get(
            f"https://api.notion.com/v1/databases/{NOTION_DB_USUARIOS}",
            headers=notion_headers(), timeout=15,
        )
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        nombres = list((resp.json().get("properties") or {}).keys())
    except (requests.RequestException, ValueError) as e:
        logger.warning("Notion schema read failed, using candidate alias names: %s",
                       type(e).__name__)
        with _candado:
            return [c for c in campos_alias_candidatos() if c not in _campos_ausentes]
    campos = [n for n in nombres if _es_campo_de_alias(n)]
    # Configured name first, so the order stays predictable.
    campos.sort(key=lambda n: n != CAMPO_EMAILS_ALIAS)
    with _candado:
        _esquema_alias.update({"campos": campos, "hasta": ahora + TTL_ESQUEMA})
    return list(campos)


_SEPARADORES_EMAIL = re.compile(r"[,;\n\r]+")
_ES_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def emails_de_usuario(props: dict) -> set:
    """Todas las direcciones por las que se puede identificar a un usuario.

    Una persona con dos buzones es UN usuario con dos emails, no dos usuarios: dos
    registros derivan (masters distintos, campos a medias) y el CV sale distinto
    segun por donde entre la oferta. Caso real, 28jul2026: ver ADR-003.
    """
    emails = set()
    principal = (props.get("Email", {}) or {}).get("email") or ""
    if principal.strip():
        emails.add(principal.strip().lower())

    crudo = ""
    for nombre, campo in props.items():
        if _es_campo_de_alias(nombre):
            crudo += "".join(t.get("plain_text", "") for t in ((campo or {}).get("rich_text") or []))
            crudo += ","
    for trozo in _SEPARADORES_EMAIL.split(crudo):
        t = trozo.strip().lower()
        if t and _ES_EMAIL.match(t):
            emails.add(t)
    return emails


def usuario_tiene_email(props: dict, email: str) -> bool:
    """¿Este usuario responde a esta direccion? Comparacion EXACTA.

    Importa que sea exacta: el filtro `contains` de Notion es de subcadena, asi que
    'vero@gmail.com' casa con 'notvero@gmail.com'. Sin esta verificacion final un
    usuario podria recibir el CV de otro.
    """
    return (email or "").strip().lower() in emails_de_usuario(props)


def _consultar_usuario_ok(filtro: dict, email: str, verificar: bool) -> tuple:
    """Una consulta a Users. Devuelve (pagina o None, ok).

    `ok` is False when the call failed (network, HTTP error) so the caller can avoid
    caching a result that should be retried. A 400 "property not found" is a
    permanent answer: the property is remembered, logged once, and counts as ok.
    """
    campo = filtro.get("property")
    with _candado:
        if campo in _campos_ausentes:
            return None, True
    try:
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_USUARIOS}/query",
            headers=notion_headers(),
            json={"filter": filtro, "page_size": 5 if verificar else 1},
            timeout=15,
        )
    except requests.RequestException as e:
        logger.warning("Notion query fallo (%s): %s", campo, e)
        return None, False
    if resp.status_code == 400 and "Could not find property" in (resp.text or ""):
        with _candado:
            nuevo = campo not in _campos_ausentes
            _campos_ausentes.add(campo)
        if nuevo:
            logger.warning("Notion property %r does not exist in Usuarios; "
                           "it will not be queried again in this process", campo)
        return None, True
    if resp.status_code != 200:
        logger.warning("Notion query error %s (%s): %s",
                       resp.status_code, campo, resp.text[:200])
        return None, False
    for page in resp.json().get("results", []):
        if not verificar or usuario_atiende(page.get("properties", {}), email):
            return page, True
    return None, True


def _consultar_usuario(filtro: dict, email: str, verificar: bool) -> dict | None:
    return _consultar_usuario_ok(filtro, email, verificar)[0]


def usuario_atiende(props: dict, email: str) -> bool:
    """¿Este registro atiende esta direccion? Exige que este ACTIVO.

    Desactivar un registro tiene que significar "ya no atiende a nadie". Sin esto,
    un duplicado desactivado seguia ganando: la busqueda mira primero el `Email`
    exacto, lo encontraba ahi, y nunca llegaba al alias del registro bueno. Costo
    un CV generado con la identidad equivocada el 28jul2026 (ver ADR-003).

    Sin columna `Activo` se asume activo, para no romper bases que no la tengan.
    """
    activo = props.get("Activo", {}).get("checkbox", True) if "Activo" in props else True
    return bool(activo) and usuario_tiene_email(props, email)


def buscar_usuario_por_email(email: str) -> dict | None:
    """Consulta Notion por email (principal o alias). Devuelve el perfil o None.

    The result (found or not found) is cached for `TTL_USUARIO` seconds. Failed
    calls are never cached.
    """
    if not NOTION_DB_USUARIOS:
        return None
    clave = (email or "").strip().lower()
    with _candado:
        hit = _usuarios_cache.get(clave)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    perfil, ok = _buscar_usuario_sin_cache(email)
    if ok:
        with _candado:
            _usuarios_cache[clave] = (time.monotonic() + TTL_USUARIO, perfil)
    return perfil


def _buscar_usuario_sin_cache(email: str) -> tuple:
    """(perfil o None, ok). ok=False si alguna consulta fallo y no se debe cachear."""
    # verificar=True tambien en la pasada por Email exacto: hay que comprobar que el
    # registro este ACTIVO, cosa que el filtro de Notion no hace.
    page, ok = _consultar_usuario_ok(
        {"property": "Email", "email": {"equals": email}}, email, verificar=True
    )
    if page is None:
        # Segunda pasada por los alias. `contains` es de subcadena, de ahi el
        # verificar=True: se confirma la coincidencia exacta en Python.
        for campo in _campos_alias_existentes():
            page, ok_alias = _consultar_usuario_ok(
                {"property": campo, "rich_text": {"contains": email}},
                email, verificar=True,
            )
            ok = ok and ok_alias
            if page is not None:
                break
    if page is None:
        return None, ok
    return _perfil_de_pagina(page), True


def _perfil_de_pagina(page: dict) -> dict:
    p = page.get("properties", {})
    return {
        "notion_id":          page.get("id", ""),
        "nombre":             (p.get("Name", {}).get("title") or [{}])[0].get("plain_text", ""),
        "email":              p.get("Email", {}).get("email", ""),
        "email_cv":           (p.get("Email CV", {}).get("email", "")
                               or (p.get("Email CV", {}).get("rich_text") or [{}])[0].get("plain_text", "")),
        "activo":             p.get("Activo", {}).get("checkbox", False),
        "perfil":             (p.get("Perfil", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
        "rol":                (p.get("Rol objetivo", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
        "stack":              [s["name"] for s in p.get("Stack", {}).get("multi_select", [])],
        "salario_min":        p.get("Salario min", {}).get("number", 0) or 0,
        "modalidad":          [m["name"] for m in p.get("Modalidad", {}).get("multi_select", [])],
        "ciudad":             (p.get("Ciudad", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
        "telefono":           (p.get("Teléfono", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
        "linkedin":           p.get("LinkedIn", {}).get("url", "") or "",
        "cv_master_url":      p.get("CV Master URL", {}).get("url", "") or "",
        "cv_master_url_es":   p.get("CV Master URL ES", {}).get("url", "") or "",
        "cv_master_file_id":  (p.get("cv_master_file_id", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
    }


def buscar_oferta_en_notion(empresa: str, puesto: str) -> dict | None:
    """Busca una oferta en la DB de Ofertas por Empresa + Puesto.

    Sirve para recuperar datos que n8n guardó en Notion al crear la oferta
    pero que no llegan en el body de /generar-cv o /generar-carta (sobre todo
    la Descripción, clave para detectar el idioma). Devuelve dict o None.
    """
    if not NOTION_DB_OFERTAS or not empresa or not puesto:
        return None
    try:
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_OFERTAS}/query",
            headers=notion_headers(),
            json={"filter": {"and": [
                {"property": "Empresa", "title": {"equals": empresa}},
                {"property": "Puesto", "rich_text": {"equals": puesto}},
            ]}, "page_size": 1},
            timeout=15,
        )
    except requests.RequestException as e:
        logger.warning("Notion query oferta falló: %s", e)
        return None
    if resp.status_code != 200:
        logger.warning("Notion query oferta error %s: %s", resp.status_code, resp.text[:200])
        return None
    results = resp.json().get("results", [])
    if not results:
        return None
    p = results[0].get("properties", {})
    return {
        "descripcion":     (p.get("Descripción", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
        "nombre_contacto": (p.get("Nombre Contacto", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
        "idioma":          (p.get("Idioma", {}).get("select") or {}).get("name", ""),
    }


def guardar_link_cv_en_notion(empresa: str, puesto: str, link_drive: str,
                              nombre_archivo: str) -> bool:
    """Escribe el enlace del CV en la ficha de la oferta, aqui y ahora.

    Nace el 30jul2026. Hasta hoy este enlace lo escribia n8n DESPUES de recibir
    la respuesta de /generar-cv, en una rama paralela a la del email. El nodo que
    llama aqui tiene timeout de 120s: con Sonnet la generacion se pasa de ahi,
    n8n aborta, y este servidor termina y sube el DOCX a Drive igualmente. El
    resultado es un CV huerfano — existe en Drive, y ni la ficha ni Veronica se
    enteran. Paso tres veces el mismo dia (tres empresas distintas).

    El enlace se escribe donde se sube el fichero para que la invariante sea
    cierta por construccion: si el CV existe, el enlace existe. Lo que haga n8n
    despues deja de importar para esto.

    Best-effort a proposito: si Notion falla, se loguea y se sigue. Un CV
    generado no se tira por no haber podido anotarlo.
    """
    if not NOTION_DB_OFERTAS or not empresa or not puesto or not link_drive:
        return False
    try:
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_OFERTAS}/query",
            headers=notion_headers(),
            json={"filter": {"and": [
                {"property": "Empresa", "title": {"equals": empresa}},
                {"property": "Puesto", "rich_text": {"equals": puesto}},
            ]}, "page_size": 1},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("Notion: query oferta %s error %s", empresa, resp.status_code)
            return False
        results = resp.json().get("results", [])
        if not results:
            logger.warning("Notion: no se encontro la oferta %s / %s para anotar el CV",
                           empresa, puesto)
            return False

        page_id = results[0]["id"]
        patch = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=notion_headers(),
            json={"properties": {
                "Link CV Drive": {"url": link_drive},
                "CV usado": {"rich_text": [{"text": {"content": nombre_archivo[:2000]}}]},
            }},
            timeout=15,
        )
        if patch.status_code != 200:
            logger.warning("Notion: patch link CV error %s: %s",
                           patch.status_code, patch.text[:200])
            return False
        logger.info("Notion: enlace del CV anotado en %s / %s", empresa, puesto)
        return True
    except requests.RequestException as e:
        logger.warning("Notion: no se pudo anotar el enlace del CV: %s", e)
        return False


def _extraer_drive_file_id(url: str) -> str:
    """Extrae el file ID de una URL de Google Drive."""
    import re
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', url) or re.search(r'id=([a-zA-Z0-9_-]+)', url)
    return m.group(1) if m else ""


def crear_usuario_en_notion(datos: dict) -> dict:
    """Crea un usuario en la BD de Notion."""
    url = "https://api.notion.com/v1/pages"
    cv_master_url = datos.get("cv_master_url") or ""
    cv_master_file_id = _extraer_drive_file_id(cv_master_url) if cv_master_url else ""
    props = {
        "Name":           {"title":  [{"text": {"content": datos.get("nombre", "")}}]},
        "Email":          {"email":   datos.get("email", "")},
        "Perfil":         {"rich_text": [{"text": {"content": datos.get("perfil", "")}}]},
        "Rol objetivo":   {"rich_text": [{"text": {"content": datos.get("rol_objetivo", "") or datos.get("rol", "")}}]},
        "Stack":          {"multi_select": [{"name": s} for s in datos.get("stack", [])]},
        "Salario min":    {"number": datos.get("salario_min") or datos.get("salario") or 0},
        "Modalidad":      {"multi_select": [{"name": m} for m in datos.get("modalidad", [])]},
        "Ciudad":         {"rich_text": [{"text": {"content": datos.get("ciudad", "")}}]},
        "LinkedIn":       {"url": datos.get("linkedin") or None},
        "CV Master URL":  {"url": cv_master_url or None},
        "Activo":         {"checkbox": True},
    }
    if cv_master_file_id:
        props["cv_master_file_id"] = {"rich_text": [{"text": {"content": cv_master_file_id}}]}
    # Filtrar propiedades con valor None que Notion rechaza
    payload = {
        "parent": {"database_id": NOTION_DB_USUARIOS},
        "properties": {k: v for k, v in props.items() if v is not None and v != {"url": None}},
    }
    resp = requests.post(url, headers=notion_headers(), json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def crear_oferta_en_notion(oferta: dict, idioma: str = "", usuario_notion_id: str = "") -> dict:
    """Crea una oferta en la DB Ofertas con TODOS sus campos mapeados.

    Centraliza el mapeo oferta→Notion en código (en vez de la UI de n8n).
    `oferta` es el dict que devuelve /buscar-ofertas-reales (real_jobs.py).
    """
    if not NOTION_DB_OFERTAS:
        # Same family of error the caller already turns into a 502; no request is made.
        raise requests.RequestException("NOTION_DB_OFERTAS no configurada")

    def _txt(v: str) -> dict:
        return {"rich_text": [{"text": {"content": (v or "")[:2000]}}]}

    props = {
        "Empresa":       {"title": [{"text": {"content": oferta.get("empresa", "")}}]},
        "Puesto":        _txt(oferta.get("puesto", "")),
        "Descripción":   _txt(oferta.get("descripcion", "")),
        "Salario":       _txt(oferta.get("salario", "")),
        "Ubicación":     _txt(oferta.get("ubicacion", "")),
        "Tipo Contrato": _txt(oferta.get("tipo_contrato", "")),
        "Estado":        {"select": {"name": "Pendiente"}},
    }
    modalidad = oferta.get("modalidad", "")
    if modalidad in ("Remoto", "Hibrido", "Presencial"):
        props["Modalidad"] = {"select": {"name": modalidad}}
    tags = [t for t in (oferta.get("tags") or []) if t]
    if tags:
        props["Tags"] = {"multi_select": [{"name": t[:100]} for t in tags]}
    if oferta.get("link"):
        props["Link oferta"] = {"url": oferta["link"]}
    if oferta.get("fecha_publicacion"):
        props["Fecha Publicacion"] = {"date": {"start": oferta["fecha_publicacion"]}}
    if idioma in ("en", "es"):
        props["Idioma"] = {"select": {"name": idioma}}
    if usuario_notion_id:
        props["Usuario"] = {"relation": [{"id": usuario_notion_id}]}

    payload = {"parent": {"database_id": NOTION_DB_OFERTAS}, "properties": props}
    resp = requests.post("https://api.notion.com/v1/pages",
                         headers=notion_headers(), json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()
