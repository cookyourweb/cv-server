"""Canario: ningun modelo por defecto puede ser uno que el proveedor ya retiro.

Historia de por que existe este test:
- 19-abr-2026: Anthropic retiro `claude-3-haiku-20240307`. El default de CLAUDE_MODEL
  se quedo apuntando ahi y la cadena de fallback devolvia 404 sin que nadie lo notase,
  porque casi nunca se ejercita.
- 16-ago-2026: Groq retiro `llama-3.3-70b-versatile`. El buscador de ofertas estuvo
  10 dias sin traer una sola oferta y el correo de error culpaba a la memoria.

El fallo es SILENCIOSO: el default solo se usa cuando falta la variable de entorno,
asi que en Render sigue funcionando mientras en local arranca roto. Este test fija
la lista de modelos retirados y revienta si alguno vuelve a colarse como default.

Al retirar un modelo nuevo: anadirlo a MODELOS_RETIRADOS con su fecha.
"""
import server as srv
import real_jobs

MODELOS_RETIRADOS = {
    "llama-3.3-70b-versatile": "Groq, 16-ago-2026",
    "claude-3-haiku-20240307": "Anthropic, 19-abr-2026",
    # Los dos, comprobados contra la API el 28-ago-2026: 404. Google responde
    # "no longer available, please update to models/gemini-3.6-flash".
    "gemini-1.5-flash": "Google, retirado antes del 28-ago-2026",
    "gemini-2.0-flash": "Google, retirado antes del 28-ago-2026",
}


def _defaults():
    return {
        "server.GROQ_MODEL": srv.GROQ_MODEL,
        "server.CLAUDE_MODEL": srv.CLAUDE_MODEL,
        "server.CV_MODEL": srv.CV_MODEL,
        "server.CARTA_MODEL": srv.CARTA_MODEL,
        "server.GEMINI_MODEL": srv.GEMINI_MODEL,
        "real_jobs.GROQ_MODEL_DEFAULT": real_jobs.GROQ_MODEL_DEFAULT,
    }


def test_ningun_default_apunta_a_un_modelo_retirado():
    muertos = {
        nombre: f"{modelo} (retirado por {MODELOS_RETIRADOS[modelo]})"
        for nombre, modelo in _defaults().items()
        if modelo in MODELOS_RETIRADOS
    }
    assert not muertos, f"Defaults apuntando a modelos retirados: {muertos}"
