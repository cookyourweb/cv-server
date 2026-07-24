# Prompt de adaptación del CV y la carta

Fuente de verdad legible del prompt que adapta el CV del usuario a cada oferta.
El prompt REAL vive como f-string en `cv_server_railway.py`; este documento explica su
estructura y el PORQUÉ de cada regla, para que nadie las rompa al editar el código.

- **Prompt del CV**: `cv_server_railway.py`, endpoint `/generar-cv`, líneas ~1231-1305.
- **Prompt de la carta**: `/generar-carta`, líneas ~1423-1442.
- **Bloque de formato** (ES/EN): líneas ~1170-1229 (`bloque_formato`).
- **Modelos**: CV con Claude Haiku 4.5 (`CV_MODEL`), carta con Claude Sonnet 4.6
  (`CARTA_MODEL`). Groq queda de fallback dentro de `call_llm_calidad`.

> Regla de oro del proyecto: **el CV NUNCA inventa**. Todo sale del CV master del usuario.
> El prompt solo cambia ORDEN, ÉNFASIS y TITULAR, nunca el contenido real.

## Modelo mental: IDENTIDAD vs POSICIONAMIENTO

La distinción base del sistema (Verónica, 24-jul-2026). Confundirlas es el origen de casi
todos los fallos que hemos corregido.

| | **Identidad** | **Posicionamiento** |
|---|---|---|
| Responde a | Quién **ES** la candidata | Cómo se **PRESENTA** ante esta oferta |
| Naturaleza | **Cerrada** | **Variable** |
| Quién la fija | El `PERFIL BASE` del Master | El **arquetipo** de la oferta |
| Cambia entre ofertas | **Nunca** | Sí, en cada una |
| Ejemplos | Frontend Tech Lead, Full-Stack Developer, AI Engineer | GenAI Adoption, Context Engineering, Applied AI, AI Automation |
| Dónde va en el titular | Huecos de identidad | Huecos de **modificador** |

**Un posicionamiento no es una identidad nueva**: es la misma trayectoria presentada según
el problema que la empresa quiere resolver. Por eso el posicionamiento puede cambiar en
cada oferta y la identidad no cambia nunca.

**El posicionamiento también necesita respaldo del Master.** Un posicionamiento sin
evidencia es una identidad inventada con otro nombre. Si el Master no respalda el que pide
la oferta, se usa el que sí esté respaldado aunque encaje peor.

> **Decisión de diseño**: no existe una sección `Posicionamientos permitidos` en el
> contrato, y es deliberado. La identidad se declara porque es cerrada; el posicionamiento
> se **deriva**, y ya está acotado por tres puertas que existen: la lista cerrada de
> arquetipos, el *límite del arquetipo* (sin evidencia no se fuerza) y la regla de
> evidencia sobre tecnologías. Declararlo además obligaría a mantener una lista que el
> sistema no necesita.

## REGLA MAESTRA — proyección, no identidad nueva

> **La adaptación debe producir una PROYECCIÓN distinta de la MISMA trayectoria
> profesional, nunca una nueva identidad profesional.**

Formulada por Verónica el **24 de julio de 2026**. Es la regla de más alto nivel del
generador: si se cumple, muchas de las demás salen casi gratis. Implica automáticamente
no cambiar el título radicalmente, no subir el seniority, no inventar herramientas, no
mover skills a experiencia, no convertir un proyecto propio en una multinacional, y
cambiar solo el énfasis según el arquetipo de la oferta.

El criterio de comprobación: un recruiter que viera tres CV suyos debe reconocer a la
misma profesional adaptando el contenido, no a tres personas distintas. **Si un cambio la
hace parecer otra profesional, ese cambio está mal aunque cada frase por separado sea
cierta.**

---

## Prompt del CV — estructura en 3 pasos

El rol que se le da al modelo: *"senior tech recruiter que revisa 200+ CVs al día"*.
El CV entero se genera en el idioma de la oferta (títulos de sección y contenido).

### PASO 1 — Análisis interno (SOLO mental, no se escribe)
El modelo piensa, sin volcarlo al output: qué skills del master encajan, qué keywords de
la oferta deben aparecer, qué logros demuestran el fit. **No inventar** experiencia,
métricas ni logros. La respuesta DEBE empezar exactamente por la línea `HEADLINE: ...`;
prohibido escribir análisis o encabezados antes de esa línea.

*Por qué*: sin este paso el modelo tiende a volcar su razonamiento al documento final. El
fix del 1-jul (`1c3702a`) descarta explícitamente el bloque "ANÁLISIS INTERNO" del CV.

### PASO 2 — CV adaptado (output principal)
Reglas estrictas:
1. **No inventar nunca**: solo experiencia real del master. Nada de tecnologías no usadas,
   liderazgo no ejercido ni métricas exageradas. El CV debe ser 100% defendible en
   entrevista.
2. Adaptar **orden y énfasis** según la oferta, no el contenido.
3. **ATS**: integrar las keywords EXACTAS de la oferta cuando sean parte de su experiencia
   real.
4. Bullets con **fórmula XYZ** ("Logré X, medido por Y, haciendo Z") siempre que los datos
   lo permitan. Nada de "responsable de...".
5. **Densidad real**: no recortar el master. Puestos recientes 6-9 bullets, antiguos 3-4.
6. Redacción como **perfil de producto**: negocio a soluciones digitales, colaboración con
   diseño y producto, B2B/B2C, Design Systems.
7. Máximo 2 páginas.

### HEADLINE RULES (primera línea del output)

> **El titular es data-driven desde el 21 de julio de 2026.** El prompt NO contiene
> identidades escritas a mano. `test_headline_datadriven.py` falla si alguien las vuelve a
> meter. Si querés cambiar cómo se presenta Verónica, se edita **el CV Master**, no esto.

- **Fuente de verdad**: las identidades profesionales y los roles objetivo salen del bloque
  `PERFIL BASE` del CV Master, secciones "Identidades profesionales" y "Roles objetivo". Es
  la ÚNICA fuente. Una identidad que no esté ahí, no se usa.
- **Cómo se construye**: se seleccionan y REORDENAN las identidades del `PERFIL BASE` que
  mejor encajan con la oferta, y se añade especialización o stack solo si aparece en el
  `PERFIL BASE` o en la experiencia real del Master. **Cambia el énfasis y el orden, nunca
  las identidades.**
- **La oferta decide qué destacar, nunca qué inventar**: si pide un rol que no está en el
  `PERFIL BASE`, no se usa. La oferta solo elige cuáles de las identidades existentes se
  resaltan.
- **Coherencia identidad/experiencia**: cada identidad del titular tiene que poder
  justificarse leyendo la EXPERIENCIA del Master. Si una identidad del `PERFIL BASE` no
  tiene experiencia que la respalde, fuera del titular.
- **Fallback**: si el Master no trae bloque `PERFIL BASE`, las identidades se derivan de la
  experiencia real, nunca se inventan.
- **Nada grandilocuente** (*Principal Architect*, *Head of Engineering*) salvo que la oferta
  lo pida explícitamente y sea justificable.

#### El PERFIL BASE es un CONTRATO de datos (24-jul-2026)

La causa raíz de la deriva de títulos no era que el modelo inventase por capricho: era
que **no existía el bloque `PERFIL BASE` en ningún Master**. El prompt caía al fallback
("deriva las identidades de la experiencia real"), y derivar obliga a interpretar. De
interpretar salieron *AI Engineering Leader*, y de ahí a *GenAI Adoption Lead* o
*Solutions Architect* en la siguiente oferta.

El arreglo no es pedirle al modelo que se contenga. Es **no dejarle nada que deducir**.
El `PERFIL BASE` declara la identidad en secciones explícitas y el prompt las LEE:

| Sección | Qué declara |
|---|---|
| `Identidad profesional` | El titular base completo. Es el ancla |
| `Identidades permitidas` | Repertorio **cerrado**. Ninguna otra existe |
| `Orden del titular` | El orden exacto. Es un dato, no una decisión del modelo |
| `Variante permitida` | El único titular alternativo, con la condición que lo habilita |
| `Nunca permitido` | Restricciones que declara el propio Master. Innegociables |

Las únicas libertades del modelo: **sustituir uno o dos modificadores** de especialización
o stack por los que la oferta valora (siempre tomados del Master), u **omitir** uno que no
aporte nada. Las identidades y su orden no se tocan.

*Por qué*: si en cada oferta la candidata pasa de *Frontend Tech Lead* a *AI Engineering
Leader*, luego a *GenAI Adoption Lead* y después a *Solutions Architect*, parece que
intenta convertirse en lo que pide cada empresa. El CV tiene que sostener la misma
identidad profesional que su perfil público de LinkedIn.

> **Nota sobre reutilización**: el prompt no conoce ninguna identidad concreta, solo los
> NOMBRES de las secciones del contrato. Por eso el generador sirve para cualquier
> usuario: cada uno declara su propio `PERFIL BASE` en su Master.
> `test_proyeccion_arquetipos.py::test_titular_base_sigue_siendo_data_driven` falla si
> alguien vuelve a escribir una identidad concreta en el código.

#### El guardrail de seniority es un PRINCIPIO, no una lista

La regla anterior enumeraba *Principal, Staff, Head, Director, Architect, Distinguished,
Manager* y *"Lead" de personas*. El CV de N-iX salió con **"AI Engineering Leader"** y no
saltó nada: *Leader* no estaba en la lista.

Ahora la regla enuncia el principio (**no incrementar el nivel jerárquico, la autoridad
ni el alcance organizativo declarados en el `PERFIL BASE`**) y marca los ejemplos como
lista **abierta**. La prueba no es si la palabra aparece en una enumeración, sino si el
titular sugiere un rango mayor que el declarado.

*Lección general*: **las reglas deben expresar principios, no listas cerradas.** Mañana
aparecerá *Champion*, *Evangelist*, *Technical Authority* o *Principal Contributor* y
volvería a escaparse.
- **Años de experiencia**: base **10+**. No clavar 15+ ni un número alto en todas las
  ofertas. Reflejar más solo si la oferta valora seniority, siempre veraz.

**Consecuencia práctica.** El titular es coherente entre ofertas porque el `PERFIL BASE` es
el mismo. Lo que cambia entre un CV de Frontend y uno de IA es qué identidad va delante y
qué stack la acompaña, no quién es la candidata. Esa es la respuesta al riesgo de "un CV
distinto en cada candidatura": no puede pasar, porque el repertorio de identidades está
cerrado y vive fuera del prompt.

*Nota histórica*: hasta el 21 de julio de 2026 esta sección listaba identidades fijas
(*Frontend Tech Lead*, *Full-Stack Developer*, *UX Engineer*) y titulares por tipo de
oferta, con *AI Product Builder* y *AI Solutions Engineer* para las de IA. Eso obligaba a
tocar el prompt cada vez que Verónica se reposicionaba, y de hecho quedó desfasado cuando el
22 de julio los dos Masters pasaron a *AI Engineer*. Por eso el repertorio se movió al
Master.

### RESUMEN — estabilidad 70-80% (24-jul-2026)
El resumen **no se reescribe desde cero** en cada oferta. Aproximadamente tres cuartas
partes describen la misma trayectoria con las mismas ideas y casi las mismas palabras: de
dónde viene, cómo ha evolucionado, qué la define hoy. Solo la parte final, o los ejemplos
concretos que se eligen, se ajustan al arquetipo.

Así el titular, el resumen y el perfil público cuentan la misma historia, y esa coherencia
se sostiene también en la entrevista.

### PERFIL — anclaje a la oferta (obligatorio)
El resumen debe RESONAR con la oferta: identifica 2-3 requisitos o keywords concretas de la
descripción que la candidata YA haya trabajado de verdad, e intégralos en el perfil
redactados como experiencia real y demostrable ("con experiencia en X aplicada a Y").

*Línea roja*: PROHIBIDO meter un requisito de la oferta que NO esté respaldado por su
trayectoria real. Si la oferta lo pide pero ella no lo ha hecho, NO entra. Esto ancla el
perfil a la oferta usando SOLO lo cierto y defendible en entrevista; nunca es una puerta
para inventar.

#### Anclaje SUTIL: prohibido el eco (23-jul-2026)

El anclaje se hace con **su experiencia**, nunca copiando el texto del anuncio. Si una
frase del perfil se puede rastrear casi literal hasta la oferta, sobra.

Prohibido devolverle a la empresa sus propias palabras como si fueran rasgos de la
candidata. Ejemplo real que hubo que quitar a mano: la oferta decía "equipo reducido, con
mucha autonomía, mínima burocracia" y el perfil salió con "Acostumbrada a equipos
reducidos con alta autonomía y poca burocracia". No es mentira, pero **no dice nada de
ella**: ocupa una línea, no aporta evidencia y se nota que está copiado.

Cómo se hace bien:
- La keyword entra **dentro de un hecho suyo**, no como adjetivo suelto. La oferta pide
  Core Web Vitals → "optimización de rendimiento web (Core Web Vitals)" dentro de la
  lista de lo que ha hecho. No → "orientada a la optimización del rendimiento".
- Las condiciones de trabajo del anuncio (tamaño de equipo, burocracia, cultura,
  metodología, tráfico del producto) **NO se reflejan en el perfil**. Son del puesto, no
  de la candidata.
- Regla de comprobación: si al leer una frase se puede señalar el renglón del anuncio del
  que salió, se borra.

### NIVEL DEL PUESTO (aplica al CUERPO, no al titular)
- Si el puesto NO menciona lead/manager/responsable/principal/head/coordinador/director, es
  **desarrollo individual**: reducir el liderazgo al mínimo, reformular logros hacia el
  trabajo técnico (qué construyó, migró, arquitectura/componentes/APIs), no hacia gestión.
  El liderazgo aparece como contexto breve, nunca como venta principal.
- Solo si el puesto pide lead/manager/etc., se destaca ownership y coordinación técnica.

*Por qué*: fix del 1-jul (`0da513c`) — el titular mantiene la seniority real (Tech Lead de
facto del frontend) sin bajar al nivel de la oferta, pero el cuerpo se ajusta al nivel real
del puesto para seguir siendo defendible.

### ARQUETIPO de la oferta (ajusta el ÉNFASIS, nunca inventa)

> Reescrito el **24 de julio de 2026**. Hasta esa fecha esta sección listaba cinco
> categorías y una de ellas era **"IA"**, a secas. Ese bucket único fue exactamente el
> fallo del CV de N-iX. Además, la lista que aquí se documentaba llevaba tiempo sin
> existir en el código: el prompt real solo decía "prioriza las skills que la oferta
> valora", genérico. Ahora el bloque existe de verdad y `test_proyeccion_arquetipos.py`
> falla si alguien vuelve a colapsar los arquetipos de IA.

La oferta se clasifica en UN arquetipo leyendo el PUESTO y la DESCRIPCIÓN, nunca el
sector de la empresa. El arquetipo **no toca el titular ni las identidades**: decide qué
experiencia va primero, qué bullets se priorizan y qué keywords entran.

- **Frontend**: React, Vue, TypeScript, arquitectura frontend, design systems,
  rendimiento, accesibilidad, mentoría técnica.
- **Full Stack**: frontend como fortaleza principal, más Node, APIs, bases de datos.
- **Tech Lead**: ownership técnico, estándares, code review, coordinación con producto,
  diseño y backend. No afirmar dirección de personas salvo que el Master lo respalde.
- **UX Engineer**: Figma, Design Systems, accesibilidad, colaboración con diseño.
- **IA / AI Engineer**: CONSTRUYE sistemas con IA. LLM, RAG, agentes, APIs, Context
  Engineering, evaluación, guardrails, pipelines.
- **IA / GenAI Adoption**: consigue que OTROS desarrolladores trabajen mejor con IA.
  Formación, workshops, mentoring, pairing, experimentación, herramientas de desarrollo
  asistido, playbooks, productividad de equipos de ingeniería.
- **IA / AI Solutions Architect**: DISEÑA sistemas. Arquitectura, escalabilidad, cloud,
  integración, decisiones técnicas, observabilidad, gobernanza.
- **IA / AI Product Engineer**: construye PRODUCTO con IA. Métricas, usuarios,
  experimentos, UX, negocio, iteración.
- **IA / AI Automation Engineer**: AUTOMATIZA procesos. N8N, MCP, APIs, workflows.

**Regla de proyección**: el CV se adapta al **problema que resuelve la empresa que
contrata**, no al producto que construyó la candidata. La misma trayectoria se proyecta
hacia un arquetipo u otro sin inventar nada.

**Límite del arquetipo**: si el Master no respalda el arquetipo de la oferta, no se
fuerza. Un arquetipo sin evidencia es una invitación a inventar.

*Caso real, 24 de julio de 2026, N-iX (Gen AI Adoption Lead, Engineering Productivity).*
La oferta pedía impulsar la adopción de Copilot, Claude y Cursor en equipos de ingeniería
con talleres, pairing y medición de productividad. El CV salió vendiendo Context
Engineering, guardrails, JSON contracts y deterministic retrieval: un CV de *AI Engineer*
para una oferta de *enablement*. La carta, con el mismo Master, sí lo enfocó bien.

### HECHOS, NO EFECTOS
Se escribe la ACCIÓN concreta y verificable, nunca el efecto que se le atribuye, salvo
que el Master traiga el dato. El lector deduce el efecto solo, y le convence más.

- MAL: *"Improved engineering productivity"*, *"Led AI transformation"*, *"proven track
  record of measurable productivity gains"*, *"measuring adoption impact"*.
- BIEN: *"Delivered technical workshops on Generative AI for engineering teams"*.

Prohibido el vocabulario de resultado no medido cuando el Master no lo respalda: *proven
track record*, *measurable*, *impact*, *transformation*, *drove*, *boosted*,
*accelerated*.

*Por qué*: el CV de N-iX afirmó *"Proven track record translating emerging AI
capabilities into measurable team productivity gains"* y *"measuring adoption impact"*.
No hay una sola métrica de productividad en el Master. Un hecho concreto sin adjetivos
vende más que un efecto declarado sin prueba, y además es defendible en entrevista.

### No mover skills a experiencia
Una tecnología que el Master lista en HABILIDADES pero **no atribuye a un puesto
concreto** no puede aparecer como logro de ese puesto. En Habilidades es legítima.

*Por qué*: el CV de N-iX atribuyó *Jest, React Testing Library y CI/CD* al puesto de
Bitcode. El Master los tiene en *Architecture & Quality*, sin ligarlos a ese puesto. La
tecnología es real, la ATRIBUCIÓN es inventada, y el detector de tecnologías no lo ve
porque solo compara presencia, no a qué puesto se asigna.

### No dejarse fuera tecnologías reales que la oferta valora (regla de completitud)
La regla de evidencia impide inventar. Esta impide lo contrario: dejarse fuera algo real y
relevante. Si la oferta pide o menciona un área y el Master tiene una tecnología concreta de
esa área, esa tecnología DEBE aparecer en Habilidades y, si encaja, en un bullet.

Caso real, 23 de julio de 2026, Revolut (Applied AI Engineer, Python, IA): el CV omitió
**FastAPI** las dos veces que se generó, pese a estar en el Master y ser exactamente lo que
la oferta valora. No era azar: el prompt no tenía la regla, solo la de no inventar. Ahora sí.

### Proyectos propios, freelance y consultoría: no sobredimensionar la escala
Un proyecto personal se describe por la **complejidad técnica del trabajo**, nunca por el
tamaño aparente de la organización. La pregunta que responde el CV no es *"¿qué empresa
era?"* sino *"¿qué sabe hacer Verónica?"*.

Prohibido el lenguaje que sugiera equipos o departamentos que no existían: *"definí la
estrategia de IA de la compañía"*, *"lideré la arquitectura de la empresa"*, *"responsable
de la plataforma global"*, *"lideré un equipo de"*. Y nada de vocabulario de CEO
(estrategia, dirección, transformación digital) salvo que la oferta sea para eso.

En su lugar: qué construyó, qué problemas resolvió, qué tecnologías usó, qué arquitectura
diseñó, qué decisiones de ingeniería tomó.

**El resumen nunca gira alrededor del proyecto propio.** Describe la trayectoria completa;
la experiencia actual es el ejemplo de la evolución, no el eje de la identidad. La narrativa
correcta es *"10+ años de producto digital, especialización frontend, evolución a
full-stack, especialización actual en AI Engineering"*, nunca *"fundadora de X que hace IA"*.

**El peso de una experiencia no depende del tamaño de la empresa**, sino de la relevancia de
las competencias para esta oferta. CookYourWeb puede ir primero por ser lo más reciente y
especializado, pero presentado como trabajo de ingeniería.

*Por qué*: 24-jul-2026. Los CV tendían a vender CookYourWeb, que es un proyecto propio, con
una escala de organización que no corresponde. No es falso (el trabajo es real), pero un
recruiter senior lo percibe y resta credibilidad.

### El titular no hace eco del anuncio
La identidad del titular sale del `PERFIL BASE` tal cual está escrita, sin calificativos del
título de la oferta. Si la oferta se titula *Applied AI Engineer* y el `PERFIL BASE` dice
*AI Engineer*, el titular usa *AI Engineer*. Caso real: Revolut, el titular salió *Applied
AI Engineer* copiando el "Applied" del anuncio.

### PASO 3 — Revisión anti-IA
Elimina todo rastro de texto de IA antes de entregar: cero guiones largos y dobles guiones,
cero frases tipo "responsable de..."/"orientada a...", cero adjetivos vacíos ("dinámico",
"proactivo", "apasionado"), cero "passionate about"/"excited to", cero pasivas innecesarias.
Tono profesional pero natural.

> Esto es la primera red. La SEGUNDA red es determinista: `sanear_tipografia()` limpia
> guiones largos y flechas en el render, por si el modelo desobedece. Ver `CHANGELOG.md`.

---

## Guardrails: lo que se comprueba en la SALIDA

El prompt es una instrucción, no una garantía. Estas dos reglas ya estaban escritas y el
modelo las incumplió igual, así que además se verifica el texto generado y se devuelve el
resultado en la respuesta de `/generar-cv`.

Ninguno de los dos aborta la generación. Una alerta puede ser legítima, y abortar dejaría a
la candidata sin CV. Se avisa para que ella lo revise antes de enviarlo.

| Campo de la respuesta | Qué contiene | Función |
|---|---|---|
| `cifras_no_respaldadas` | Cifras y magnitudes del CV que no están en el Master | `detectar_cifras_no_respaldadas` |
| `tecnologias_no_respaldadas` | Tecnologías del CV que no están en el Master | `detectar_tecnologias_no_respaldadas` |

El catálogo de tecnologías reconoce variantes de escritura como equivalentes: `RTL`,
`React Testing Library` y `Testing Library` son la misma, igual que `Vue` y `Vue.js`. Si el
Master usa una variante y el CV otra, no salta falsa alarma.

**Regla de evidencia (tecnologías):** una tecnología entra en el CV solo si el Master la
respalda. Da igual que la oferta la pida.

Caso real, 23 de julio de 2026, oferta de Tenth Revolution: la oferta pedía "entornos
PHP/Symfony o templating server-side (Twig, Blade)". Verónica no tiene esa experiencia. El
CV generado salió con *"experiencia en templating server-side (contexto de integración con
arquitecturas PHP/Symfony)"*. No es exactamente mentira, y en la bandeja de un recruiter se
lee como experiencia. Hubo que quitarlo a mano. Ahora sale marcado en la respuesta.

El detector trabaja con un catálogo de tecnologías y con sus variantes de escritura, para
que "Vue" y "Vue.js" cuenten como lo mismo y no salte una falsa alarma. Cuando el Master
incorpore una tecnología nueva, no hay que tocar nada: el detector compara contra el Master,
no contra una lista de permitidas.

**Un alias que falta es un agujero en el guardrail.** Caso real, 24 de julio de 2026,
N-iX: el CV coló *"integrating Copilot-class AI systems"* sin respaldo del Master y el
detector no dijo nada. El catálogo daba de alta **"GitHub Copilot"** y el patrón usa
fronteras de palabra, así que **"Copilot" a secas no matcheaba**. No fue un fallo del
modelo ni de la regla: fue un alias que no estaba. Arreglado con
`_reg_tec("GitHub Copilot", "Copilot")` y cubierto por
`test_tecnologias_inventadas.py::test_regresion_la_frase_exacta_del_cv_de_n_ix`.

Al añadir una herramienta al catálogo, **da de alta también el nombre corto por el que la
gente la escribe de verdad**. El patrón consume primero los nombres largos, así que
registrar el alias corto no produce dobles alertas.

---

## Prompt de la carta de presentación

Rol: *experto en cartas de presentación*. Máximo **250 palabras**, en el idioma de la oferta.

- Solo experiencia real del master y solo la relevante; conectar con lo que pide la oferta.
  No inventar, no exagerar, nada difícil de defender.
- **Nivel**: mismo criterio que el CV. Puesto sin lead/manager es desarrollo individual, no
  usar la coordinación de equipos como argumento principal; enfocar el encaje técnico.
- Tono profesional, directo y humano. Cero frases de IA ("apasionada", "proactiva",
  "soluciones innovadoras", "emocionada de la oportunidad").
- Mencionar logros o tecnologías concretas del CV que encajen.
- Saludo: a la persona de contacto si se conoce ("A la atención de {contacto}," / "Dear
  {contacto},"), usando el nombre EXACTO, sin inventarlo. Si no, genérico ("Estimados/as," /
  "Dear Hiring Team,"). Despedida formal + nombre.

---

## Al editar el prompt: no rompas esto

- La primera línea del CV DEBE ser `HEADLINE: ...` — el render la usa como titular de la
  cabecera. Si el modelo escribe algo antes, se rompe la cabecera.
- Nombre/email/teléfono NO van en el prompt: se añaden programáticamente en el DOCX.
- Nada de markdown en el output (`**texto**`, `##`, ```` ``` ````).
- No metas un saneado tipográfico global antes de parsear el DOCX: la detección de la línea
  de empresa usa el guion largo como marcador. Ver `CHANGELOG.md`.

---

**Última actualización:** 24 julio 2026
**Ver también:** `../CHANGELOG.md` (cambios técnicos), `../README.md` (guía de usuario),
`../test_proyeccion_arquetipos.py` (invariantes del prompt: regla maestra, titular base,
arquetipos, hechos-no-efectos).
