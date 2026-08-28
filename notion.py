"""Acceso a Notion: usuarios y ofertas.

Las dos bases que usa el sistema. Lee sus credenciales del entorno igual que el
servidor, asi que no importa nada de `server`.

Extraido de `server.py` el 28-ago-2026.
"""
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_USUARIOS = os.getenv("NOTION_DB_USUARIOS", "")
NOTION_DB_OFERTAS = os.getenv("NOTION_DB_OFERTAS", "33d11515-f4b2-8176-947b-000bbafd1ca7")

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


def _consultar_usuario(filtro: dict, email: str, verificar: bool) -> dict | None:
    """Una consulta a Users. Si verificar=True confirma el email exacto en Python."""
    try:
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_USUARIOS}/query",
            headers=notion_headers(),
            json={"filter": filtro, "page_size": 5 if verificar else 1},
            timeout=15,
        )
    except requests.RequestException as e:
        logger.warning("Notion query fallo (%s): %s", filtro.get("property"), e)
        return None
    if resp.status_code != 200:
        # Un 400 aqui suele significar que el campo no existe todavia en la base.
        logger.warning("Notion query error %s (%s): %s",
                       resp.status_code, filtro.get("property"), resp.text[:200])
        return None
    for page in resp.json().get("results", []):
        if not verificar or usuario_atiende(page.get("properties", {}), email):
            return page
    return None


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
    """Consulta Notion por email (principal o alias). Devuelve el perfil o None."""
    if not NOTION_DB_USUARIOS:
        return None
    # verificar=True tambien en la pasada por Email exacto: hay que comprobar que el
    # registro este ACTIVO, cosa que el filtro de Notion no hace.
    page = _consultar_usuario(
        {"property": "Email", "email": {"equals": email}}, email, verificar=True
    )
    if page is None:
        # Segunda pasada por los alias. `contains` es de subcadena, de ahi el
        # verificar=True: se confirma la coincidencia exacta en Python.
        for campo in campos_alias_candidatos():
            page = _consultar_usuario(
                {"property": campo, "rich_text": {"contains": email}},
                email, verificar=True,
            )
            if page is not None:
                break
    if page is None:
        return None
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
    enteran. Paso tres veces el mismo dia (Cactus, Alan, Trivelta).

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
