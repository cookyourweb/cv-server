# CHANGELOG técnico — cv-server

Doc técnico interno del `cv-server` (repo `github.com/cookyourweb/cv-server`, rama `main`).
El `README.md` es la guía de USUARIO (registro y uso diario). Este archivo es el rastro
de POR QUÉ el código hace lo que hace: decisiones, fixes y trampas que no se ven leyendo
el código a secas.

Servicio en producción: `https://cv-server-ggd8.onrender.com` (Render).
Archivo principal: `cv_server_railway.py`. Ranking de ofertas: `real_jobs.py`.

**Decisiones de arquitectura:** ver `docs/ADR-*`.
- [`docs/ADR-001-migracion-fastapi.md`](docs/ADR-001-migracion-fastapi.md) - migración incremental Flask → FastAPI + Pydantic (core puro + wrapper HTTP, coexistencia, TDD).

---

## Modelos LLM (estado actual)

Cadena declarada en la cabecera de `cv_server_railway.py` (v2.3-groq):

- **Ranking de ofertas** (`real_jobs.rankear_con_groq`): Groq `llama-3.3-70b-versatile`
  como primario, con fallback heurístico determinista (`_ranking_fallback`) si no hay
  `GROQ_API_KEY` o la llamada falla. Nunca deja sin resultado.
- **CV adaptado** (`/generar-cv`): Claude Haiku 4.5 (`CV_MODEL`), barato y obediente al
  prompt de adaptación. Va a empresas.
- **Carta de presentación** (`/generar-carta`): Claude Sonnet 4.6 (`CARTA_MODEL`), mejor
  prosa. Va a empresas.
- **Fallbacks generales**: Gemini y Claude quedan como red del texto general.

Todos los modelos se pueden sobreescribir por variable de entorno (`GROQ_MODEL`,
`CV_MODEL`, `CARTA_MODEL`, `GEMINI_MODEL`, `CLAUDE_MODEL`).

**El prompt que adapta el CV y la carta está documentado en
[`docs/PROMPT-ADAPTACION-CV.md`](./docs/PROMPT-ADAPTACION-CV.md)**: estructura en 3 pasos,
HEADLINE RULES, posicionamiento por tipo de oferta y las reglas anti-IA. Léelo antes de
tocar el f-string del prompt en `cv_server_railway.py`.

---

## Julio 2026

### 20-jul — Saneador tipográfico: cero guiones largos ni flechas en CV y carta
Commit `f0ba838`. Nueva función pura `sanear_tipografia(texto, idioma)` en
`cv_server_railway.py:549`.

- **Qué hace**: elimina guiones largos y medios (`—`, `–`) y flechas (`→`) del texto
  final. Las flechas se traducen a la palabra de transición del idioma ("a" en ES,
  "to" en EN); los guiones a guion normal. Es rastro tipográfico de IA y NO puede
  salir a una empresa.
- **Por qué así**: es una red DETERMINISTA. No depende de que el LLM obedezca el prompt.
- **TRAMPA (no romper)**: se aplica solo en el RENDER (DOCX y carta), NUNCA sobre el
  texto que el parser del DOCX usa para detectar estructura. La detección de la línea
  de empresa usa el guion largo como MARCADOR, así que el parser sigue leyendo la línea
  cruda y solo se limpia el texto que se escribe. Si metés un saneado global antes de
  parsear, perdés las negritas y la estructura.
- **Tests**: `test_sanear_tipografia.py` y `test_render_sin_guiones.py`.

### 03-jul — Titulares: identidad real + especialización, y años de experiencia ajustables
Commits `9136979`, `d70a5c6`.

- Sistema de titulares que combina identidad real (Full-Stack e IA delante cuando
  aplica) con resumen adaptado por oferta.
- Años de experiencia: base **10+**, ajustable por oferta. NO clavar 15+.

### 01-jul — Refinado de reglas de CV y seniority del titular
Commits `1c3702a`, `e95cf17`, `5c9d4e5`, `0da513c`.

- Descartar el bloque "ANÁLISIS INTERNO" del CV (no debe salir al documento final).
- El titular MANTIENE la seniority (Tech Lead / Senior); no baja al nivel de la oferta.
- Liderazgo ajustado según el nivel del puesto.
- Reglas de Vero: titular con IA solo en ofertas de IA, Python como herramienta,
  optimización ATS, tono no grandilocuente.

---

## Cambios operativos / entorno (NO están en git)

Estos fixes fueron de configuración en Render o Brevo, no de código. Por eso no dejan
rastro en el historial y por eso se documentan aquí: si alguien clona el repo, no los ve.

### 17-jul — 500 en /generar-cv: token de Google caducado en Render
- **Síntoma**: `/generar-cv` y `/generar-carta` devolvían 500 y rompían la cadena de
  aprobación de ofertas en n8n (al Aprobar no llegaba carta/CV/email).
- **Causa raíz** (confirmada con huellas de token): Render tenía el
  `GOOGLE_REFRESH_TOKEN` VIEJO/caducado (terminaba en `VrpunA`). El `.env` local ya
  tenía el bueno (terminaba en `AxAB_4`).
- **Fix**: actualizar `GOOGLE_REFRESH_TOKEN` en las variables de entorno de Render con
  el valor bueno. Tras redeploy, 200 OK.
- **Nota**: el proyecto de Google Cloud con las credenciales OAuth es
  `sylvan-surf-138623` (OJO: hay dos proyectos llamados "My Project" en la cuenta, no
  fiarse del nombre). Utilidades para regenerar el token: `regenera_token.py`,
  `get_refresh_token.py`, `diagnostico_drive.py`.

### 18-jul — El email de aprobación va por Brevo, no por Gmail
- El mail que se manda al aprobar una oferta sale por **Brevo** (SMTP API), no por Gmail.
- Sender verificado: `veronica@cookyourwebai.es`. La credencial de Brevo en n8n debe
  usar la API key viva y ese sender exacto; un mismatch de sender o key hace que Brevo
  no entregue aunque la petición parezca correcta.
- Prueba directa a `api.brevo.com/v3/smtp/email` con ese sender devuelve 201 y entrega.

---

**Última actualización:** 20 julio 2026
**Fuente de verdad operativa del flujo completo:** `../buscartrabajo/README.md`
