# cv-server

Servicio que genera **CVs y cartas adaptados a cada oferta** con LLMs, sin inventar
experiencia. Flask en producción, migrándose a FastAPI de forma incremental.

```
Notion (ofertas + perfil) ─┐
                           ├─► /generar-cv ─► LLM ─► guardrails ─► Google Drive
CV Master (Google Docs) ───┘
```

---

## El problema interesante

Adaptar un CV con un LLM es fácil. **Que no mienta, no.**

Un modelo al que le pides "adapta este CV a esta oferta" tiende a acercar el candidato
al puesto: añade una tecnología que la oferta pide, redondea una cifra, sube el alcance
de un rol. Cada una de esas frases es indefendible en una entrevista.

La respuesta de este servicio no es solo el CV: son **cuatro guardrails** que verifican
la salida contra la fuente de verdad.

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

| Guardrail | Qué detecta | Caso real que lo motivó |
|---|---|---|
| `cifras_no_respaldadas` | Números que no están en el CV Master | Cifras de usuarios redondeadas hacia arriba |
| `tecnologias_no_respaldadas` | Tecnologías que la oferta pide y el Master no respalda | *"experiencia en arquitecturas PHP/Symfony"* en un perfil sin PHP |
| `titular_fuera_de_contrato` | Titulares que inventan identidad o suben seniority | El titular copiando el título de la vacante |
| `descripcion_oferta` | **Entrada** insuficiente para adaptar nada | Ofertas de LinkedIn con 172 caracteres: el titular reformulado |

El cuarto es el que más cuesta ver: los otros tres miran la salida, y **un CV genérico
no inventa nada — simplemente no dice nada**. Sin mirar la entrada, `ok: true` oculta
que no había material.

### Lo que los guardrails NO detectan

La inflación del **alcance del rol**: `coordinated data contracts` → `own the data
contracts`, `Integrated APIs` → `Designed and integrated APIs`. No son tecnologías ni
cifras, así que la comparación contra el Master no las ve. Es semántico y sigue abierto.

---

## Decisiones de arquitectura

Documentadas como ADRs en [`docs/`](docs/):

- **[ADR-001](docs/ADR-001-migracion-fastapi.md)** — Migración incremental a FastAPI.
  Coexistencia en vez de big-bang: se extrae el núcleo (`generar_cv_core`) y las rutas
  Flask y FastAPI son wrappers finos sobre el mismo core. Errores como excepción tipada
  (`CVError`), contratos Pydantic, y Flask como red de seguridad hasta que FastAPI cubra
  el endpoint en verde.
- **[ADR-002](docs/ADR-002-modelo-del-cv.md)** — Qué modelo escribe el CV, con coste
  medido vía `count_tokens`, no estimado. Incluye un hallazgo que invirtió la decisión:
  un modelo más nuevo y con precio por token más bajo salía **igual de caro**, porque su
  tokenizador cuenta un 50% más de tokens para el mismo texto.
- **[ADR-003](docs/ADR-003-usuario-multicuenta.md)** — Un usuario con varias cuentas de
  correo. Por qué duplicar el registro es un parche que se degrada en silencio, y por qué
  la verificación final tiene que ser exacta (el filtro `contains` de Notion es de
  subcadena: `vero@gmail.com` casa con `notvero@gmail.com`).

## Tests

```bash
pytest -q     # 132 tests
```

Escritos primero. Cada uno documenta en su docstring **el fallo real que lo motivó**,
con fecha, no un caso hipotético.

## Stack

`Python` · `Flask` → `FastAPI` · `Pydantic` · `Claude API` · `Notion API` ·
`Google Drive API` · `python-docx` · `pytest` · `Render`

---

## Guía de uso del servicio

**Qué es:** Sistema automatizado que cada mañana te manda 5 ofertas personalizadas por email, y al aprobar una genera el CV adaptado + carta de presentación automáticamente.

**Estado:** Beta privada. Tienes que estar invitado para usarlo.

---

## 🚀 Cómo empezar (usuarios nuevos)

### Paso 1 — Abre el formulario de registro

👉 **[https://cv-server-ggd8.onrender.com/registro](https://cv-server-ggd8.onrender.com/registro)**

> ⚠️ La primera vez que lo abras puede tardar 30-60 segundos en cargar (el servidor se "despierta" al recibir la primera visita del día). Si parece colgado, espera un minuto antes de recargar.

### Paso 2 — Rellena el formulario

Campos obligatorios:
- **Nombre completo**
- **Email** (el que usarás para recibir las ofertas)
- **Perfil libre** — cuéntanos qué buscas en tus propias palabras

Campos opcionales pero muy recomendados para que las ofertas sean precisas:
- **Rol objetivo** (ej: "Senior Frontend Developer", "Tech Lead")
- **Ciudad** (para filtros de híbrido)
- **Modalidad preferida** (Remoto / Híbrido Madrid / Híbrido BCN / Presencial)
- **Stack técnico** (selecciona los que domines)
- **Salario mínimo anual** en euros
- **LinkedIn** (URL completa)
- **CV Master URL** — **importante**, ver sección siguiente

### Paso 3 — Sube tu CV Master a Drive

El sistema adapta TU CV para cada oferta, pero necesita una versión base para trabajar. Tienes 2 opciones:

**Opción A — Link a Drive (recomendado)**
1. Sube un `.txt` con tu CV completo a tu Google Drive
2. Haz el archivo público ("Cualquiera con el enlace puede ver")
3. Copia el link y pégalo en el campo "CV Master URL" del formulario

**Opción B — Dejarlo vacío**
Si dejas el campo vacío, contacta con quien te invitó para que suban tu CV a la carpeta compartida con el nombre `CV_Master_{tu_email_con_guiones}.txt`.

### Paso 4 — Envía el formulario

Al pulsar "🚀 Empezar" pasarán dos cosas:

- **Si es tu primer registro:** verás un mensaje "¡Listo! Mañana a las 9:00 recibirás tus primeras 5 ofertas". Y así será.

- **Si tu email ya existe:** verás dos botones:
  - **⚡ Buscar ahora** → recibirás las ofertas en unos minutos
  - **🌅 Mañana a las 9** → esperas al siguiente envío programado

---

## 📬 Cómo funciona el día a día

### Email de la mañana (9:00 AM)

Cada día a las 9 recibes un email con **5 ofertas reales**: empresa, puesto, salario, modalidad, enlace y contacto de RRHH. Cada oferta tiene 2 botones:

- **✅ Aprobar** — "quiero aplicar a esta"
- **❌ Descartar** — "no me encaja"

Ambos botones están **en el email mismo**, no hace falta abrir el sistema.

### Al aprobar una oferta

En 1-2 minutos recibes un segundo email con:
- **Carta de presentación** personalizada para esa empresa y puesto
- **Link al CV adaptado** (DOCX en tu Drive, con tus datos, con métricas ajustadas a lo que pide la oferta)
- **Botón "Mandar a empresa"** — cuando pulsas este, el sistema marca la oferta como "enviada a empresa" y te llega un tercer email de confirmación con los datos de contacto

### Lo que TÚ haces

Abres el link del CV, revisas que te guste, y mandas el email a la empresa con el CV + carta. El sistema NO envía automáticamente a la empresa, solo te prepara todo.

---

## 🎛️ Cambiar tus preferencias

Todo tu perfil vive en una base de datos de Notion. Si necesitas:

- Cambiar tu email, stack, salario, etc.
- Pausar los envíos diarios (sin borrarte)
- Borrar tu cuenta

Contacta con quien te invitó. En el futuro habrá un botón de "Editar mi perfil" en el propio formulario.

---

## 🐛 Qué hacer si algo falla

### "El formulario no carga"
Espera 60 segundos. El servidor está en plan gratuito de Render y se "duerme" tras 15 min sin actividad. La primera request del día lo despierta. Si tras 2 minutos sigue sin cargar, avisa.

### "No me llega el email de las ofertas"
1. Mira carpeta de spam / promociones
2. El remitente es `veronica@usecookyourwebai.es`
3. Si no aparece ni ahí, avisa a administración con tu email registrado

### "Aprobé una oferta pero no me llegó el CV"
El flujo de aprobar tarda ~1-2 minutos (Claude genera carta + CV adapta + Drive sube). Si pasa más de 5 min sin que llegue nada, avísanos y revisamos logs.

### "El CV generado tiene datos de otra persona"
Seguramente no tienes tu CV Master subido todavía y el sistema usó uno de fallback. Verifica que subiste tu CV y avísanos.

### Estados en el CRM

Las ofertas pasan por estos estados:
- **Pendiente** → oferta recién llegada, aún no has decidido
- **Aprobado** → pulsaste "Aprobar", carta y CV en camino
- **En proceso** → carta y CV generados, esperando que la mandes a la empresa
- **Enviado a empresa** → pulsaste "Mandar", aplicación enviada
- **Descartado** → pulsaste "Descartar"
- **Rechazado** → la empresa te respondió que no

---

## 🔒 Privacidad

- Tu perfil está en una base de datos privada (Notion). Solo administración tiene acceso.
- Los CVs adaptados se guardan en Drive, en una carpeta con tu email como nombre.
- La generación de CVs usa Claude (Anthropic) con tu CV Master + la descripción de la oferta.
- Ningún dato se vende ni se comparte con terceros.
- Para borrar tu cuenta completa, avisa y se elimina en 24h.

---

## ❓ FAQ

**¿Las ofertas son reales?**
De momento están generadas por IA basándose en perfiles reales de empresas. En la próxima fase se conectará a buscadores de empleo reales (LinkedIn Jobs, Getonboard, Remotive…).

**¿Cuánto cuesta?**
Nada por ahora — estás en beta privada cerrada. Si pasa a producto comercial te avisaremos antes.

**¿Cuántas ofertas recibo al día?**
5 cada mañana a las 9:00. Si es fin de semana o festivo, igual (no hay pausa).

**¿Puedo usarlo desde el móvil?**
Sí, el formulario y los emails están optimizados para móvil.

**¿Cómo invito a alguien más?**
De momento no. Manda el contacto a administración y lo añadimos manualmente.

---

## 📞 Contacto

Cualquier incidencia, duda o feedback:
- Email: **veronica@usecookyourwebai.es**
- Responde cualquier email del sistema y llegará a administración

---

> 🛠️ **¿Desarrollas o mantienes el servicio?** El detalle técnico (modelos LLM, fixes y trampas) está en [`CHANGELOG.md`](./CHANGELOG.md). Esta guía es solo para usuarios.

---

**Versión:** 2.0 Multi-User
**Última actualización:** 21 Abril 2026
