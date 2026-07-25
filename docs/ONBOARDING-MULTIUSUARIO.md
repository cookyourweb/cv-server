# Onboarding multiusuario: de un CV cualquiera a un PERFIL BASE

Spec de la entrevista de alta. **Todavía no implementado.** Escrito el 24 de julio de 2026,
ampliado el 25 con la arquitectura de tres capas y el flujo de 9 pasos.

---

## LA LECCIÓN RAÍZ: el problema nunca fue el CV

Estábamos intentando adaptar un documento que **mezclaba tres cosas distintas**:

1. **Quién eres** (identidad)
2. **Qué has hecho** (hechos)
3. **Cómo venderlo para una oferta concreta** (adaptación)

Un documento que mezcla las tres capas obliga al modelo a separarlas por su cuenta cada vez
que genera, y ahí es donde inventa. La solución no fue una regla mejor: fue **separar las
capas en el dato**.

| Capa | Qué es | Cambia |
|---|---|---|
| **PERFIL BASE** | Identidad permanente | Casi nunca |
| **Master CV** | Todos los hechos verificables | Cuando ocurren hechos nuevos |
| **CV adaptado** | Selección y orden de esos hechos según la oferta | En cada oferta |

Con las capas separadas, generar un CV deja de ser "reinterpretar quién eres" y pasa a ser
**seleccionar y ordenar hechos que ya existen**. Eso es lo que elimina la invención.

> **Si tuviéramos que crear el sistema desde cero para otra persona, empezaríamos por esta
> arquitectura.** No por el CV. El CV es la salida, no el punto de partida.

---

## EL ORDEN DE LA ENTREVISTA (construir el Master ANTES de generar CVs)

El error de partida sería pedir "el CV y la oferta". El orden correcto es al revés: **primero
se construye el Master (la fuente de verdad), después se generan infinitos CV adaptados.** La
oferta no entra hasta que el Master está terminado.

Nueve pasos, en este orden estricto:

1. **Identidad profesional** — antes que nada, quién eres. *¿A qué te dedicas realmente? ¿Qué
   problemas sabes resolver? ¿Qué puestos puedes defender en una entrevista? ¿Qué puestos NO
   quieres que aparezcan nunca?* La identidad es lo único que no cambia entre ofertas.
2. **Objetivo profesional** — *¿Qué tipos de oferta quieres poder atacar con este Master?*
   (Backend, Frontend Tech Lead, AI Engineer, Engineering Manager, Solutions Architect,
   GenAI Adoption...). No para ponerlo en el CV: para saber qué variaciones debe soportar el
   sistema. → alimenta `Tipos de oferta compatibles`.
3. **CV actual** — ahora sí. No para mejorarlo, para **extraer hechos**: empresas, proyectos,
   tecnologías, responsabilidades, logros, formación.
4. **Lo que falta** — donde casi todos los CV fallan. *¿Qué haces de verdad que no aparece en
   el CV?* Mentorizar, entrevistar, documentar, experimentar, automatizar, formar equipos,
   definir procesos, comparar herramientas, hacer arquitectura. Ocurre, pero nadie lo escribe.
5. **Límites** — *¿Qué NO quieres que el sistema invente nunca?* No inventar liderazgo,
   métricas, equipos, tecnologías, cloud, IA. **Aquí nacen los guardrails de ese usuario.**
6. **Identidad estructurada** — se construye el `PERFIL BASE`: Identidad profesional,
   Identidades permitidas, Orden del titular, Variante permitida, Nunca permitido, Tipos de
   oferta compatibles, Áreas de contribución, Posicionamiento, Especialización, Tecnologías
   principales. Este bloque apenas cambiará nunca.
7. **Experiencia** — los bullets NO se escriben pensando en una oferta, se escriben pensando
   *¿qué ocurrió de verdad?* Cada experiencia responde: qué construiste, diseñaste, lideraste,
   automatizaste, aprendiste; qué tecnologías, qué decisiones, qué enseñaste, qué documentaste.
   Todavía sin pensar en ATS.
8. **Inventario de palabras clave** — solo cuando el Master está terminado. Un inventario
   grande (AI Engineering, LLMs, OpenAI, Claude, React, Node, Developer Productivity, AI
   Adoption, Architecture, Technical Leadership...). No para meterlas todas: para que el
   adaptador pueda **elegir** según la oferta.
9. **Reglas del sistema** — al final del todo: no inventar experiencia, no cambiar seniority,
   no crear identidades nuevas, no alterar el orden del titular, adaptar el énfasis y no los
   hechos, priorizar la experiencia relevante, reutilizar solo información existente en el
   Master.

**Por qué este orden importa:** ATS y adaptación van al final a propósito. Si se piensa en la
oferta antes de tener los hechos, el usuario (o el modelo) empieza a escribir para agradar en
vez de para describir, y ahí vuelve la invención. Primero la verdad, luego la venta.

---

El resto de este documento detalla CÓMO ejecutar esos pasos: qué se lee en vez de preguntar,
las preguntas ancladas en fallos reales, y dónde vive el contrato.

- **Qué produce la entrevista**: el bloque `PERFIL BASE` (paso 6) + el Master de hechos
  (paso 7). Ver `PROMPT-ADAPTACION-CV.md`, sección *El PERFIL BASE es un CONTRATO de datos*.
- **Por qué hace falta el PERFIL BASE**: sin ese bloque el prompt cae al fallback ("deriva las
  identidades de la experiencia") y **derivar obliga a interpretar**. De interpretar salió
  *AI Engineering Leader* en el CV de N-iX. La entrevista existe para que el modelo no tenga
  que deducir nada.

---

## Principio: no preguntes lo que puedes leer

Un formulario largo mata el alta. Y la mayoría de las respuestas ya están en los dos
documentos que el usuario acaba de entregar. Tres modos, y solo el tercero cuesta tiempo:

| Modo | Qué es | Coste para el usuario |
|---|---|---|
| **EXTRAER** | Se lee del CV o de LinkedIn. No se pregunta | Cero |
| **CONFIRMAR** | Se le propone lo extraído y dice sí o corrige | Un clic |
| **PREGUNTAR** | No está en ningún documento. Hay que preguntarlo | Real |

**Toda pregunta de este documento justifica su existencia con un fallo real** que se cometió
generando los CV de Verónica. Una pregunta sin fallo detrás no entra.

---

## Se engancha al alta que YA existe

No es un formulario nuevo. El registro actual (`/registro`, formulario multistep servido en
`/`) ya crea el usuario en Notion con estos campos:

| Campo en Notion | Qué es | Para la entrevista |
|---|---|---|
| `Email` · `Name` · `Ciudad` | Identificación | — |
| `LinkedIn` | URL del perfil | **Fuente de EXTRAER** |
| `CV Master URL` · `cv_master_file_id` | El Master en Drive | **Fuente de EXTRAER** |
| `Perfil` | Texto libre | Solapa con `Resumen profesional` |
| `Rol objetivo` | Texto libre | Solapa con `Roles objetivo` |
| `Stack` | Multi-select | Solapa con `Tecnologías principales` |
| `Salario min` · `Modalidad` · `Activo` | Filtros de búsqueda | — |

**Las dos fuentes que necesita la entrevista ya se piden.** Y tres campos ya cubren parte del
contrato: no se vuelven a preguntar, se **confirman**.

Los pasos nuevos son solo los que producen lo que hoy no existe: identidades, orden,
variante, posicionamiento y las preguntas de evidencia y frontera.

---

## DÓNDE VIVE EL CONTRATO: en Notion, no en el Google Doc

Con Verónica el `PERFIL BASE` se pegó **a mano** al principio de su CV Master. Para una
usuaria eso vale. Para multiusuario **no**, y hay evidencia del mismo día.

*El 24-jul-2026, pegando ese bloque en dos documentos, el contenido español acabó dentro del
Master inglés **dos veces seguidas**. Lo detectó una lectura desde Drive, no la usuaria. Si
falla quien diseñó el bloque, falla cualquiera.*

**Propuesta (no implementada)**: el contrato se guarda como campos del usuario en Notion, y
el servidor **construye el bloque `PERFIL BASE` y lo antepone al texto del Master** antes de
mandarlo al modelo. El usuario no pega nada. Su Master sigue siendo solo su CV.

Ventajas, más allá de quitar el copiar y pegar:

- **Editable desde la aplicación**: cambiar el titular es actualizar un campo, no reeditar un
  documento de Drive.
- **Validable**: se puede comprobar que `Identidades permitidas` tiene entre 1 y 4 entradas, o
  que la condición de la variante contiene nombres propios y no una categoría. Sobre texto
  pegado en un Doc no se puede validar nada.
- **Arregla de paso la incoherencia del detector**: hoy
  `detectar_tecnologias_no_respaldadas` compara contra el texto completo del Master,
  `PERFIL BASE` incluido, así que una tecnología escrita ahí queda dada por respaldada y
  ciega el guardrail. Si el bloque se inyecta aparte, el detector puede seguir comparando
  contra el Master **sin** el bloque, que es lo que el prompt dice que debe pasar.

El prompt **no cambia**: sigue leyendo las mismas secciones por su nombre. Solo cambia quién
escribe el bloque y dónde se guarda.

---

## FASE 0 — EXTRAER (sin preguntar nada)

Del CV y del perfil de LinkedIn se saca automáticamente:

- Titular actual de LinkedIn → candidato a `Identidad profesional`
- Puestos, empresas y fechas
- Tecnologías mencionadas, y **en qué puesto aparece cada una**
- Formación e idiomas
- Años totales de trayectoria

Esto no se pregunta nunca. Ya está escrito.

---

## FASE 1 — CONFIRMAR la identidad (un clic por pregunta)

Se propone lo extraído y el usuario valida. Construye el contrato.

**1.1 · Tu titular** — *"Tu LinkedIn dice X. ¿Ese es el titular con el que quieres que se
generen todos tus CV?"*
→ `Identidad profesional`

**1.2 · Tus identidades** — *"He detectado estas: A, B, C. ¿Sobran o falta alguna?"*
Máximo 4. Es un repertorio **cerrado**: ninguna otra podrá usarse nunca.
→ `Identidades permitidas`
*Previene*: identidades inventadas por oferta (*AI Engineering Leader*, *GenAI Adoption Lead*).

**1.3 · El orden** — *"¿En qué orden van? La primera es con la que te van a identificar."*
→ `Orden del titular`
*Previene*: que el CV se reordene según la oferta y parezca otra persona en cada envío.

**1.4 · La excepción** — *"¿Hay empresas concretas para las que invertirías ese orden?
Nómbralas. Si dudas, deja esto vacío."*
→ `Variante permitida`

> **Esta es la pregunta más delicada de todo el alta.** El 24-jul-2026 la condición de
> Verónica decía *"empresas cuyo producto principal sea la IA (OpenAI, Anthropic,
> Cohere...)"*, y el modelo aplicó la variante **a N-iX y a Revolut**, que no son ninguna de
> esas. Leyó el paréntesis como ejemplos, no como lista cerrada. Es el mismo patrón que
> dejó pasar *"Leader"* en el guardrail de seniority.
>
> **Regla que se deriva**: la condición debe ser una **lista de nombres propios**, nunca una
> categoría. Si el usuario responde con una categoría ("empresas de IA", "startups"), hay
> que repreguntar pidiendo nombres. Y si no sabe cuáles, se deja vacío: **sin variante
> declarada, no hay excepción posible.** Vacío es más seguro que ambiguo.

**1.5 · Seniority** — *"¿Cuántos años declaras?"*
*Previene*: inflar el número según lo que valore la oferta.

**1.6 · Lo que no eres** — *"¿Con qué rol te confunden y no quieres que te confundan?"*
→ bloque `POSICIONAMIENTO`
Verónica: *"No soy Data Scientist. No soy investigadora de IA."* Es una frontera, y el prompt
la respeta aunque la oferta pida lo contrario.

---

## FASE 2 — La EVIDENCIA (lo que impide inventar)

Aquí no vale confirmar: hay que preguntar. Es lo que separa un CV defendible de uno bonito.

**2.1 · Qué hiciste tú** — por cada puesto relevante: *"¿Qué hiciste con tus manos, no tu
equipo?"*
*Previene*: atribuirse el trabajo del equipo.

**2.2 · Tecnologías por puesto** — *"De estas que aparecen en tu CV, ¿cuáles usaste **en este
puesto concreto**?"*
*Previene*: el fallo de GraphQL. En el CV de Revolut el modelo escribió *"implemented
GraphQL and webhook patterns"* en el puesto de Bitcode, cuando el Master solo las tiene en
habilidades sin ligarlas a ningún puesto. La tecnología era real; **la atribución, inventada**.

**2.3 · Cifras** — *"¿Qué cifras puedes defender con un dato real que tengas a mano?"*
Si no hay dato, no hay cifra. Un CV sin cifras es defendible; con una cifra inventada, no.

**2.4 · Lo que conoces pero no usaste** — *"¿Qué tecnologías has tocado pero no usarías como
argumento en una entrevista?"*
Van a una **lista negra explícita** del usuario. Complementa al detector, que solo sabe
comparar contra el Master.

---

## FASE 3 — La FRONTERA (lo único que ningún guardrail cubre)

Las dos preguntas más importantes del alta, y las que nadie hace.

**3.1 · Aspiración** — *"¿Qué quieres hacer que todavía no has hecho?"*
→ va a `Roles objetivo`, **jamás a Experiencia**. El prompt trata el `PERFIL BASE` como guía
de identidad y **nunca como evidencia**, así que declararlo ahí no puede inflar el cuerpo del
CV. La aspiración queda dicha sin afirmar nada.

**3.2 · La prueba de la entrevista** — *"¿Hay algo en tu CV actual que no podrías defender en
veinte minutos de entrevista?"*

> **Por qué existe esta pregunta.** Todos los guardrails del sistema comparan **el CV
> generado contra el Master**. Si una afirmación sin respaldo vive **dentro del Master**, es
> indetectable: el Master es el axioma.
>
> El 24-jul-2026 los dos Masters de Verónica afirmaban *"formación técnica para empresas"*.
> Ella no había impartido todavía ningún curso a empresas. Ningún detector podía verlo, y de
> ahí había salido ya una carta a N-iX afirmándolo. Lo paró ella, no el sistema.
>
> **La regla de evidencia protege la frontera oferta → CV. No protege la frontera
> realidad → Master. Esa solo la sostiene la persona.** Con un usuario desconocido, esta
> pregunta es lo único que hay. Conviene repetirla cada vez que edite su Master.

---

## FASE 4 — Arquetipos

**4.1** — *"¿A qué tipo de puesto apuntas?"* Se le enseñan los arquetipos que el prompt sabe
distinguir (ver `PROMPT-ADAPTACION-CV.md`) y elige uno o varios.

**Limitación conocida**: los arquetipos están **escritos en el prompt** y son del sector
tecnológico. Un perfil de diseño, ventas o administración no encaja en ninguno. Para abrir el
sistema fuera de tecnología habrá que sacarlos a datos, igual que se hizo con las identidades.
No se toca hasta que haya un usuario real que lo necesite.

---

## Salida de la entrevista

El bloque que se pega al principio del CV Master del usuario:

```
# PERFIL BASE
## Identidad profesional      (1.1)
## Identidades permitidas     (1.2)
## Orden del titular          (1.3)
## Variante permitida         (1.4)
## Nunca permitido            (fijo, igual para todos)
## Roles objetivo             (3.1 + 4.1)
## Resumen profesional        (extraído, confirmado)
## Especialización actual     (extraído, confirmado)
## Tecnologías principales    (2.2)

POSICIONAMIENTO               (1.6)
EVOLUCIÓN PROFESIONAL         (extraído de fechas y puestos)
```

---

## Errores a evitar en el alta

- **No preguntar lo que está en el CV.** Cada pregunta redundante es un usuario que abandona.
- **No aceptar categorías donde hace falta una lista de nombres** (pregunta 1.4).
- **No dejar que la aspiración entre en Experiencia.** Va a `Roles objetivo` y punto.
- **No pegar tecnologías en el `PERFIL BASE` que no estén en la experiencia.** El detector
  compara contra el texto completo del Master, `PERFIL BASE` incluido: escribir ahí una
  tecnología la da por respaldada y **ciega el guardrail**. Incoherencia conocida entre el
  prompt (que dice que el `PERFIL BASE` no es evidencia) y el detector (que no distingue
  secciones). Si alguna vez muerde, se arregla excluyendo el bloque del texto que ve el
  detector.

---

**Ver también**: `PROMPT-ADAPTACION-CV.md` (las reglas que esta entrevista alimenta),
`../test_proyeccion_arquetipos.py` (los invariantes del prompt).
