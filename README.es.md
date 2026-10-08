**Español** · [English](README.md)

# cv-server

[![tests](https://github.com/cookyourweb/cv-server/actions/workflows/tests.yml/badge.svg)](https://github.com/cookyourweb/cv-server/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> Cómo se trabaja aquí (ciclo rojo-verde-commit, hook de pre-commit y reglas de
> commit): [`CONTRIBUTING.md`](CONTRIBUTING.md). ¿Vienes a **usar** el servicio y no a
> leer el código? La guía está en [`docs/GUIA-DE-USO.md`](docs/GUIA-DE-USO.md).

**Qué es.** Un servicio que genera el CV y la carta de presentación adaptados a cada
oferta con LLMs, diseñado para no inventar experiencia. Flask en producción, migrándose a FastAPI de
forma incremental.

**Por qué importa.** Un CV con una frase inventada es indefendible en una entrevista, y
un servicio abierto en internet no puede fiarse de quién dice ser quien lo llama.

**Dos problemas difíciles resueltos aquí:**

| Problema | Solución | Dónde leerlo |
|---|---|---|
| Detectar cuándo el LLM inventa | Seis detectores deterministas contra el CV Master: cinco sobre el CV (cuatro se devuelven en la respuesta y uno solo se registra en el log) y tres sobre la carta. Avisan, no bloquean. El titular no se acepta tal cual lo escribe el modelo: se reconstruye de forma determinista desde el `PERFIL BASE` (`construir_titular`) | [El problema interesante](#el-problema-interesante) |
| Que solo entre quien está invitada | Token de Google verificado (OIDC) para personas, clave de máquina para n8n | [Acceso por invitación](#acceso-por-invitación) |

```
Notion (ofertas + perfil) ─┐
                           ├── /generar-cv ── LLM ── guardrails ── Google Drive
CV Master (Google Docs) ───┘
```

**Modelos.** En producción, el CV y la carta los escribe `claude-sonnet-4-6`. Si Claude
falla, cae a Groq (`openai/gpt-oss-120b`), luego Gemini y luego Claude Haiku
(`call_llm_calidad` y `call_llm` en `llm.py`). Cada respuesta informa en `modelo_usado`
del modelo que la escribió de verdad. El modelo lo fijan las variables de entorno
`CV_MODEL` y `CARTA_MODEL`, no el código; `GET /health` muestra los que están activos.

---

## El problema interesante

Adaptar un CV con un LLM es fácil. **Que no mienta, no.**

Un modelo al que le pides "adapta este CV a esta oferta" tiende a acercar el candidato
al puesto: añade una tecnología que la oferta pide, redondea una cifra, sube el alcance
de un rol. Cada una de esas frases es indefendible en una entrevista.

La respuesta de este servicio no es solo el CV: son **seis detectores deterministas**
que comparan el texto generado contra el CV Master. Desde el 28-ago-2026 tres de ellos
se aplican también a la **carta**, que hasta entonces salía sin ninguno. Avisan, no
bloquean.

Respuesta real de `POST /generar-cv` (los campos de guardrails que devuelve hoy; el
resto de campos, como `link` o `consumo`, se omiten):

```json
{
  "ok": true,
  "link": "https://drive.google.com/...",
  "modelo_usado": "claude-sonnet-4-6",
  "cifras_no_respaldadas": [],
  "tecnologias_no_respaldadas": [],
  "titular_fuera_de_contrato": [],
  "descripcion_oferta": { "suficiente": true, "chars": 1694, "aviso": "" }
}
```

| Guardrail | Dónde aplica | Qué detecta | Caso real que lo motivó |
|---|---|---|---|
| `cifras_no_respaldadas` | CV (devuelto) y carta | Números que no están en el CV Master | Cifras de usuarios redondeadas hacia arriba |
| `tecnologias_no_respaldadas` | CV (devuelto) y carta | Tecnologías del catálogo que la oferta pide y el Master no respalda | *"experiencia en arquitecturas PHP/Symfony"* en un perfil sin PHP |
| `skills_no_respaldadas` | CV (solo registrado en el log, hoy no se devuelve) | Cada skill declarada, verificada una a una y sin catálogo | *"React 19 · Tailwind (v4) · Radix UI · Mantine"*: el stack de la oferta, copiado entero |
| `titular_fuera_de_contrato` | CV (devuelto) | Titulares que inventan identidad o suben seniority | El titular copiando el título de la vacante |
| `experiencia_mal_atribuida` | Solo carta (devuelto en `avisos`) | Años de experiencia pegados a la tecnología equivocada | El Master dice *"Vue.js, 8 años"* y la carta escribió *"más de ocho años con React y TypeScript"* |
| `descripcion_oferta` | Entrada del CV (devuelto) | **Entrada** insuficiente para adaptar nada | Ofertas de LinkedIn con 172 caracteres: el titular reformulado |

El de la descripción es el que más cuesta ver: los otros miran la salida, y **un CV
genérico no inventa nada, simplemente no dice nada**. Sin mirar la entrada, `ok: true`
oculta que no había material.

`experiencia_mal_atribuida` cubre un hueco distinto de todos los demás: los otros
comprueban si algo **existe** en el Master, este comprueba **a quién pertenece**. React
existe, el 8 existe, y la frase que los junta es falsa.

### La carta también pasa los guardrails

Hasta el 28-ago-2026 los detectores se aplicaban solo a `contenido_cv`. La carta es lo
PRIMERO que lee un humano, el CV lo abren después, y salía sin verificar. Ahora
`/generar-carta` devuelve `avisos` con lo que encuentre.

Se aplican tres: `experiencia_mal_atribuida`, `tecnologias_no_respaldadas` y
`cifras_no_respaldadas`. `skills_no_respaldadas` queda fuera **a propósito**: lee líneas
de skills separadas por puntos, y una carta es prosa. Aplicarlo ahí daría solo ruido.

Y avisan, no abortan: un aviso puede ser una reformulación legítima, y abortar dejaría a
la usuaria sin carta.

### El quinto guardrail nació del fallo del segundo

`tecnologias_no_respaldadas` funciona con un catálogo de 173 variantes dadas de alta a
mano. Ninguna de las cuatro que se colaron estaba en él, así que fue **ciego** a las
cuatro.

No fue un descuido de la lista. Lo que un modelo copia son las tecnologías **nuevas** de
cada oferta, que por definición no están en un catálogo escrito antes de leerla: una
lista blanca no puede cubrir un mundo abierto.

`skills_no_respaldadas` (hoy solo se registra en el log, no se devuelve en la respuesta)
invierte el sentido. La sección de skills de un CV es una lista
de afirmaciones separadas por puntos, así que cada una se contrasta contra el Master
venga la tecnología de donde venga, sin catálogo de por medio. El mundo cerrado pasa al
lado correcto: el de lo que el CV afirma. Verifica también lo que va dentro de los
paréntesis, donde se esconden herramientas enteras (`Vue 2 and 3 (Composition API,
Pinia)`), y trata las versiones como afirmaciones: si el Master dice "Tailwind" sin
versión, `Tailwind (v4)` se marca.

### Lo que los guardrails NO detectan

La inflación del **alcance del rol**: `coordinated data contracts` pasa a `own the data
contracts`, `Integrated APIs` pasa a `Designed and integrated APIs`. No son tecnologías
ni cifras, así que la comparación contra el Master no las ve. Es semántico y sigue abierto.

Y una limitación de fondo de todos ellos: un guardrail solo puede ser tan bueno como su
fuente de verdad. Si el CV Master está incompleto, marca como no respaldado algo que sí
es real. Los falsos positivos no son un fallo del detector, son agujeros del Master.

### Riesgo conocido: inyección de instrucciones

La descripción de la oferta es texto de terceros y **no está aislada en el prompt**: se
inserta tal cual junto a las instrucciones (`PROMPT_CV` y `PROMPT_CARTA` en `server.py`).
Una oferta maliciosa podría intentar darle órdenes al modelo.

Lo que limita el daño, sin eliminarlo:

- Los detectores comparan contra el CV Master, no contra la oferta. Una tecnología o cifra
  que la oferta le dicte al modelo y que el Master no respalde se marca.
- El titular no se acepta como lo escribe el modelo: se reconstruye desde el `PERFIL BASE`
  (si el Master lo tiene; sin él se usa el del modelo).

No hay hoy un delimitador ni un filtro de instrucciones sobre la oferta.

---

## IA en cifras

| Qué | Dato | Dónde leerlo |
|---|---|---|
| Coste por petición | CV unos 0,05 USD y carta unos 0,013 USD con `claude-sonnet-4-6` (medición del 2-oct-2026, prompt de unos 9.600 tokens de entrada) | [ADR-002](docs/ADR-002-modelo-del-cv.md) |
| Por qué este modelo | Coste medido con `count_tokens` y fallos reales de Haiku | [ADR-002](docs/ADR-002-modelo-del-cv.md) |
| Cadena de respaldo | Claude, luego Groq, luego Gemini, luego Claude Haiku; `modelo_usado` dice cuál escribió | [`llm.py`](llm.py) |
| Evaluación | `evaluacion.py` es pura (no llama a ningún modelo) y sus tests corren en la suite como red contra regresiones. Generar de verdad contra el LLM se lanza a mano | [`evaluacion.py`](evaluacion.py), [`tests/test_evaluacion.py`](tests/test_evaluacion.py) |
| Modos de fallo conocidos | Descripción de oferta demasiado corta (CV genérico, avisado en `descripcion_oferta`); inflación del alcance del rol, no detectada; respuesta escrita por un modelo de respaldo | [Lo que los guardrails NO detectan](#lo-que-los-guardrails-no-detectan) |
| Inyección de instrucciones | Riesgo conocido, mitigado solo en parte | [Riesgo conocido](#riesgo-conocido-inyección-de-instrucciones) |
| Claves fuera de los logs | La clave de Gemini va en cabecera, no en la URL, y los errores de los proveedores se registran por tipo y código HTTP, no con su mensaje; lo vigila un test | [`tests/test_claves_fuera_de_los_registros.py`](tests/test_claves_fuera_de_los_registros.py) |

---

## Decisiones de arquitectura

Documentadas como ADRs en [`docs/`](docs/):

- **[ADR-001](docs/ADR-001-migracion-fastapi.md)**. Migración incremental a FastAPI.
  Coexistencia en vez de big-bang: se extrae el núcleo (`generar_cv_core`) y las rutas
  Flask y FastAPI son wrappers finos sobre el mismo core. Errores como excepción tipada
  (`CVError`), contratos Pydantic, y Flask como red de seguridad hasta que FastAPI cubra
  el endpoint en verde.
- **[ADR-002](docs/ADR-002-modelo-del-cv.md)**. Qué modelo escribe el CV, con coste
  medido vía `count_tokens`, no estimado. Incluye un hallazgo que invirtió la decisión:
  un modelo más nuevo y con precio por token más bajo salía **igual de caro**, porque su
  tokenizador cuenta un 50% más de tokens para el mismo texto.
- **[ADR-003](docs/ADR-003-usuario-multicuenta.md)**. Un usuario con varias cuentas de
  correo. Por qué duplicar el registro es un parche que se degrada en silencio, y por qué
  la verificación final tiene que ser exacta (el filtro `contains` de Notion es de
  subcadena: `vero@gmail.com` casa con `notvero@gmail.com`).
- **[ADR-004](docs/ADR-004-backend-llm.md)**. LiteLLM se escribe y se deja apagado
  (`LLM_BACKEND`). Se midió: +146 MB de disco, +5,96 s de arranque y 207 MB de RAM frente
  a 9 MB.

> **La autenticación está en el ADR-003 del repo `buscartrabajo`**
> (`docs/adr/ADR-003-autenticacion.md`), que no es el ADR-003 de arriba.

### Deuda conocida

`server.py` tiene unas 1.340 líneas y sigue siendo un módulo demasiado grande. No está
sin mirar: el ADR-001 describe cómo se está deshaciendo, con `api.py` llevándose un
endpoint cada vez y Flask cubriendo hasta que el nuevo está en verde. Se documenta aquí
porque es lo primero que se ve al abrir el repo.

Otras dos deudas conocidas:

- **Datos personales en los logs.** Los registros de `/generar-cv` y `/generar-carta`
  incluyen el email de la usuaria, la empresa y el puesto (por ejemplo, en los avisos de
  guardrails).
- **Modelo por defecto del CV.** En `llm.py`, `CV_MODEL` sigue valiendo `claude-haiku-4-5`
  por defecto. Producción usa Sonnet porque el entorno lo fija; si esa variable se pierde,
  el CV pasa a Haiku sin ningún error. Un cambio aparte, con tests, moverá el valor por
  defecto.

## Rutas

| Ruta | Acceso | Para qué |
|---|---|---|
| `GET /` | Pública | Página de invitación (`templates/inicio.html`) |
| `GET /health` | Pública | Estado, modelos activos y rama/commit desplegados |
| `GET /yo` | Token de Google (`Authorization: Bearer`) | Quién es la usuaria |
| `POST /registro` | Clave de máquina | Alta de usuaria |
| `POST /generar-cv` | Clave de máquina | CV adaptado a una oferta |
| `POST /generar-carta` | Clave de máquina | Carta adaptada a una oferta |
| `GET /usuarios` | Clave de máquina | Listado de usuarias |
| `POST /crear-oferta` | Clave de máquina | Alta de una oferta |
| `POST /buscar-ofertas-reales` | Clave de máquina | Búsqueda y ranking de ofertas |

La clave de máquina viaja en la cabecera `X-Clave-Maquina` y vale lo que diga la variable
`CLAVE_MAQUINA`. Sin ella configurada, esas rutas no abren nunca (falla cerrado). El
inventario de rutas lo protege `tests/test_rutas_de_maquina.py`.

## Acceso por invitación

Dos puertas distintas, según quién llame:

| Quién | Cómo entra |
|---|---|
| Una persona (el panel) | Token de identidad de Google en `GET /yo` |
| Una máquina (n8n) | Cabecera `X-Clave-Maquina` |

**Cómo funciona `/yo`.** El panel manda el token de Google en `Authorization: Bearer`.
`autenticacion.py` lo valida: algoritmo RS256 (fijo, el token no elige el verificador),
firma contra las claves públicas de Google (JWKS en caché 3600 s; un `kid` desconocido
provoca una descarga nueva, como mucho cada 300 s), emisor en `OIDC_EMISORES`, audiencia
igual a `OIDC_AUDIENCIA`, caducidad con 60 s de margen y `email_verified` verdadero.

| Código | Significado |
|---|---|
| 200 | `{sub, email, nombre}` |
| 401 | Falta el token o no es válido |
| 403 | Token válido, pero el email no está invitado |
| 503 | Falta configuración o no se alcanzan las claves públicas |

**Invitadas.** La lista es la variable `INVITADAS` (emails separados por comas, vacía =
nadie entra). Es provisional hasta que haya base de datos de usuarias.

**CORS.** Solo `/yo` y `/health` lo admiten, con coincidencia exacta de origen contra
`CORS_ORIGENES`. Vacío = ningún origen.

**El client id de Google es público a propósito.** Aparece en el panel y no protege nada
por sí mismo: lo que protege es la comprobación de la audiencia, que rechaza tokens
emitidos para otra aplicación.

**Arranque en local** (con las variables `OIDC_*` e `INVITADAS` de [`.env.example`](.env.example)
exportadas en la shell, no cargadas desde un fichero):

```bash
export CORS_ORIGENES=http://localhost:4200
.venv/bin/gunicorn server:app --bind 127.0.0.1:5000
```

La decisión de diseño completa está en el ADR-003 del repo `buscartrabajo`.

## Tests

```bash
pytest -q     # 381 tests
```

Los tests se escriben primero. Cada uno documenta en su docstring **el fallo real que lo motivó**,
con fecha, no un caso hipotético.

## Stack

`Python` · `Flask` y `FastAPI` · `Pydantic` · `Claude API` · `Notion API` ·
`Google Drive API` · `python-docx` · `pytest` · `Render`
