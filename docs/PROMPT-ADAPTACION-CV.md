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

### POSICIONAMIENTO por tipo de oferta (ajusta el ÉNFASIS, nunca inventa)
- **Frontend**: React, Vue, TypeScript, JS, HTML5, CSS3. Reduce el liderazgo.
- **Full Stack**: React, TypeScript, Node, APIs, Firebase, MongoDB. Frontend como fortaleza
  principal.
- **Tech Lead**: mentoría técnica, coordinación con negocio/UX/producto/backend, ownership
  del área frontend. No afirmar dirección de personas salvo que sea cierto.
- **UX Engineer**: Figma, Design Systems, UX, accesibilidad.
- **IA**: IA aplicada, automatización, LLMs, OpenAI/Claude/n8n, agentes, prototipado.
  Python SÍ como HERRAMIENTA dentro de IA aplicada, nunca como *Senior Python Engineer*.

### No dejarse fuera tecnologías reales que la oferta valora (regla de completitud)
La regla de evidencia impide inventar. Esta impide lo contrario: dejarse fuera algo real y
relevante. Si la oferta pide o menciona un área y el Master tiene una tecnología concreta de
esa área, esa tecnología DEBE aparecer en Habilidades y, si encaja, en un bullet.

Caso real, 23 de julio de 2026, Revolut (Applied AI Engineer, Python, IA): el CV omitió
**FastAPI** las dos veces que se generó, pese a estar en el Master y ser exactamente lo que
la oferta valora. No era azar: el prompt no tenía la regla, solo la de no inventar. Ahora sí.

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

**Última actualización:** 20 julio 2026
**Ver también:** `../CHANGELOG.md` (cambios técnicos), `../README.md` (guía de usuario).
