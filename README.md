# cv-server

Servicio que genera **CVs y cartas adaptados a cada oferta** con LLMs, sin inventar
experiencia. Flask en producción, migrándose a FastAPI de forma incremental.

```
Notion (ofertas + perfil) ─┐
                           ├─► /generar-cv ─► LLM ─► guardrails ─► Google Drive
CV Master (Google Docs) ───┘
```

> ¿Vienes a **usar** el servicio y no a leer el código? La guía está en
> [`docs/GUIA-DE-USO.md`](docs/GUIA-DE-USO.md).

---

## El problema interesante

Adaptar un CV con un LLM es fácil. **Que no mienta, no.**

Un modelo al que le pides "adapta este CV a esta oferta" tiende a acercar el candidato
al puesto: añade una tecnología que la oferta pide, redondea una cifra, sube el alcance
de un rol. Cada una de esas frases es indefendible en una entrevista.

La respuesta de este servicio no es solo el CV: son **seis guardrails** que verifican
la salida contra la fuente de verdad. Desde el 28-ago-2026 se aplican también a la
**carta**, que hasta entonces salía sin ninguno.

```json
{
  "ok": true,
  "link": "https://drive.google.com/...",
  "modelo_usado": "claude-sonnet-4-6",
  "cifras_no_respaldadas": [],
  "tecnologias_no_respaldadas": [],
  "skills_no_respaldadas": [],
  "titular_fuera_de_contrato": [],
  "experiencia_mal_atribuida": [],
  "descripcion_oferta": { "suficiente": true, "chars": 1694, "aviso": "" }
}
```

| Guardrail | Qué detecta | Caso real que lo motivó |
|---|---|---|
| `cifras_no_respaldadas` | Números que no están en el CV Master | Cifras de usuarios redondeadas hacia arriba |
| `tecnologias_no_respaldadas` | Tecnologías del catálogo que la oferta pide y el Master no respalda | *"experiencia en arquitecturas PHP/Symfony"* en un perfil sin PHP |
| `skills_no_respaldadas` | Cada skill declarada, verificada una a una y sin catálogo | *"React 19 · Tailwind (v4) · Radix UI · Mantine"*: el stack de la oferta, copiado entero |
| `titular_fuera_de_contrato` | Titulares que inventan identidad o suben seniority | El titular copiando el título de la vacante |
| `experiencia_mal_atribuida` | Años de experiencia pegados a la tecnología equivocada | El Master dice *"Vue.js, 8 años"* y la carta escribió *"más de ocho años con React y TypeScript"* |
| `descripcion_oferta` | **Entrada** insuficiente para adaptar nada | Ofertas de LinkedIn con 172 caracteres: el titular reformulado |

El de la descripción es el que más cuesta ver: los otros miran la salida, y **un CV
genérico no inventa nada, simplemente no dice nada**. Sin mirar la entrada, `ok: true`
oculta que no había material.

`experiencia_mal_atribuida` cubre un hueco distinto de todos los demás: los otros
comprueban si algo **existe** en el Master, este comprueba **a quién pertenece**. React
existe, el 8 existe, y la frase que los junta es falsa.

### La carta también pasa los guardrails

Hasta el 18-ago-2026 los detectores se aplicaban solo a `contenido_cv`. La carta es lo
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

`skills_no_respaldadas` invierte el sentido. La sección de skills de un CV es una lista
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

### Deuda conocida

`cv_server_railway.py` tiene unas 2.500 líneas y es un módulo demasiado grande. No está
sin mirar: el ADR-001 describe cómo se está deshaciendo, con `api.py` llevándose un
endpoint cada vez y Flask cubriendo hasta que el nuevo está en verde. Se documenta aquí
porque es lo primero que se ve al abrir el repo.

## Tests

```bash
pytest -q     # 146 tests
```

Escritos primero. Cada uno documenta en su docstring **el fallo real que lo motivó**,
con fecha, no un caso hipotético.

## Stack

`Python` · `Flask` → `FastAPI` · `Pydantic` · `Claude API` · `Notion API` ·
`Google Drive API` · `python-docx` · `pytest` · `Render`
