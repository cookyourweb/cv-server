"""TDD - avisar cuando la DESCRIPCION de la oferta no da material para adaptar el CV.

Caso real (27jul2026): de 15 ofertas pendientes en Notion, 9 traian entre 172 y 245
caracteres de descripcion. No son ofertas: son el titular reformulado, y algunas con
el metacomentario del scraper dentro. Ejemplo literal, de Personio:

    "Senior Frontend Engineer en el dominio de Payroll (nominas) para Personio, con
     sede en Madrid o remoto desde Espana. Detalles limitados: oferta descubierta via
     LinkedIn, sin verificacion de estado por no tener acceso a Chrome/sesion de
     LinkedIn."

Las que SI vienen completas (Tecnoempleo, Remotive) traen entre 991 y 1800.

`generar_cv_core` adapta el CV leyendo ese campo, y hoy solo valida que existan email,
empresa y puesto. Con 200 caracteres genera igual y devuelve `ok: true`: el CV sale
generico y nadie se entera hasta que lo lee un recruiter.

Esto NO rechaza la peticion (rompería el flujo de n8n y a veces se quiere generar
igual). Avisa, como `cifras_no_respaldadas` y `tecnologias_no_respaldadas`.
"""
import server as srv

# Descripcion real de Clipster (Remotive), recortada pero por encima del umbral.
DESCRIPCION_BUENA = """About Clipster: Clipster is where brands and creators connect to
turn views into profits. Clippers clip, remix, and post branded content on TikTok,
YouTube, Instagram and X. We launched our platform in early 2025 and scaled to more
than 100,000 creators. The role: we are looking for a Backend-Heavy Senior Engineer who
isn't afraid to touch the full stack. Your primary domain will be our Golang services
and distributed architecture, but you are a Product Engineer at heart and can jump into
the React/Next.js frontend whenever it's the shortest path to delivering value. The
mindset we hire for: intensity and grit, ambitious simplification, ownership and
mission alignment, and AI readiness with modern tooling."""

# Descripcion real de Personio (LinkedIn), literal.
DESCRIPCION_POBRE = (
    "Senior Frontend Engineer en el dominio de Payroll (nominas) para Personio, con "
    "sede en Madrid o remoto desde Espana. Detalles limitados: oferta descubierta via "
    "LinkedIn, sin verificacion de estado por no tener acceso a Chrome/sesion de "
    "LinkedIn."
)


def test_descripcion_completa_no_avisa():
    assert srv.evaluar_descripcion_oferta(DESCRIPCION_BUENA)["suficiente"] is True


def test_descripcion_corta_avisa():
    assert srv.evaluar_descripcion_oferta(DESCRIPCION_POBRE)["suficiente"] is False


def test_descripcion_vacia_avisa():
    assert srv.evaluar_descripcion_oferta("")["suficiente"] is False


def test_solo_espacios_cuenta_como_vacia():
    assert srv.evaluar_descripcion_oferta("   \n\t  ")["suficiente"] is False


def test_devuelve_el_numero_de_caracteres():
    assert srv.evaluar_descripcion_oferta(DESCRIPCION_POBRE)["chars"] == len(DESCRIPCION_POBRE)


def test_el_aviso_explica_el_motivo():
    aviso = srv.evaluar_descripcion_oferta(DESCRIPCION_POBRE)["aviso"]
    assert aviso, "una descripcion insuficiente debe traer motivo"
    assert "LinkedIn" in aviso or "scraper" in aviso.lower() or "detalles limitados" in aviso.lower()


def test_descripcion_suficiente_no_trae_aviso():
    assert srv.evaluar_descripcion_oferta(DESCRIPCION_BUENA)["aviso"] == ""


def test_el_marcador_del_scraper_avisa_aunque_sea_larga():
    # Una descripcion larga que ARRASTRA el metacomentario sigue sin ser fiable:
    # el scraper no pudo leer la oferta, por mucho relleno que haya alrededor.
    larga_pero_marcada = DESCRIPCION_BUENA + " Detalles limitados: oferta descubierta via LinkedIn."
    assert srv.evaluar_descripcion_oferta(larga_pero_marcada)["suficiente"] is False


def test_el_umbral_se_puede_configurar():
    # Por defecto 400. Una descripcion de ~300 pasa si se baja el umbral.
    media = "x" * 300
    assert srv.evaluar_descripcion_oferta(media)["suficiente"] is False
    assert srv.evaluar_descripcion_oferta(media, minimo=200)["suficiente"] is True
