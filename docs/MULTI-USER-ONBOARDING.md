# Multi-user onboarding: from any CV to a PERFIL BASE

Spec of the sign-up interview. **Not implemented yet.** Written on 24 July 2026,
expanded on the 25th with the three-layer architecture and the 9-step flow.

> **Language note.** `PERFIL BASE` and the names of its sections (`Identidad profesional`,
> `Identidades permitidas`, `Orden del titular`, `Variante permitida`, `Nunca permitido`, and so on)
> are literal identifiers: the prompt in `server.py` reads them by name. They stay in Spanish
> and are glossed in English the first time they are explained. See `CV-ADAPTATION-PROMPT.md`.

---

## THE ROOT LESSON: the problem was never the CV

We were trying to adapt a document that **mixed three different things**:

1. **Who you are** (identity)
2. **What you have done** (facts)
3. **How to sell it for a specific offer** (adaptation)

A document that mixes the three layers forces the model to separate them on its own every time
it generates, and that is where it invents. The solution was not a better rule: it was **separating the
layers in the data**.

| Layer | What it is | Changes |
|---|---|---|
| **PERFIL BASE** | Permanent identity | Almost never |
| **Master CV** | All the verifiable facts | When new facts happen |
| **Adapted CV** | Selection and order of those facts according to the offer | In every offer |

With the layers separated, generating a CV stops being "reinterpreting who you are" and becomes
**selecting and ordering facts that already exist**. That is what removes invention.

> **If we had to build the system from scratch for another person, we would start with this
> architecture.** Not with the CV. The CV is the output, not the starting point.

---

## THE ORDER OF THE INTERVIEW (build the Master BEFORE generating CVs)

The starting mistake would be to ask for "the CV and the offer". The right order is the reverse: **first
the Master (the source of truth) is built, then infinite adapted CVs are generated.** The
offer does not come in until the Master is finished.

Nine steps, in this strict order:

1. **Professional identity**: before anything else, who you are. *What do you really do? What
   problems can you solve? What positions can you defend in an interview? What positions do you NOT
   want to ever appear?* Identity is the only thing that does not change between offers.
2. **Professional goal**: *What types of offer do you want to be able to target with this Master?*
   (Backend, Frontend Tech Lead, AI Engineer, Engineering Manager, Solutions Architect,
   GenAI Adoption...). Not to put it on the CV: to know which variations the system must
   support. It feeds `Tipos de oferta compatibles` (compatible offer types).
3. **Current CV**: now, yes. Not to improve it, but to **extract facts**: companies, projects,
   technologies, responsibilities, achievements, education.
4. **What is missing**: where almost every CV fails. *What do you really do that does not appear on
   the CV?* Mentoring, interviewing, documenting, experimenting, automating, training teams,
   defining processes, comparing tools, doing architecture. It happens, but nobody writes it down.
5. **Limits**: *What do you NOT want the system to ever invent?* Do not invent leadership,
   metrics, teams, technologies, cloud, AI. **This is where that user's guardrails are born.**
6. **Structured identity**: the `PERFIL BASE` is built with `Identidad profesional` (professional
   identity), `Identidades permitidas` (allowed identities), `Orden del titular` (headline order),
   `Variante permitida` (allowed variant), `Nunca permitido` (never allowed), `Tipos de oferta
   compatibles` (compatible offer types), `Áreas de contribución` (contribution areas),
   `Posicionamiento` (positioning), `Especialización` (specialization) and `Tecnologías principales`
   (main technologies). This block will hardly ever change.
7. **Experience**: the bullets are NOT written thinking about an offer, they are written thinking
   *what really happened?* Each experience answers: what you built, designed, led,
   automated, learned; what technologies, what decisions, what you taught, what you documented.
   Still without thinking about ATS.
8. **Keyword inventory**: only when the Master is finished. A large inventory (AI
   Engineering, LLMs, OpenAI, Claude, React, Node, Developer Productivity, AI
   Adoption, Architecture, Technical Leadership...). Not to include them all: so that the
   adapter can **choose** according to the offer.
9. **System rules**: at the very end. Do not invent experience, do not change seniority,
   do not create new identities, do not alter the headline order, adapt the emphasis and not the
   facts, prioritize relevant experience, reuse only information that exists in the
   Master.

**Why this order matters:** ATS and adaptation go last on purpose. If the offer is thought about
before the facts are in hand, the user (or the model) starts writing to please instead of
to describe, and that is where invention comes back. First the truth, then the sale.

---

The rest of this document details HOW to run those steps: what is read instead of asked,
the questions anchored in real failures, and where the contract lives.

- **What the interview produces**: the `PERFIL BASE` block (step 6) + the Master of facts
  (step 7). See `CV-ADAPTATION-PROMPT.md`, section *The PERFIL BASE is a data CONTRACT*.
- **Why the PERFIL BASE is needed**: without that block the prompt falls back to the fallback ("derive the
  identities from the experience") and **deriving forces interpretation**. Interpretation produced
  *AI Engineering Leader* in the Eastern European consultancy CV. The interview exists so that the model does not
  have to deduce anything.

---

## Principle: do not ask what you can read

A long form kills sign-up. And most of the answers are already in the two
documents the user has just handed over. Three modes, and only the third costs time:

| Mode | What it is | Cost for the user |
|---|---|---|
| **EXTRACT** | Read from the CV or LinkedIn. Not asked | Zero |
| **CONFIRM** | The extracted data is proposed and they say yes or correct it | One click |
| **ASK** | It is in no document. It has to be asked | Real |

**Every question in this document justifies its existence with a real failure** made
while generating Verónica's CVs. A question with no failure behind it does not get in.

---

## It hooks into the sign-up that ALREADY exists

It is not a new sign-up. The current registration is done by the administrator with `POST /registro`, which
since 7 Oct 2026 requires the machine key. The public form that was served at `/`
was removed: today `/` is an invitation page. The sign-up creates the user in Notion with
these fields:

```bash
curl -X POST "$BASE/registro" \
  -H "Content-Type: application/json" \
  -H "X-Clave-Maquina: $CLAVE_MAQUINA" \
  -d '{"nombre": "...", "email": "persona@example.com", "perfil": "...",
       "rol_objetivo": "...", "ciudad": "...", "stack": ["..."],
       "modalidad": ["..."], "salario_min": 0, "linkedin": "...",
       "cv_master_url": "..."}'
```

Only `email` is required by the route; the rest fills in the profile in Notion.

| Field in Notion | What it is | For the interview |
|---|---|---|
| `Email` · `Name` · `Ciudad` | Identification | n/a |
| `LinkedIn` | Profile URL | **EXTRACT source** |
| `CV Master URL` · `cv_master_file_id` | The Master in Drive | **EXTRACT source** |
| `Perfil` | Free text | Overlaps with `Resumen profesional` |
| `Rol objetivo` | Free text | Overlaps with `Roles objetivo` |
| `Stack` | Multi-select | Overlaps with `Tecnologías principales` |
| `Salario min` · `Modalidad` · `Activo` | Search filters | n/a |

**The two sources the interview needs are already requested.** And three fields already cover part of the
contract: they are not asked again, they are **confirmed**.

The new steps are only the ones that produce what does not exist today: identities, order,
variant, positioning and the evidence and boundary questions.

---

## WHERE THE CONTRACT LIVES: in Notion, not in the Google Doc

With Verónica the `PERFIL BASE` was pasted **by hand** at the top of her CV Master. For a
single user that works. For multi-user it does **not**, and there is evidence from the same day.

*On 24 Jul 2026, while pasting that block into two documents, the Spanish content ended up inside the
English Master **twice in a row**. It was caught by a read from Drive, not by the user. If
the person who designed the block gets it wrong, anyone will.*

**Proposal (not implemented)**: the contract is stored as user fields in Notion, and
the server **builds the `PERFIL BASE` block and prepends it to the Master text** before
sending it to the model. The user pastes nothing. Their Master remains only their CV.

Advantages, beyond removing the copy and paste:

- **Editable from the application**: changing the headline means updating a field, not re-editing a
  Drive document.
- **Validatable**: you can check that `Identidades permitidas` has between 1 and 4 entries, or
  that the variant condition contains proper names and not a category. Nothing can be validated on text
  pasted into a Doc.
- **It also fixes the detector inconsistency**: today
  `detectar_tecnologias_no_respaldadas` compares against the full text of the Master,
  `PERFIL BASE` included, so a technology written there is considered backed and
  blinds the guardrail. If the block is injected separately, the detector can keep comparing
  against the Master **without** the block, which is what the prompt says must happen.

The prompt **does not change**: it keeps reading the same sections by name. Only who
writes the block and where it is stored changes.

---

## PHASE 0: EXTRACT (without asking anything)

From the CV and the LinkedIn profile, the following is taken automatically:

- Current LinkedIn headline: candidate for `Identidad profesional`
- Positions, companies and dates
- Technologies mentioned, and **in which position each one appears**
- Education and languages
- Total years of career

None of this is ever asked. It is already written.

---

## PHASE 1: CONFIRM the identity (one click per question)

What was extracted is proposed and the user validates it. This builds the contract.

**1.1 · Your headline**: *"Your LinkedIn says X. Is that the headline you want all your CVs to be
generated with?"*
Goes to: `Identidad profesional`

**1.2 · Your identities**: *"I have detected these: A, B, C. Are there too many, or is one missing?"*
Maximum 4. It is a **closed** repertoire: no other can ever be used.
Goes to: `Identidades permitidas`
*Prevents*: identities invented per offer (*AI Engineering Leader*, *GenAI Adoption Lead*).

**1.3 · The order**: *"In what order do they go? The first is the one people will identify you by."*
Goes to: `Orden del titular`
*Prevents*: the CV being reordered according to the offer and looking like a different person in every application.

**1.4 · The exception**: *"Are there specific companies for which you would invert that order?
Name them. If in doubt, leave this empty."*
Goes to: `Variante permitida`

> **This is the most delicate question of the whole sign-up.** On 24 Jul 2026 Verónica's condition
> said *"companies whose main product is AI (OpenAI, Anthropic,
> Cohere...)"*, and the model applied the variant **to the Eastern European consultancy and to the London fintech**, which are neither of
> those. It read the parenthesis as examples, not as a closed list. It is the same pattern that
> let *"Leader"* through the seniority guardrail.
>
> **Rule that follows**: the condition must be a **list of proper names**, never a
> category. If the user answers with a category ("AI companies", "startups"), the question
> must be asked again, requesting names. And if they do not know which, it is left empty: **with no variant
> declared, no exception is possible.** Empty is safer than ambiguous.

**1.5 · Seniority**: *"How many years do you declare?"*
*Prevents*: inflating the number according to what the offer values.

**1.6 · What you are not**: *"What role are you mistaken for that you do not want to be mistaken for?"*
Goes to: `POSICIONAMIENTO` block
Verónica: *"I am not a Data Scientist. I am not an AI researcher."* It is a boundary, and the prompt
respects it even if the offer asks for the opposite.

---

## PHASE 2: the EVIDENCE (what prevents inventing)

Confirming is not enough here: you have to ask. This is what separates a defensible CV from a pretty one.

**2.1 · What you did**: for each relevant position, *"What did you do with your own hands, not your
team?"*
*Prevents*: taking credit for the team's work.

**2.2 · Technologies per position**: *"Of these that appear on your CV, which did you use **in this
specific position**?"*
*Prevents*: the GraphQL failure. In the London fintech CV the model wrote *"implemented
GraphQL and webhook patterns"* in the Bitcode position, when the Master only has them under
skills without tying them to any position. The technology was real; **the attribution was invented**.

**2.3 · Figures**: *"What figures can you defend with real data that you have at hand?"*
If there is no data, there is no figure. A CV without figures is defensible; with an invented figure, it is not.

**2.4 · What you know but did not use**: *"What technologies have you touched but would not use as an
argument in an interview?"*
They go to an **explicit blacklist** for the user. It complements the detector, which can only
compare against the Master.

---

## PHASE 3: the BOUNDARY (the only thing no guardrail covers)

The two most important questions of the sign-up, and the ones nobody asks.

**3.1 · Aspiration**: *"What do you want to do that you have not done yet?"*
Goes to `Roles objetivo` (target roles), **never to Experience**. The prompt treats the `PERFIL BASE` as an identity guide
and **never as evidence**, so declaring it there cannot inflate the body of the
CV. The aspiration is stated without claiming anything.

**3.2 · The interview test**: *"Is there anything on your current CV that you could not defend in
twenty minutes of interview?"*

> **Why this question exists.** All the guardrails in the system compare **the generated CV
> against the Master**. If an unbacked claim lives **inside the Master**, it is
> undetectable: the Master is the axiom.
>
> On 24 Jul 2026 both of Verónica's Masters claimed *"technical training for companies"*.
> She had not yet taught any course to companies. No detector could see it, and a cover letter to the Eastern European consultancy
> claiming it had already come out of that. She stopped it, not the system.
>
> **The evidence rule protects the offer-to-CV boundary. It does not protect the
> reality-to-Master boundary. Only the person can hold that one.** With an unknown user, this
> question is all there is. It is worth repeating each time they edit their Master.

---

## PHASE 4: Archetypes

**4.1**: *"What type of position are you aiming for?"* They are shown the archetypes the prompt knows how to
tell apart (see `CV-ADAPTATION-PROMPT.md`) and choose one or several.

**Known limitation**: the archetypes are **written in the prompt** and belong to the
technology sector. A design, sales or administration profile fits none of them. To open the
system outside technology they will have to be moved into data, as was done with the identities.
It is not touched until there is a real user who needs it.

---

## Output of the interview

The block that is pasted at the top of the user's CV Master:

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

(The parenthesized notes read: `fijo, igual para todos` is "fixed, the same for everyone";
`extraído, confirmado` is "extracted, confirmed"; `extraído de fechas y puestos` is "extracted from
dates and positions".)

---

## Mistakes to avoid at sign-up

- **Do not ask what is in the CV.** Every redundant question is a user who drops out.
- **Do not accept categories where a list of names is needed** (question 1.4).
- **Do not let the aspiration into Experience.** It goes to `Roles objetivo` and that is it.
- **Do not paste technologies into the `PERFIL BASE` that are not in the experience.** The detector
  compares against the full text of the Master, `PERFIL BASE` included: writing a
  technology there marks it as backed and **blinds the guardrail**. Known inconsistency between the
  prompt (which says the `PERFIL BASE` is not evidence) and the detector (which does not tell
  sections apart). If it ever bites, it is fixed by excluding the block from the text the
  detector sees.

---

**See also**: `CV-ADAPTATION-PROMPT.md` (the rules this interview feeds),
`../tests/test_proyeccion_arquetipos.py` (the prompt invariants).
