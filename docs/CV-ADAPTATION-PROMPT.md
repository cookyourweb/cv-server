# CV and cover letter adaptation prompt

Readable source of truth for the prompt that adapts the user's CV to each job offer.
The REAL prompt lives as an f-string in `server.py`; this document explains its
structure and the REASON behind each rule, so that nobody breaks them when editing the code.

> **Language note.** The prompt text in `server.py` is written in Spanish, and so are
> the section names that the prompt reads from the CV Master (`PERFIL BASE`,
> `Identidades permitidas`, and so on) and some of its own markers (`PASO 1`,
> `ANÁLISIS INTERNO`, `NIVEL DEL PUESTO`, `HECHOS, NO EFECTOS`). They are literal
> identifiers: this document keeps them in code format and explains them in English.
> Do not translate them in the code or in a Master without changing both sides.

- **CV prompt**: constant `PROMPT_CV` in `server.py`, used by `generar_cv_core`.
  Inside it, the `HEADLINE RULES` section sets the headline.
- **Cover letter prompt**: constant `PROMPT_CARTA` in `server.py`, used by `generar_carta`.
- **Format block** (ES/EN): `PROMPT_ESTRUCTURA_ES` and `PROMPT_ESTRUCTURA_EN`, which
  `generar_cv_core` picks according to the language of the offer and passes to `PROMPT_CV` as
  `bloque_formato`.
- **Models**: CV and cover letter use `claude-sonnet-4-6` in production. The environment
  sets them (`CV_MODEL`, `CARTA_MODEL`), not the code: the default value of `CV_MODEL` in
  `llm.py` is still Haiku 4.5 (see ADR-002). If Claude fails, the call falls back to Groq
  (`openai/gpt-oss-120b`), then Gemini, then Claude Haiku (`call_llm_calidad` and
  `call_llm` in `llm.py`). Each response reports in `modelo_usado` the model that actually
  wrote it. `/health` shows the active models.

> Golden rule of the project: **the CV must not invent anything**. Everything comes from the user's CV Master.
> The prompt only changes ORDER, EMPHASIS and HEADLINE, never the real content. It is a request to the
> model, not a guarantee: the detectors warn about unsupported figures and technologies, but
> inflation of the scope of a role (`coordinated` becoming `owned`) is not detected
> automatically.

## Mental model: IDENTITY vs POSITIONING

The basic distinction of the system (Verónica, 24 Jul 2026). Confusing the two is the origin of almost
every failure we have fixed.

| | **Identity** | **Positioning** |
|---|---|---|
| Answers | Who the candidate **IS** | How she **PRESENTS** herself for this offer |
| Nature | **Closed** | **Variable** |
| Who sets it | The `PERFIL BASE` of the Master | The **archetype** of the offer |
| Changes between offers | **Never** | Yes, in each one |
| Examples | Frontend Tech Lead, Full-Stack Developer, AI Engineer | GenAI Adoption, Context Engineering, Applied AI, AI Automation |
| Where it goes in the headline | Identity slots | **Modifier** slots |

**A positioning is not a new identity**: it is the same career presented according to
the problem the company wants to solve. That is why the positioning can change in
every offer and the identity never changes.

**The positioning also needs backing from the Master.** A positioning without
evidence is an invented identity under another name. If the Master does not back the one the
offer asks for, the one that is backed is used, even if it fits worse.

> **Design decision**: there is no `Posicionamientos permitidos` (allowed positionings) section in the
> contract, and that is deliberate. The identity is declared because it is closed; the positioning
> is **derived**, and it is already bounded by three gates that exist: the closed list of
> archetypes, the *archetype limit* (without evidence it is not forced) and the
> evidence rule on technologies. Declaring it as well would force us to maintain a list that the
> system does not need.

## MASTER RULE: projection, not a new identity

> **The adaptation must produce a different PROJECTION of the SAME professional
> career, never a new professional identity.**

Stated by Verónica on **24 July 2026**. It is the highest-level rule of the
generator: if it holds, many of the other rules follow almost for free. It automatically implies
not changing the title radically, not raising the seniority, not inventing tools, not
moving skills into experience, not turning a personal project into a multinational, and
changing only the emphasis according to the archetype of the offer.

The test: a recruiter who saw three of her CVs must recognize the
same professional with adapted content, not three different people. **If a change makes
her look like a different professional, that change is wrong even if each sentence on its own is
true.**

---

## CV prompt: 3-step structure

The role given to the model: *"senior tech recruiter reviewing 200+ CVs a day"*.
The whole CV is generated in the language of the offer (section titles and content).

### `PASO 1`: Internal analysis (mental ONLY, never written)
The model thinks, without dumping it into the output: which Master skills fit, which keywords
of the offer must appear, which achievements show the fit. **Do not invent** experience,
metrics or achievements. The response MUST start exactly with the line `HEADLINE: ...`;
writing analysis or headings before that line is forbidden.

*Why*: without this step the model tends to dump its reasoning into the final document. The
fix of 1 Jul (`1c3702a`) explicitly discards the `ANÁLISIS INTERNO` block from the CV.

### `PASO 2`: Adapted CV (main output)
Strict rules:
1. **Never invent**: only real experience from the Master. No technologies that were not used,
   leadership that was not exercised, or exaggerated metrics. The CV must be 100% defensible in an
   interview.
2. Adapt **order and emphasis** to the offer, not the content.
3. **ATS**: include the EXACT keywords of the offer when they are part of the real
   experience.
4. Bullets use the **XYZ formula** ("Accomplished X, as measured by Y, by doing Z") whenever the data
   allows it. No "responsible for...".
5. **Real density**: do not trim the Master. Recent positions get 6-9 bullets, older ones 3-4.
6. Write it as a **product profile**: business to digital solutions, collaboration with
   design and product, B2B/B2C, Design Systems.
7. Maximum 2 pages.

### HEADLINE RULES (first line of the output)

> **The headline has been data-driven since 21 July 2026.** The prompt contains NO hand-written
> identities. `test_headline_datadriven.py` fails if someone puts them back. If you want to change
> how Verónica presents herself, edit **the CV Master**, not this.

- **Source of truth**: the professional identities and target roles come from the `PERFIL BASE`
  block of the CV Master, sections "Identidades profesionales" (professional identities) and
  "Roles objetivo" (target roles). It is the ONLY source. An identity that is not there is not used.
- **How it is built**: the identities of the `PERFIL BASE` that best fit the offer are
  selected and REORDERED, and a specialization or stack is added only if it appears in the
  `PERFIL BASE` or in the Master's real experience. **The emphasis and the order change, never
  the identities.**
- **The offer decides what to highlight, never what to invent**: if it asks for a role that is not in the
  `PERFIL BASE`, it is not used. The offer only chooses which of the existing identities
  are highlighted.
- **Identity/experience coherence**: every identity in the headline must be
  justifiable by reading the Master's EXPERIENCE. If an identity of the `PERFIL BASE` has no
  experience backing it, it is left out of the headline.
- **Fallback**: if the Master has no `PERFIL BASE` block, the identities are derived from the
  real experience, never invented.
- **Nothing grandiose** (*Principal Architect*, *Head of Engineering*) unless the offer
  explicitly asks for it and it is justifiable.

#### The PERFIL BASE is a data CONTRACT (24 Jul 2026)

The root cause of title drift was not that the model invented things on a whim: it was
that **no Master had a `PERFIL BASE` block**. The prompt fell back to the fallback
("derive the identities from the real experience"), and deriving forces interpretation.
Interpretation produced *AI Engineering Leader*, and from there *GenAI Adoption Lead* or
*Solutions Architect* in the next offer.

The fix is not to ask the model to restrain itself. It is to **leave it nothing to deduce**.
The `PERFIL BASE` declares the identity in explicit sections and the prompt READS them:

| Section | What it declares |
|---|---|
| `Identidad profesional` | The complete base headline. It is the anchor |
| `Identidades permitidas` | A **closed** repertoire. No other identity exists |
| `Orden del titular` | The exact order. It is data, not a decision of the model |
| `Variante permitida` | The only alternative headline, with the condition that enables it |
| `Nunca permitido` | Restrictions declared by the Master itself. Non-negotiable |

The model's only freedoms: **replace one or two modifiers** of specialization
or stack with the ones the offer values (always taken from the Master), or **omit** one that adds
nothing. The identities and their order are not touched.

*Why*: if in each offer the candidate goes from *Frontend Tech Lead* to *AI Engineering
Leader*, then to *GenAI Adoption Lead* and then to *Solutions Architect*, it looks like she
is trying to become whatever each company asks for. The CV has to hold the same professional
identity as her public LinkedIn profile.

> **Note on reuse**: the prompt does not know any specific identity, only the
> NAMES of the contract sections. That is why the generator works for any
> user: each one declares their own `PERFIL BASE` in their Master.
> `test_proyeccion_arquetipos.py::test_titular_base_sigue_siendo_data_driven` fails if
> someone writes a specific identity into the code again.

#### The seniority guardrail is a PRINCIPLE, not a list

The previous rule enumerated *Principal, Staff, Head, Director, Architect, Distinguished,
Manager* and people *"Lead"*. The Eastern European consultancy CV came out with **"AI Engineering Leader"** and nothing
fired: *Leader* was not in the list.

Now the rule states the principle (**do not raise the hierarchical level, the authority
or the organizational scope declared in the `PERFIL BASE`**) and marks the examples as an
**open** list. The test is not whether the word appears in an enumeration, but whether the
headline suggests a higher rank than the declared one.

*General lesson*: **rules must express principles, not closed lists.** Tomorrow
*Champion*, *Evangelist*, *Technical Authority* or *Principal Contributor* will show up and
slip through again.
- **Years of experience**: base **10+**. Do not hardcode 15+ or a high number in every
  offer. Reflect more only if the offer values seniority, always truthfully.

**Practical consequence.** The headline is consistent across offers because the `PERFIL BASE` is
the same. What changes between a Frontend CV and an AI CV is which identity comes first and
which stack goes with it, not who the candidate is. That is the answer to the risk of "a different
CV in every application": it cannot happen, because the repertoire of identities is
closed and lives outside the prompt.

*Historical note*: until 21 July 2026 this section listed fixed identities
(*Frontend Tech Lead*, *Full-Stack Developer*, *UX Engineer*) and headlines by offer type,
with *AI Product Builder* and *AI Solutions Engineer* for the AI ones. That forced us to
touch the prompt every time Verónica repositioned herself, and in fact it went out of date when on
22 July both Masters changed to *AI Engineer*. That is why the repertoire moved to the
Master.

### SUMMARY: 70-80% stability (24 Jul 2026)
The summary is **not rewritten from scratch** for each offer. Roughly three quarters of it
describe the same career with the same ideas and almost the same words: where she comes from, how she
has evolved, what defines her today. Only the final part, or the specific examples that are
chosen, are adjusted to the archetype.

This way the headline, the summary and the public profile tell the same story, and that coherence
also holds in the interview.

### PROFILE: anchoring to the offer (mandatory)
The summary must RESONATE with the offer: identify 2-3 specific requirements or keywords from the
description that the candidate has ALREADY really worked with, and integrate them into the profile
written as real, demonstrable experience ("experience in X applied to Y").

*Red line*: it is FORBIDDEN to include a requirement of the offer that is NOT backed by her real
career. If the offer asks for it but she has not done it, it does NOT go in. This anchors the
profile to the offer using ONLY what is true and defensible in an interview; it is never a gateway
to invent.

#### SUBTLE anchoring: no echo (23 Jul 2026)

The anchoring is done with **her experience**, never by copying the text of the posting. If a
sentence of the profile can be traced almost literally to the offer, it is superfluous.

Handing the company its own words back as if they were traits of the
candidate is forbidden. Real example that had to be removed by hand: the offer said "small team, with
a lot of autonomy, minimal bureaucracy" and the profile came out with "Used to small
teams with high autonomy and little bureaucracy". It is not a lie, but **it says nothing about
her**: it takes up a line, adds no evidence and it shows that it was copied.

How to do it well:
- The keyword goes **inside a fact of hers**, not as a loose adjective. The offer asks for
  Core Web Vitals: "web performance optimization (Core Web Vitals)" inside the
  list of what she has done. Not: "oriented to performance optimization".
- The working conditions of the posting (team size, bureaucracy, culture,
  methodology, product traffic) are **NOT reflected in the profile**. They belong to the position, not
  to the candidate.
- Check rule: if, when reading a sentence, you can point to the line of the posting
  it came from, delete it.

### `NIVEL DEL PUESTO` (applies to the BODY, not the headline)
- If the position does NOT mention lead/manager/owner/principal/head/coordinator/director, it is
  **individual development**: reduce leadership to a minimum, reword achievements toward
  technical work (what she built, migrated, architecture/components/APIs), not toward management.
  Leadership appears as brief context, never as the main selling point.
- Only if the position asks for lead/manager/etc. are ownership and technical coordination highlighted.

*Why*: fix of 1 Jul (`0da513c`): the headline keeps the real seniority (de facto Tech Lead of
the frontend) without dropping to the level of the offer, but the body is adjusted to the real level
of the position so that it stays defensible.

### Offer ARCHETYPE (adjusts the EMPHASIS, never invents)

> Rewritten on **24 July 2026**. Until that date this section listed five
> categories and one of them was **"AI"**, just like that. That single bucket was exactly the
> failure of the Eastern European consultancy CV. Also, the list documented here had not existed in the code for a
> long time: the real prompt only said "prioritize the skills the offer values", generic.
> Now the block really exists and `test_proyeccion_arquetipos.py`
> fails if someone collapses the AI archetypes again.

The offer is classified into ONE archetype by reading the POSITION and the DESCRIPTION, never the
sector of the company. The archetype **does not touch the headline or the identities**: it decides which
experience goes first, which bullets are prioritized and which keywords come in.

- **Frontend**: React, Vue, TypeScript, frontend architecture, design systems,
  performance, accessibility, technical mentoring.
- **Full Stack**: frontend as the main strength, plus Node, APIs, databases.
- **Tech Lead**: technical ownership, standards, code review, coordination with product,
  design and backend. Do not claim people management unless the Master backs it.
- **UX Engineer**: Figma, Design Systems, accessibility, collaboration with design.
- **AI / AI Engineer**: BUILDS systems with AI. LLM, RAG, agents, APIs, Context
  Engineering, evaluation, guardrails, pipelines.
- **AI / GenAI Adoption**: gets OTHER developers to work better with AI.
  Training, workshops, mentoring, pairing, experimentation, AI-assisted development
  tools, playbooks, engineering team productivity.
- **AI / AI Solutions Architect**: DESIGNS systems. Architecture, scalability, cloud,
  integration, technical decisions, observability, governance.
- **AI / AI Product Engineer**: builds PRODUCT with AI. Metrics, users,
  experiments, UX, business, iteration.
- **AI / AI Automation Engineer**: AUTOMATES processes. N8N, MCP, APIs, workflows.

**Projection rule**: the CV is adapted to the **problem the hiring company
solves**, not to the product the candidate built. The same career is projected
toward one archetype or another without inventing anything.

**Archetype limit**: if the Master does not back the archetype of the offer, it is not
forced. An archetype without evidence is an invitation to invent.

*Real case, 24 July 2026, the Eastern European consultancy (AI adoption lead role).*
The offer asked for driving the adoption of Copilot, Claude and Cursor in engineering teams
through workshops, pairing and productivity measurement. The CV came out selling Context
Engineering, guardrails, JSON contracts and deterministic retrieval: an *AI Engineer* CV
for an *enablement* offer. The cover letter, with the same Master, did focus it correctly.

### `HECHOS, NO EFECTOS` (facts, not effects)
Write the concrete, verifiable ACTION, never the effect attributed to it, unless
the Master has the data. The reader deduces the effect alone, and is more convinced by it.

- BAD: *"Improved engineering productivity"*, *"Led AI transformation"*, *"proven track
  record of measurable productivity gains"*, *"measuring adoption impact"*.
- GOOD: *"Delivered technical workshops on Generative AI for engineering teams"*.

Unmeasured result vocabulary is forbidden when the Master does not back it: *proven
track record*, *measurable*, *impact*, *transformation*, *drove*, *boosted*,
*accelerated*.

*Why*: the Eastern European consultancy CV claimed *"Proven track record translating emerging AI
capabilities into measurable team productivity gains"* and *"measuring adoption impact"*.
There is not a single productivity metric in the Master. A concrete fact without adjectives
sells better than an effect declared without proof, and it is also defensible in an interview.

### Do not move skills into experience
A technology that the Master lists under SKILLS (`Habilidades`) but **does not attribute to a specific
position** cannot appear as an achievement of that position. Under Skills it is legitimate.

*Why*: the Eastern European consultancy CV attributed *Jest, React Testing Library and CI/CD* to the Bitcode position.
The Master has them under *Architecture & Quality*, not tied to that position. The
technology is real, the ATTRIBUTION is invented, and the technology detector does not see it
because it only compares presence, not which position it is assigned to.

### Do not leave out real technologies that the offer values (completeness rule)
The evidence rule prevents inventing. This one prevents the opposite: leaving out something real and
relevant. If the offer asks for or mentions an area and the Master has a specific technology in
that area, that technology MUST appear under Skills and, if it fits, in a bullet.

Real case, 23 July 2026, a London fintech: the CV omitted
**FastAPI** both times it was generated, even though it was in the Master and was exactly what
the offer values. It was not chance: the prompt did not have the rule, only the one about not inventing. Now it does.

### Personal projects, freelance and consulting: do not oversize the scale
A personal project is described by the **technical complexity of the work**, never by the
apparent size of the organization. The question the CV answers is not *"what company
was it?"* but *"what can Verónica do?"*.

Language that suggests teams or departments that did not exist is forbidden: *"I defined the
company's AI strategy"*, *"I led the company's architecture"*, *"responsible
for the global platform"*, *"I led a team of"*. And no CEO vocabulary
(strategy, direction, digital transformation) unless the offer is for that.

Instead: what she built, what problems she solved, what technologies she used, what architecture
she designed, what engineering decisions she made.

**The summary never revolves around the personal project.** It describes the full career;
the current experience is the example of the evolution, not the axis of the identity. The correct
narrative is *"10+ years of digital product, frontend specialization, evolution to
full-stack, current specialization in AI Engineering"*, never *"founder of X doing AI"*.

**The weight of an experience does not depend on the size of the company**, but on the relevance of
the skills for this offer. CookYourWeb can go first for being the most recent and
specialized, but presented as engineering work.

*Why*: 24 Jul 2026. The CVs tended to sell CookYourWeb, which is a personal project, with
an organization scale that does not correspond to it. It is not false (the work is real), but a senior
recruiter notices it and it costs credibility.

### The headline does not echo the posting
The identity in the headline comes from the `PERFIL BASE` exactly as written, without qualifiers from the
title of the offer. If the offer is titled *Applied AI Engineer* and the `PERFIL BASE` says
*AI Engineer*, the headline uses *AI Engineer*. Real case: a London fintech, the headline came out *Applied
AI Engineer*, copying the "Applied" from the posting.

### `PASO 3`: Anti-AI review
Remove every trace of AI-written text before delivering: zero long dashes and double dashes,
zero phrases like "responsible for..."/"oriented to...", zero empty adjectives ("dynamic",
"proactive", "passionate"), zero "passionate about"/"excited to", zero unnecessary passives.
Professional but natural tone.

> This is the first net. The SECOND net is deterministic: `sanear_tipografia()` cleans
> long dashes and arrows at render time, in case the model disobeys. See `CHANGELOG.md`.

---

## Guardrails: what is checked in the OUTPUT

The prompt is an instruction, not a guarantee. These two rules were already written and the
model broke them anyway, so the generated text is also checked and the
result is returned in the `/generar-cv` response.

Neither of them aborts the generation. An alert can be legitimate, and aborting would leave the
candidate without a CV. The warning is raised so that she reviews it before sending.

| Response field | What it contains | Function |
|---|---|---|
| `cifras_no_respaldadas` | Figures and magnitudes in the CV that are not in the Master | `detectar_cifras_no_respaldadas` |
| `tecnologias_no_respaldadas` | Technologies in the CV that are not in the Master | `detectar_tecnologias_no_respaldadas` |

The technology catalog treats spelling variants as equivalent: `RTL`,
`React Testing Library` and `Testing Library` are the same, just like `Vue` and `Vue.js`. If the
Master uses one variant and the CV another, there is no false alarm.

**Evidence rule (technologies):** a technology goes into the CV only if the Master
backs it. It does not matter that the offer asks for it.

Real case, 23 July 2026, recruitment agency offer: the offer asked for "PHP/Symfony
environments or server-side templating (Twig, Blade)". Verónica does not have that experience. The
generated CV came out with *"experience in server-side templating (integration context with
PHP/Symfony architectures)"*. It is not exactly a lie, and in a recruiter's inbox it
reads as experience. It had to be removed by hand. Now it is flagged in the response.

The detector works with a technology catalog and its spelling variants, so
that "Vue" and "Vue.js" count as the same thing and no false alarm is raised. When the Master
adds a new technology, nothing needs to be touched: the detector compares against the Master,
not against an allowed list.

**A missing alias is a hole in the guardrail.** Real case, 24 July 2026,
the Eastern European consultancy: the CV let through *"integrating Copilot-class AI systems"* without backing from the Master and the
detector said nothing. The catalog registered **"GitHub Copilot"** and the pattern uses
word boundaries, so a bare **"Copilot" did not match**. It was not a failure
of the model or of the rule: it was an alias that was missing. Fixed with
`_reg_tec("GitHub Copilot", "Copilot")` and covered by
`test_tecnologias_inventadas.py::test_regresion_la_frase_exacta_del_cv_de_n_ix`.

When adding a tool to the catalog, **also register the short name by which
people really write it**. The pattern consumes the long names first, so
registering the short alias does not produce double alerts.

---

## Cover letter prompt

Role: *expert in cover letters*. Maximum **250 words**, in the language of the offer.

- Only real experience from the Master and only the relevant part; connect with what the offer asks for.
  Do not invent, do not exaggerate, nothing hard to defend.
- **Level**: same criterion as the CV. A position without lead/manager is individual development; do not
  use team coordination as the main argument; focus on technical fit.
- Professional, direct and human tone. Zero AI phrases ("passionate", "proactive",
  "innovative solutions", "excited about the opportunity").
- Mention specific achievements or technologies from the CV that fit.
- Greeting: to the contact person if known ("A la atención de {contacto}," / "Dear
  {contacto},"), using the EXACT name, without inventing it. Otherwise generic ("Estimados/as," /
  "Dear Hiring Team,"). Formal closing + name.

---

## When editing the prompt: do not break this

- The first line of the CV MUST be `HEADLINE: ...`: the render uses it as the headline of the
  header. If the model writes anything before it, the header breaks.
- Name/email/phone do NOT go in the prompt: they are added programmatically in the DOCX.
- No markdown in the output (`**text**`, `##`, ```` ``` ````).
- Do not add a global typographic cleanup before parsing the DOCX: the detection of the company
  line uses the long dash as a marker. See `CHANGELOG.md`.

---

**Last updated:** 24 July 2026
**See also:** `../CHANGELOG.md` (technical changes), `../README.md` (user guide),
`../tests/test_proyeccion_arquetipos.py` (prompt invariants: master rule, base headline,
archetypes, facts-not-effects).
