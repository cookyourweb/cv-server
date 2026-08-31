"""Guardrails de veracidad: comprueban lo generado contra el CV Master.

Seis detectores y el constructor del titular. Todos reciben el texto generado y
el texto del Master, y devuelven una lista de hallazgos. **Avisan, no bloquean**:
un aviso puede ser una reformulacion legitima, y abortar dejaria a la usuaria sin
documento.

Cinco miran la SALIDA y uno la ENTRADA (`evaluar_descripcion_oferta`): un CV
generico no inventa nada, simplemente no dice nada, y sin mirar la entrada un
`ok: true` esconde que no habia material que adaptar.

Extraido de `server.py` el 28-ago-2026. No importa nada del servidor:
solo `os` y `re`, asi que se puede leer y probar aislado.
"""
import os
import re

_NUM_RE = re.compile(r"\d[\d.,]*")

# Magnitudes en texto: no llevan digitos pero cuantifican igual.
_MAGNITUDES = (
    "millones", "millón", "millon", "millions", "million",
    "miles", "thousands", "thousand",
    "cientos", "hundreds",
    "billones", "billions",
)


def _normalizar_cifra(crudo: str) -> str:
    """166.000 y 166,000 son el MISMO dato escrito en dos idiomas."""
    return crudo.replace(".", "").replace(",", "").lstrip("0") or "0"


def detectar_cifras_no_respaldadas(cv_texto: str, master_texto: str) -> list:
    """Cifras del CV generado que NO aparecen en el CV Master.

    Devuelve la lista de fragmentos sospechosos (vacia si todo esta respaldado).
    Los años se ignoran: son fechas, no metricas. Sin master no se alerta:
    no hay fuente contra la que contrastar."""
    if not cv_texto or not master_texto:
        return []

    respaldadas = {_normalizar_cifra(m.group(0)) for m in _NUM_RE.finditer(master_texto)}

    sospechosas = set()
    for m in _NUM_RE.finditer(cv_texto):
        norm = _normalizar_cifra(m.group(0))
        if norm.isdigit() and 1900 <= int(norm) <= 2100:  # es un año, no una metrica
            continue
        if norm not in respaldadas:
            sospechosas.add(m.group(0).rstrip(".,"))

    master_low = master_texto.lower()
    cv_low = cv_texto.lower()
    for palabra in _MAGNITUDES:
        if re.search(rf"\b{palabra}\b", cv_low) and not re.search(rf"\b{palabra}\b", master_low):
            sospechosas.add(palabra)

    return sorted(sospechosas)


# Catalogo de tecnologias, con sus variantes de escritura mapeadas al nombre que se
# reporta. Sin catalogo habria que decidir si cada sustantivo del CV es una tecnologia,
# y eso no se puede hacer bien: se marcarian palabras normales.
# Las variantes existen porque "Vue" y "Vue.js" son lo mismo, y marcar una teniendo la
# otra en el master seria una falsa alarma.
_TEC_ALIAS = {}


def _reg_tec(canonico: str, *variantes: str) -> None:
    _TEC_ALIAS[canonico.lower()] = canonico
    for v in variantes:
        _TEC_ALIAS[v.lower()] = canonico


# Lenguajes
for _t in ("JavaScript", "Python", "PHP", "Java", "Kotlin", "Swift", "Ruby", "Rust",
           "Scala", "Perl", "Elixir", "Dart", "C#", "C++", "Objective-C", "COBOL", "ABAP"):
    _reg_tec(_t)
_reg_tec("TypeScript", "TS")
_reg_tec("Golang", "Go lang")
# Frontend
for _t in ("Svelte", "Ember", "Backbone", "jQuery", "Redux", "Zustand", "RxJS", "Tailwind",
           "Bootstrap", "Sass", "SCSS", "Webpack", "Vite", "Rollup", "Babel", "Storybook",
           "HTML5", "CSS3", "Ionic", "Astro", "Qwik", "Solid.js", "Alpine.js"):
    _reg_tec(_t)
_reg_tec("React", "ReactJS", "React.js")
_reg_tec("React Native")
_reg_tec("Vue.js", "Vue", "VueJS")
_reg_tec("Angular", "AngularJS", "Angular 2+")
_reg_tec("Next.js", "NextJS", "Next")
_reg_tec("Nuxt", "Nuxt.js", "NuxtJS")
# Backend y frameworks
for _t in ("Symfony", "Laravel", "Django", "Flask", "FastAPI", "NestJS", "Deno", "Bun",
           "CodeIgniter", "Zend", "Struts", "Hibernate", "Quarkus", "Micronaut"):
    _reg_tec(_t)
_reg_tec(".NET", "ASP.NET", "dotnet", ".NET Core")
_reg_tec("Spring Boot", "Spring", "Spring Framework")
_reg_tec("Node.js", "NodeJS", "Node")
_reg_tec("Express", "Express.js", "ExpressJS")
_reg_tec("Ruby on Rails", "Rails")
# Templating de servidor
for _t in ("Twig", "Blade", "Thymeleaf", "Handlebars", "Mustache", "Pug", "Jinja", "ERB",
           "Smarty", "Freemarker", "Razor", "JSP"):
    _reg_tec(_t)
# Datos
for _t in ("MongoDB", "MySQL", "Oracle", "Redis", "Elasticsearch", "DynamoDB", "Firebase",
           "Supabase", "Prisma", "GraphQL", "SQLite", "Cassandra", "MariaDB", "Neo4j"):
    _reg_tec(_t)
_reg_tec("PostgreSQL", "Postgres")
_reg_tec("SQL Server", "MSSQL")
# Infraestructura
for _t in ("Docker", "Kubernetes", "Terraform", "Jenkins", "AWS", "Azure", "Vercel",
           "Netlify", "Render", "Railway", "Nginx", "Apache", "Ansible", "Heroku"):
    _reg_tec(_t)
_reg_tec("GCP", "Google Cloud")
_reg_tec("Kubernetes", "K8s")
# Testing
for _t in ("Jest", "Cypress", "Playwright", "Vitest", "Selenium", "JUnit", "Pytest",
           "Mocha", "Jasmine", "Karma"):
    _reg_tec(_t)
_reg_tec("Testing Library", "React Testing Library", "RTL")
# CMS y comercio
for _t in ("WordPress", "Drupal", "Shopify", "Strapi", "Contentful", "Magento", "Joomla",
           "Prestashop", "Sitecore", "AEM"):
    _reg_tec(_t)
# IA y herramientas
for _t in ("Claude Code", "Cursor", "LangChain", "TensorFlow", "PyTorch",
           "Hugging Face", "Ollama", "Pandas", "NumPy", "Git", "Jira", "Figma"):
    _reg_tec(_t)
# El nombre corto tambien cuenta: el CV de N-iX (24jul2026) colo "Copilot-class AI
# systems" sin respaldo del Master y el guardrail no salto, porque solo estaba dado de
# alta "GitHub Copilot" y el patron usa fronteras de palabra.
_reg_tec("GitHub Copilot", "Copilot")

# Se buscan primero los nombres largos: en "Spring Boot" no debe reportarse ademas
# "Spring", ni en "React Native" un "React" suelto.
_TEC_PATRONES = [
    (variante, re.compile(rf"(?<![A-Za-z0-9]){re.escape(variante)}(?![A-Za-z0-9])", re.IGNORECASE))
    for variante in sorted(_TEC_ALIAS, key=len, reverse=True)
]


def _tecnologias_en(texto: str) -> set:
    """Nombres canonicos de las tecnologias del catalogo presentes en el texto.

    Consume los tramos ya reconocidos para que un nombre corto no vuelva a saltar
    dentro de uno largo que ya se ha identificado."""
    if not texto:
        return set()
    restante = texto
    encontradas = set()
    for variante, patron in _TEC_PATRONES:
        nuevo, n = patron.subn(" ", restante)
        if n:
            encontradas.add(_TEC_ALIAS[variante])
            restante = nuevo
    return encontradas


def detectar_tecnologias_no_respaldadas(cv_texto: str, master_texto: str) -> list:
    """Tecnologias que el CV generado atribuye a la candidata y NO estan en su Master.

    Regla de evidencia: una tecnologia entra en el CV solo si el Master la respalda.
    El prompt ya lo prohibe y el modelo lo hizo igual (PHP/Symfony en la oferta de
    Tenth Revolution, 23jul2026), asi que se verifica la salida.

    Sin master no se alerta: no hay fuente contra la que contrastar."""
    if not cv_texto or not master_texto:
        return []
    return sorted(_tecnologias_en(cv_texto) - _tecnologias_en(master_texto))


# ── Guardrail de veracidad: skills declaradas sin respaldo ───────────────────
# El detector de arriba solo ve lo que esta dado de alta en el catalogo, y lo que
# el modelo copia es el stack NUEVO de cada oferta: en el CV de Koinly (11ago2026)
# entraron enteros "React 19 · Tailwind (v4) · Radix UI · Mantine" y "TanStack
# Query" sin que saltara nada, porque ninguno de los cuatro estaba en las 173
# variantes. No es un descuido de la lista: una lista blanca no puede cubrir un
# mundo abierto, y el mundo abierto es justo de donde sale el riesgo.
#
# Aqui se invierte el sentido. La seccion de skills es una lista de AFIRMACIONES
# separadas por puntos, y cada una se contrasta contra el Master venga de donde
# venga. El mundo cerrado pasa al lado correcto: el de lo que el CV afirma.

_CABECERAS_SKILLS = {
    "technical skills", "skills", "competencias tecnicas", "competencias técnicas",
    "habilidades tecnicas", "habilidades técnicas", "stack tecnico", "stack técnico",
}

_SEP_SKILLS = re.compile(r"\s*[·•]\s*")
_PARENTESIS = re.compile(r"\(([^)]*)\)")

# Describen COMO se usa una herramienta, no una herramienta aparte: "TypeScript
# (strict)" no afirma nada que el Master tenga que respaldar por separado.
_CALIFICADORES = {
    "strict", "estricto", "avanzado", "advanced", "basico", "básico", "basic",
    "intermedio", "intermediate", "experta", "experto", "expert", "senior",
}


def _normalizar_skill(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "").strip().lower())


def _lineas_de_skills(cv_texto: str) -> list:
    """Lineas que hay DENTRO de la seccion de skills.

    Solo esa seccion: la cabecera del CV y las lineas de empresas tambien llevan
    puntos separadores, y analizarlas llenaria el aviso de ruido."""
    dentro, out = False, []
    for linea in (cv_texto or "").splitlines():
        desnuda = linea.strip().lstrip("#").strip()
        if _normalizar_skill(desnuda).rstrip(":") in _CABECERAS_SKILLS:
            dentro = True
            continue
        if not dentro:
            continue
        # Otra cabecera en mayusculas (EDUCATION, LANGUAGES) cierra la seccion.
        if desnuda and "·" not in desnuda and desnuda == desnuda.upper():
            break
        if desnuda:
            out.append(desnuda)
    return out


def _afirmaciones_de(item: str) -> list:
    """Todo lo que un elemento de la lista afirma.

    Cuenta la base y tambien lo que va entre parentesis, que es donde se
    esconden herramientas enteras: "Vue.js (Composition API, Pinia)"."""
    base = _PARENTESIS.sub("", item).strip()
    dentro = [p.strip() for m in _PARENTESIS.finditer(item)
              for p in m.group(1).split(",") if p.strip()]
    return [base] + dentro


def detectar_skills_no_respaldadas(cv_texto: str, master_texto: str) -> list:
    """Skills que el CV declara y el Master no respalda, verificadas una a una.

    Sin master no se alerta: no hay fuente contra la que contrastar."""
    if not cv_texto or not master_texto:
        return []

    master = _normalizar_skill(master_texto)
    marcadas = []
    for linea in _lineas_de_skills(cv_texto):
        etiqueta, dos_puntos, valores = linea.partition(":")
        if not dos_puntos:                      # sin etiqueta de grupo
            if "·" not in linea:                # ni lista: no es linea de skills
                continue
            valores = linea
        for item in _SEP_SKILLS.split(valores):
            item = item.strip(" .;")
            if not item:
                continue
            respaldada = all(
                _normalizar_skill(a) in master
                for a in _afirmaciones_de(item)
                if _normalizar_skill(a) and _normalizar_skill(a) not in _CALIFICADORES
            )
            if not respaldada and item not in marcadas:
                marcadas.append(item)
    return sorted(marcadas)


# ── Guardrail del TITULAR: que no se salga del contrato del PERFIL BASE ──────────
# El 24jul2026 se desplegaron las reglas del titular ancla y los DOS CV regenerados
# (N-iX y Revolut) salieron con el orden de "Variante permitida", cuya condicion no
# cumplia ninguna de las dos empresas. El modelo leyo el parentesis de la condicion
# como ejemplos. Mismo patron que dejo pasar "Leader" en el guardrail de seniority.
# Leccion medida: la regla en el prompt es DISCIPLINA; solo el detector es MECANISMO.

_SEP_TITULAR = re.compile(r"\s*[|·]\s*")
_VINETA = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")

# Nombres de seccion del contrato: sirven para saber donde ACABA la seccion buscada.
_SECCIONES_PB = {
    "identidad profesional", "identidades permitidas", "orden del titular",
    "variante permitida", "nunca permitido", "roles objetivo", "resumen profesional",
    "especializacion actual", "especialización actual",
    "tecnologias principales", "tecnologías principales",
}


def _cabecera(linea: str) -> str:
    """Nombre de seccion de una linea, sin almohadillas ni dos puntos. '' si no lo es."""
    return linea.strip().lstrip("#").strip().rstrip(":").lower()


def _seccion_perfil_base(master: str, nombre: str) -> str:
    """Contenido de una seccion del PERFIL BASE. Cadena vacia si no existe.

    Tolerante con el formato: Google Docs exporta a texto plano y puede haberse
    comido las almohadillas, asi que se reconoce la cabecera por su NOMBRE."""
    objetivo = nombre.lower()
    dentro, out = False, []
    for linea in (master or "").splitlines():
        cab = _cabecera(linea)
        if not dentro:
            dentro = cab == objetivo
            continue
        if linea.strip().startswith("#") or cab in _SECCIONES_PB:
            break
        s = linea.strip()
        # Cabecera del CV en mayusculas (POSICIONAMIENTO, EXPERIENCIA...): fin de bloque
        if s and s == s.upper() and len(s) > 3 and any(c.isalpha() for c in s):
            break
        out.append(linea)
    return "\n".join(out).strip()


def _identidades_declaradas(master: str) -> list:
    bloque = _seccion_perfil_base(master, "Identidades permitidas")
    return [_VINETA.sub("", l).strip() for l in bloque.splitlines() if _VINETA.sub("", l).strip()]


def _partir_titular(titular: str, permitidas: list) -> tuple:
    """Separa el titular en (identidades reconocidas, resto de segmentos)."""
    por_nombre = {p.lower(): p for p in permitidas}
    ident, otros = [], []
    for seg in (s.strip() for s in _SEP_TITULAR.split(titular or "") if s.strip()):
        canon = por_nombre.get(seg.lower())
        (ident if canon else otros).append(canon or seg)
    return ident, otros


def _huecos(linea: str) -> list:
    """Huecos del titular. Solo parte por '|': el '·' vive DENTRO de un hueco."""
    return [h.strip() for h in (linea or "").split("|") if h.strip()]


def _es_identidad(hueco: str, permitidas: list) -> str:
    """Nombre canonico si el hueco es una identidad declarada, si no ''."""
    for p in permitidas:
        if hueco.strip().lower() == p.lower():
            return p
    return ""


def _respaldado(modificador: str, master_texto: str) -> bool:
    """El Master avala el modificador si avala todas sus palabras con contenido.

    Palabra a palabra y no la frase entera: el Master dice "LLM integration" y el
    modelo propone "LLM Systems". Exigir la frase literal obligaria a escribir en el
    Master cada forma posible de nombrar lo mismo."""
    master_low = (master_texto or "").lower()
    palabras = [p for p in re.split(r"[^\wÁÉÍÓÚÜÑáéíóúüñ+#.]+", modificador or "") if len(p) > 2]
    return bool(palabras) and all(p.lower() in master_low for p in palabras)


def _mancha_seniority(hueco: str, seniority: str) -> bool:
    """El hueco es la seniority disfrazada, no un modificador.

    31ago2026: cuatro CV salieron con la seniority DOS VECES (dos ya enviados). Aqui
    se comparaba por IGUALDAD EXACTA contra la seniority, y el modelo no la repite:
    propone una VARIANTE. Con la seniority real

        "10+ years in digital product · applying AI in production since 2025"

    colo "10+ years in digital product" (un prefijo) y "10+ years in digital product ·
    AI systems in production since 2025" (otro final). Ninguna es igual, las dos
    pasaban el filtro, y luego la seniority se pegaba otra vez al final.

    La prueba correcta no es la igualdad: es si el hueco habla DE LO MISMO. Se compara
    por el primer tramo antes del "·", que es donde vive el nucleo ("10+ years in
    digital product"). Asi caen el prefijo y todas sus variantes de cola."""
    if not seniority:
        return False
    nucleo = seniority.split("·")[0].strip().lower()
    h = hueco.strip().lower()
    return h == seniority.strip().lower() or bool(nucleo) and h.startswith(nucleo)


def construir_titular(titular_llm: str, master_texto: str) -> str:
    """Ensambla el titular desde el PERFIL BASE en vez de fiarse del modelo.

    Medido 3 veces el 24jul2026: la regla en el prompt no sostiene el titular. El
    modelo invirtio el orden, fusiono identidades con "&" y se comio la seniority.
    Como el contrato es CERRADO (identidades declaradas, orden declarado), no hay nada
    que generar: se rellena un hueco.

    Del titular del modelo solo se aprovechan los MODIFICADORES, y solo si el Master
    los respalda. Sin PERFIL BASE se devuelve lo que dijo el modelo: los Masters
    antiguos siguen funcionando igual."""
    permitidas = _identidades_declaradas(master_texto)
    base = _seccion_perfil_base(master_texto, "Identidad profesional")
    if not permitidas or not base:
        return titular_llm

    base = base.splitlines()[0]
    identidades, resto = [], []
    for hueco in _huecos(base):
        canon = _es_identidad(hueco, permitidas)
        (identidades if canon else resto).append(canon or hueco)
    if not identidades:
        return titular_llm

    # El ultimo hueco no-identidad del PERFIL BASE es la seniority: nunca se sustituye.
    seniority = resto[-1] if resto else ""
    modificadores_base = resto[:-1]

    # Un hueco que CONTIENE una identidad no es un modificador: es una identidad mal
    # escrita: dos identidades fusionadas con "&", o una con un sufijo de rango pegado.
    def _mancha_identidad(h: str) -> bool:
        return any(re.search(rf"\b{re.escape(p)}", h, re.IGNORECASE) for p in permitidas)

    propuestos = [
        h for h in _huecos(titular_llm)
        if not _es_identidad(h, permitidas)
        and not _mancha_identidad(h)
        and not _mancha_seniority(h, seniority)
        and _respaldado(h, master_texto)
    ][:2]

    return " | ".join(identidades + (propuestos or modificadores_base)
                      + ([seniority] if seniority else []))


# Numeros escritos con letra: "ocho años" y "8 años" son la misma afirmacion, y el
# modelo escribe la primera forma con mucha mas frecuencia que la segunda.
_NUM_PALABRA = {
    "un": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20,
}

# Las palabras van de mas larga a mas corta para que "dieciseis" gane a "diez".
_ANIOS_RE = re.compile(
    r"\b(\d{1,2}|" + "|".join(sorted(_NUM_PALABRA, key=len, reverse=True)) + r")\s*\+?\s*a[nñ]os\b",
    re.IGNORECASE,
)


def _valor_anios(bruto: str) -> int:
    bruto = bruto.lower()
    return int(bruto) if bruto.isdigit() else _NUM_PALABRA[bruto]


def detectar_experiencia_mal_atribuida(texto: str, master_texto: str) -> list:
    """Años de experiencia que el texto le pega a una tecnologia y el Master a otra.

    El hueco que cubre: los tres guardrails anteriores comprueban si algo EXISTE
    en el Master. Aqui se comprueba a QUIEN pertenece. Caso real del 18ago2026:
    el Master dice `Vue.js - 8 años` y la carta escribio "mas de ocho años con
    React y TypeScript". React existe, el 8 existe, y la frase es falsa.

    Es mas peligroso que una invencion: una tecnologia inventada se cae en la
    primera pregunta, unos años mal atribuidos aguantan hasta la entrevista
    tecnica. Sin master no se alerta: no hay fuente contra la que contrastar."""
    if not texto or not master_texto:
        return []

    # Los años son del nombre que tienen AL LADO, no de toda la linea. El Master
    # real escribe "Vue.js (8 años), React, Angular, TypeScript, ..." en una sola
    # linea, y leyendo la linea entera esos ocho años se repartirian entre las once
    # tecnologias de la lista: React quedaria respaldado y la regla no serviria de
    # nada. Paso el 18-ago-2026, con el detector en verde en sus propios tests.
    # Se parte por comas y puntos y coma. Las filas de una tabla no llevan comas,
    # asi que siguen entrando enteras y el numero sigue encontrando a su tecnologia.
    duenas_por_anios = {}
    for linea in master_texto.splitlines():
        for trozo in re.split(r"[,;]", linea):
            for m in _ANIOS_RE.finditer(trozo):
                duenas_por_anios.setdefault(_valor_anios(m.group(1)), set()).update(
                    _tecnologias_en(trozo)
                )

    # El texto generado se lee por FRASES, no por lineas: el salto de linea de un
    # parrafo justificado parte "ocho\naños" y se perderia la afirmacion.
    marcadas = set()
    for frase in re.split(r"[.;:]", " ".join(texto.split())):
        for m in _ANIOS_RE.finditer(frase):
            duenas = duenas_por_anios.get(_valor_anios(m.group(1)))
            if not duenas:
                continue        # el Master no asigna esos años a ninguna tecnologia
            for tec in _tecnologias_en(frase) - duenas:
                marcadas.add(
                    f"{tec}: se le atribuyen {_valor_anios(m.group(1))} años que el "
                    f"Master asigna a {', '.join(sorted(duenas))}"
                )
    return sorted(marcadas)


def detectar_titular_fuera_de_contrato(titular: str, master_texto: str) -> list:
    """Avisos si el titular generado no respeta el contrato del PERFIL BASE.

    Comprueba tres cosas: que las identidades sean las declaradas, que vayan en el
    orden declarado, y que no aparezca una identidad declarada con un sufijo de rango
    pegado detras, que es como se cuela una seniority que el PERFIL BASE no da.

    No aborta ni decide: la condicion de la Variante permitida depende de la empresa
    y eso no se puede verificar por codigo. Informa para que la persona lo revise."""
    permitidas = _identidades_declaradas(master_texto)
    base = _seccion_perfil_base(master_texto, "Identidad profesional")
    if not titular or not permitidas or not base:
        return []  # sin contrato no hay nada contra lo que contrastar

    esperadas, _ = _partir_titular(base.splitlines()[0], permitidas)
    if not esperadas:
        return []

    avisos = []
    actuales, otros = _partir_titular(titular, permitidas)

    # Una identidad declarada con un sufijo de rango pegado detras.
    # Solo frontera de palabra por delante: por detras la rompe el propio sufijo.
    for seg in otros:
        for ident in permitidas:
            if re.search(rf"\b{re.escape(ident)}", seg, re.IGNORECASE):
                avisos.append(
                    f"Identidad no permitida en el titular: {seg!r}. El PERFIL BASE solo "
                    f"declara {permitidas}."
                )
                break

    if actuales != esperadas:
        variante = _seccion_perfil_base(master_texto, "Variante permitida")
        lineas_var = [l for l in variante.splitlines() if l.strip()]
        if lineas_var:
            de_variante, _ = _partir_titular(lineas_var[0], permitidas)
            if de_variante and actuales == de_variante:
                avisos.append(
                    "El titular usa la Variante permitida. Solo es valida si esta oferta "
                    "cumple la condicion declarada en el PERFIL BASE; verificalo antes de enviar."
                )
        avisos.append(
            f"El orden de las identidades no coincide con 'Identidad profesional': "
            f"esperado {esperadas}, generado {actuales}."
        )
    return avisos


# Marcadores que deja el scraper cuando NO pudo leer la oferta. Su presencia
# invalida la descripcion aunque venga con relleno alrededor.
_MARCADORES_SCRAPER = (
    "detalles limitados",
    "sin verificacion de estado",
    "sin verificación de estado",
    "no tener acceso a chrome",
)

DESCRIPCION_MINIMA = int(os.getenv("DESCRIPCION_MINIMA", "400"))


def evaluar_descripcion_oferta(descripcion: str, minimo: int = None) -> dict:
    """¿Tiene la descripcion material suficiente para ADAPTAR el CV?

    El prompt adapta el CV leyendo este campo. Si llega el titular reformulado en
    dos lineas, el CV sale generico y `ok: true` no lo delata. Esto no rechaza la
    peticion: avisa, igual que `cifras_no_respaldadas` y `tecnologias_no_respaldadas`.

    Umbral por datos reales (27jul2026): las ofertas de Tecnoempleo y Remotive traen
    991-1800 caracteres; las de LinkedIn e Indeed, 172-245. 400 separa ambos grupos
    con margen. Configurable con DESCRIPCION_MINIMA.
    """
    minimo = DESCRIPCION_MINIMA if minimo is None else minimo
    texto = (descripcion or "").strip()
    bajo = texto.lower()

    if any(m in bajo for m in _MARCADORES_SCRAPER):
        return {
            "suficiente": False,
            "chars": len(descripcion or ""),
            "aviso": (
                "La descripcion lleva el marcador del scraper ('Detalles limitados'): "
                "la oferta no se pudo leer de LinkedIn/Indeed y lo guardado es un resumen, "
                "no el anuncio. Pega la descripcion real en Notion antes de generar el CV."
            ),
        }

    if len(texto) < minimo:
        return {
            "suficiente": False,
            "chars": len(descripcion or ""),
            "aviso": (
                f"La descripcion tiene {len(texto)} caracteres (minimo {minimo}). "
                "No hay material que adaptar: el CV saldra generico. Las ofertas de "
                "LinkedIn e Indeed suelen llegar asi; pega el anuncio real en Notion."
            ),
        }

    return {"suficiente": True, "chars": len(descripcion or ""), "aviso": ""}


# ══════════════════════════════════════════════
# REGISTRO DE GUARDRAILS
# ══════════════════════════════════════════════
# Antes cada endpoint enumeraba los detectores a mano, asi que anadir el septimo
# obligaba a modificar `/generar-cv` y `/generar-carta`. Aqui el contrato es uno
# solo y cada guardrail declara a que documentos se aplica: quien llama pide
# `guardrails_para("carta")` y no necesita saber cuantos hay ni cuales.

from dataclasses import dataclass
from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict

CV = "cv"
CARTA = "carta"


class Guardrail(Protocol):
    """Lo que cualquier guardrail tiene que ofrecer. Nada mas.

    Un `Protocol` no se hereda: cualquier objeto con estos tres miembros vale.
    El contrato es UN metodo a proposito, para que nadie tenga que implementar
    lo que no usa.

    ═══ SI VAS A ESCRIBIR UN GUARDRAIL NUEVO, LEE ESTO ═══

    La regla: **el sustituto puede prometer MAS, nunca menos.** Quien te llama no
    sabe cual de los guardrails le ha tocado, asi que todos tienen que
    comportarse igual ante la misma llamada. Si el tuyo promete menos, rompes a
    quien llama sin que quien llama haya cambiado una linea.

    Las tres formas de romperlo, y las tres pasan de verdad:

    1. NO devuelvas `None` cuando no encuentres nada. Devuelve `[]`. Quien llama
       hace `if encontrados:` y luego recorre: un `None` pasa el `if` de largo
       pero revienta al recorrer.
    2. NO lances excepciones que los demas no lanzan. Si el master llega vacio,
       devuelve `[]`; los otros seis lo hacen.
    3. NO exijas mas que los demas. Si todos aceptan texto vacio, el tuyo tambien.

    `tests/test_registro_guardrails.py::test_son_sustituibles_entre_si` te lo
    comprueba: pasa el caso mas hostil a todos y exige que ninguno lance y que
    todos devuelvan lista.
    """

    nombre: str
    aplica_a: frozenset
    def revisar(self, texto: str, master: str) -> list: ...


@dataclass(frozen=True)
class _Detector:
    """Envuelve una funcion detectora para que cumpla el contrato.

    Las funciones ya estaban escritas y probadas: no se reescriben, se adaptan.
    """

    nombre: str
    aplica_a: frozenset
    funcion: Callable[[str, str], list]

    def revisar(self, texto: str, master: str) -> list:
        return self.funcion(texto, master)


# El reparto vive AQUI, no en los endpoints, porque es el guardrail quien sabe
# de si mismo. `skills_no_respaldadas` no se aplica a la carta a proposito: lee
# lineas de skills separadas por puntos, y una carta es prosa.
GUARDRAILS = [
    _Detector("cifras_no_respaldadas", frozenset({CV, CARTA}), detectar_cifras_no_respaldadas),
    _Detector("tecnologias_no_respaldadas", frozenset({CV, CARTA}), detectar_tecnologias_no_respaldadas),
    _Detector("skills_no_respaldadas", frozenset({CV}), detectar_skills_no_respaldadas),
    # OJO: hoy solo se aplica a la carta. En el CV nunca se llego a aplicar, y
    # ese hueco se conserva aqui a proposito: cambiar comportamiento dentro de un
    # refactor es como se rompen las cosas en silencio. Anotado para decidirlo.
    _Detector("experiencia_mal_atribuida", frozenset({CARTA}), detectar_experiencia_mal_atribuida),
]


def guardrails_para(destino: str) -> list:
    """Los guardrails que aplican a un documento: `CV` o `CARTA`."""
    return [g for g in GUARDRAILS if destino in g.aplica_a]


class Aviso(BaseModel):
    """Lo que un guardrail encontro. Es la forma que SALE POR HTTP.

    Antes era un dict con dos claves y ese contrato no vivia en ningun sitio:
    `server.py` hacia `aviso["hallazgos"]` de memoria. Un renombrado de clave no
    rompia ni un test y reventaba en produccion a mitad de generar una carta.

    Se declara aqui y no en las tripas de los detectores a proposito: **la forma
    se declara donde el dato cruza una frontera**, no en cada paso interno. Los
    siete detectores siguen devolviendo listas de texto, que es lo que son.

    `extra="forbid"` esta puesto para que un typo en un nombre de campo sea un
    error y no un campo nuevo que nadie lee.
    """
    model_config = ConfigDict(extra="forbid")

    regla:     str
    hallazgos: list[str]


def revisar(texto: str, master: str, destino: str) -> list[Aviso]:
    """Pasa el texto por sus guardrails y devuelve solo lo que encontro algo.

    Avisa, no bloquea: la decision de que hacer con los hallazgos es de quien
    llama, no de aqui.

    OJO al serializar: el endpoint que los publica es Flask con `jsonify`, que
    NO sabe convertir un modelo Pydantic. Hay que pasar por `model_dump()`, y
    eso lo vigila `tests/test_aviso_guardrail.py`.
    """
    hallazgos = []
    for g in guardrails_para(destino):
        encontrados = g.revisar(texto, master)
        if encontrados:
            hallazgos.append(Aviso(regla=g.nombre, hallazgos=encontrados))
    return hallazgos
