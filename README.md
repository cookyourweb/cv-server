[Español](README.es.md) · **English**

# cv-server

[![tests](https://github.com/cookyourweb/cv-server/actions/workflows/tests.yml/badge.svg)](https://github.com/cookyourweb/cv-server/actions/workflows/tests.yml)
[![license: PolyForm Noncommercial](https://img.shields.io/badge/license-PolyForm%20Noncommercial-blue.svg)](LICENSE)

> How work is done here (red-green-commit cycle, pre-commit hook and commit rules):
> [`CONTRIBUTING.md`](CONTRIBUTING.md). Here to **use** the service rather than read the
> code? The guide is in [`docs/USAGE-GUIDE.md`](docs/USAGE-GUIDE.md). The linked
> documents in this repo are in Spanish.

**What it is.** A service that uses LLMs to generate a CV and cover letter tailored to
each job posting, designed not to invent experience. Flask in production, migrating to
FastAPI incrementally.

**Why it matters.** A CV with one invented sentence cannot be defended in an interview,
and a service exposed to the internet cannot trust callers to be who they say they are.

**Two hard problems solved here:**

| Problem | Solution | Where to read about it |
|---|---|---|
| Detecting when the LLM invents | Six deterministic detectors checked against the CV Master: five on the CV (four are returned in the response and one is only written to the log) and three on the cover letter. They warn, they do not block. The headline is not accepted as the model writes it: it is rebuilt deterministically from the `PERFIL BASE` (base profile) (`construir_titular`) | [The interesting problem](#the-interesting-problem) |
| Letting in only invited users | Verified Google token (OIDC) for people, a machine key for n8n | [Invitation-only access](#invitation-only-access) |

```
Notion (postings + profile) ─┐
                             ├── /generar-cv ── LLM ── guardrails ── Google Drive
CV Master (Google Docs) ─────┘
```

**Models.** In production, the CV and the cover letter are written by `claude-sonnet-4-6`.
If Claude fails, it falls back to Groq (`openai/gpt-oss-120b`), then Gemini, then Claude
Haiku (`call_llm_calidad` and `call_llm` in `llm.py`). Every response reports in
`modelo_usado` (model used) the model that actually wrote it. The model is set by the
`CV_MODEL` and `CARTA_MODEL` environment variables, not by the code; `GET /health` shows
the active ones.

---

## The interesting problem

Tailoring a CV with an LLM is easy. **Keeping it from lying is not.**

A model asked to "tailor this CV to this posting" tends to pull the candidate toward the
role: it adds a technology the posting asks for, rounds a number up, widens the scope of a
role. Every one of those sentences is indefensible in an interview.

This service's answer is not just the CV: it is **six deterministic detectors** that
compare the generated text against the CV Master. Since 28 Aug 2026, three of them also
run on the **cover letter**, which until then went out with none. They warn, they do not
block.

Actual response from `POST /generar-cv` (the guardrail fields it returns today; the
other fields, such as `link` or `consumo`, are omitted):

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

| Guardrail | Where it applies | What it detects | Real case that prompted it |
|---|---|---|---|
| `cifras_no_respaldadas` | CV (returned) and cover letter | Numbers that are not in the CV Master | User counts rounded up |
| `tecnologias_no_respaldadas` | CV (returned) and cover letter | Catalog technologies the posting asks for and the Master does not back | *"experiencia en arquitecturas PHP/Symfony"* (experience with PHP/Symfony architectures) in a profile with no PHP |
| `skills_no_respaldadas` | CV (only written to the log, not returned today) | Every declared skill, checked one by one, with no catalog | *"React 19 · Tailwind (v4) · Radix UI · Mantine"*: the posting's stack, copied wholesale |
| `titular_fuera_de_contrato` | CV (returned) | Headlines that invent an identity or inflate seniority | The headline copying the job title |
| `experiencia_mal_atribuida` | Cover letter only (returned in `avisos`) | Years of experience attached to the wrong technology | The Master says *"Vue.js, 8 años"* and the letter wrote *"más de ocho años con React y TypeScript"* (more than eight years with React and TypeScript) |
| `descripcion_oferta` | CV input (returned) | **Input** too thin to tailor anything | 172-character LinkedIn postings: the headline, reworded |

The description check is the hardest to see: the others look at the output, and **a
generic CV invents nothing, it simply says nothing**. Without looking at the input,
`ok: true` hides the fact that there was no material.

`experiencia_mal_atribuida` covers a gap none of the others do: they check whether
something **exists** in the Master, this one checks **what it belongs to**. React exists,
the 8 exists, and the sentence that joins them is false.

### The cover letter goes through the guardrails too

Until 28 Aug 2026 the detectors only ran on `contenido_cv`. The cover letter is the FIRST
thing a human reads, the CV gets opened afterwards, and it went out unchecked. Now
`/generar-carta` returns `avisos` (warnings) with whatever it finds.

Three of them apply: `experiencia_mal_atribuida`, `tecnologias_no_respaldadas` and
`cifras_no_respaldadas`. `skills_no_respaldadas` is left out **on purpose**: it reads
skill lines separated by dots, and a cover letter is prose. Running it there would only
produce noise.

And they warn, they do not abort: a warning may be a legitimate rewording, and aborting
would leave the user without a cover letter.

### Translated-master mode

When the master comes from the database in another language than the document (the
response says `master_traducido: true`), detectors that compare literal text would raise
false alarms: the words simply differ between languages. Every detector in the registry
declares `independiente_del_idioma` (the input check `evaluar_descripcion_oferta` is not a detector and is outside the registry). Language-independent ones keep running (`cifras_no_respaldadas`,
`tecnologias_no_respaldadas`, `inflacion`); the text-matching ones
(`skills_no_respaldadas`, `titular_fuera_de_contrato`, whose PERFIL BASE section names are
Spanish, and `experiencia_mal_atribuida`, whose years regex is Spanish) are skipped by
`guardrails.revisar(..., traducido=True)` and listed in the `no_evaluables` field of
`/generar-carta` and `/generar-cv`, so that "no warning" is never read as "checked and clean". The
default flow (Drive master, same language) is unchanged and `no_evaluables` is empty.

### The fifth guardrail came out of the second one's failure

`tecnologias_no_respaldadas` works from a catalog of 173 variants entered by hand. None
of the four that slipped through were in it, so it was **blind** to all four.

This was not an oversight in the list. What a model copies are each posting's **new**
technologies, which by definition are not in a catalog written before reading it: an
allowlist cannot cover an open world.

`skills_no_respaldadas` (today only written to the log, not returned in the response)
flips the direction. The skills section of a CV is a list of dot-separated claims, so
each one is checked against the Master wherever the technology comes from, with no
catalog in between. The closed world moves to the right side: what the CV claims. It also
checks what is inside parentheses, where whole tools hide (`Vue 2 and 3 (Composition API,
Pinia)`), and treats versions as claims: if the Master says "Tailwind" with no version,
`Tailwind (v4)` gets flagged.

### What the guardrails do NOT detect

Inflation of **role scope**: `coordinated data contracts` becomes `own the data
contracts`, `Integrated APIs` becomes `Designed and integrated APIs`. These are not
technologies or numbers, so the comparison against the Master does not see them. It is
semantic and still open.

And one underlying limitation shared by all of them: a guardrail can only be as good as
its source of truth. If the CV Master is incomplete, it flags as unbacked something that
is real. False positives are not a detector bug, they are gaps in the Master.

### Known risk: prompt injection

The posting description is third-party text and **is not isolated in the prompt**: it is
inserted as is next to the instructions (`PROMPT_CV` and `PROMPT_CARTA` in `server.py`).
A malicious posting could try to give the model orders.

What limits the damage, without eliminating it:

- The detectors compare against the CV Master, not against the posting. A technology or
  number that the posting dictates to the model and the Master does not back gets flagged.
- The headline is not accepted as the model writes it: it is rebuilt from the `PERFIL BASE`
  (if the Master has one; without it, the model's headline is used).

There is currently no delimiter or instruction filter on the posting.

---

## AI in numbers

| What | Figure | Where to read about it |
|---|---|---|
| Cost per request | CV about 0.05 USD and cover letter about 0.013 USD with `claude-sonnet-4-6` (measured 2 Oct 2026, prompt of about 9,600 input tokens) | [ADR-002](docs/ADR-002-cv-model.md) |
| Why this model | Cost measured with `count_tokens` and real Haiku failures | [ADR-002](docs/ADR-002-cv-model.md) |
| Fallback chain | Claude, then Groq, then Gemini, then Claude Haiku; `modelo_usado` says which one wrote it | [`llm.py`](llm.py) |
| Evaluation | `evaluacion.py` is pure (it calls no model) and its tests run in the suite as a regression net. Real generation against the LLM is run by hand | [`evaluacion.py`](evaluacion.py), [`tests/test_evaluacion.py`](tests/test_evaluacion.py) |
| Known failure modes | Posting description too short (generic CV, flagged in `descripcion_oferta`); role scope inflation, not detected; response written by a fallback model | [What the guardrails do NOT detect](#what-the-guardrails-do-not-detect) |
| Prompt injection | Known risk, only partly mitigated | [Known risk](#known-risk-prompt-injection) |
| Keys kept out of logs | The Gemini key goes in a header, not in the URL, and provider errors are logged by type and HTTP code, not with their message; a test guards this | [`tests/test_claves_fuera_de_los_registros.py`](tests/test_claves_fuera_de_los_registros.py) |

---

## Architecture decisions

Documented as ADRs in [`docs/`](docs/):

- **[ADR-001](docs/ADR-001-fastapi-migration.md)**. Incremental migration to FastAPI.
  Coexistence instead of a big bang: the core is extracted (`generar_cv_core`) and the
  Flask and FastAPI routes are thin wrappers over the same core. Errors as a typed
  exception (`CVError`), Pydantic contracts, and Flask as a safety net until FastAPI
  covers the endpoint in green.
- **[ADR-002](docs/ADR-002-cv-model.md)**. Which model writes the CV, with cost
  measured via `count_tokens`, not estimated. Includes a finding that reversed the
  decision: a newer model with a lower per-token price came out **just as expensive**,
  because its tokenizer counts 50% more tokens for the same text.
- **[ADR-003](docs/ADR-003-multi-account-user.md)**. One user with several email
  accounts. Why duplicating the record is a patch that degrades silently, and why the
  final check has to be exact (Notion's `contains` filter is a substring match:
  `vero@gmail.com` matches `notvero@gmail.com`).
- **[ADR-004](docs/ADR-004-llm-backend.md)**. LiteLLM is written and left switched off
  (`LLM_BACKEND`). It was measured: +146 MB of disk, +5.96 s of startup and 207 MB of RAM
  versus 9 MB.
- **[ADR-007](docs/ADR-007-cv-encryption-at-rest.md)**. CV masters are encrypted at rest
  by the application with AES-256-GCM and a keyring that never touches the database
  (`cifrado.py`). Each ciphertext is bound to its owner and language.
- **[ADR-008](docs/ADR-008-external-encrypted-backup.md)**. Daily `pg_dump` of the database,
  encrypted with `age` to an offline public key, kept as a 30-day GitHub artifact because
  Neon's free restore window is only 6 hours.
- **[ADR-009](docs/ADR-009-rule-based-match.md)**. The offer match is plain rules, no model,
  and an offer is the caller's only if its Notion "Usuario" relation holds her page id;
  anything else is one identical 404.

- **[ADR-010](docs/ADR-010-owner-paid-generation-quota.md)**. Invited users generate CVs and
  letters on the owner's keys: 8 applications per user and UTC month (CV 0.7 + letter 0.3) and a
  20 EUR monthly cap, both reserved before any model is called; refusals are 429 with `motivo`.

> **Authentication is covered in ADR-003 of the `buscartrabajo` repo**
> (`docs/adr/ADR-003-authentication.md`), which is not the ADR-003 above.

### Known debt

`server.py` is about 1,340 lines and is still too large a module. It has not been
ignored: ADR-001 describes how it is being taken apart, with `api.py` taking over one
endpoint at a time and Flask covering until the new one is green. It is documented here
because it is the first thing you see when you open the repo.

Two other known debts:

- **Personal data in the logs.** The `/generar-cv` and `/generar-carta` logs include the
  user's email, the company and the role (for example, in the guardrail warnings).
- **Default CV model.** In `llm.py`, `CV_MODEL` still defaults to `claude-haiku-4-5`.
  Production uses Sonnet because the environment sets it; if that variable is lost, the
  CV silently switches to Haiku with no error. A separate change, with tests, will move
  the default.

## Routes

| Route | Access | Purpose |
|---|---|---|
| `GET /` | Public | Invitation page (`templates/inicio.html`) |
| `GET /health` | Public | Status, active models and deployed branch/commit |
| `GET /yo` | Google token (`Authorization: Bearer`) | Who the user is, plus `cuota: {usadas, limite, se_renueva}` for Neon users who are not exempt (units with one decimal, [ADR-010](docs/ADR-010-owner-paid-generation-quota.md)) |
| `GET /perfil` | Google token | The caller's profile (404 if none) |
| `PUT /perfil` | Google token | Create or replace the profile (422 on invalid data) |
| `POST /consentimientos` | Google token | Record a consent `{tipo, version}` (201, idempotent) |
| `POST /cv` | Google token | Upload a CV (multipart field `archivo`, PDF or DOCX, 2 MB): stored encrypted, one master per language (201 `{idioma, formato, caracteres}`; 403 without the `almacenar_cv` consent, 413, 415, 422) |
| `GET /cv` | Google token | The caller's masters, metadata only (`idioma`, `formato`, `subido_en`) |
| `DELETE /cv/{idioma}` | Google token | Delete the caller's master in `es` or `en` (204, 404) |
| `POST /extraccion` | Google token | Owner-paid extraction of profile proposals from her stored CV, empty body. 200 `{estado: "propuesta", propuestas: [{campo, valor, cita}]}` or `{estado: "manual", motivo: desactivada\|ya_usada\|tope\|proveedor\|indisponible}`; 403 without the `enviar_cv_a_ia` consent, 404 without a stored CV |
| `POST /interes` | Google token | "Tell me about packs / access through my academy" lead, body `{tipo: "paquetes"\|"academia", organizacion?: string up to 120}`. One row per user and kind, idempotent (201 `{tipo, organizacion}`; 422 on anything else); deleted with the account |
| `GET /ofertas/{id}/encaje` | Google token | Rule-based match of one of the caller's offers against her profile and master ([ADR-009](docs/ADR-009-rule-based-match.md)). 200 `{cubiertos, huecos, no_evaluables, alcanzable, cobertura}`; 404 (identical for not hers, nobody's and missing), 409 with neither profile nor master, 503 if Notion fails |
| `POST /encajes` | Google token | Same for `{"ids": [...]}` (max 50, 51 is 422): `{"<id>": {alcanzable, cobertura}}` keyed by the id as sent (summary only); ids that are not hers are silently omitted, empty ids give `{}` |
| `DELETE /cuenta` | Google token | Delete the account and its data in one transaction (204) |
| `PUT /ajustes/extraccion` | Machine key | Kill switch of the owner-paid CV extraction, body `{"activa": bool}`; no redeploy needed |
| `POST /registro` | Machine key | User sign-up |
| `POST /generar-cv`, `POST /generar-carta` | Machine key | Generation for the user's email. For a Neon user they count against the quota and the cap: **429** `{ok: false, error, motivo: "cuota"\|"tope", se_renueva: "YYYY-MM-01"}` before any model is called, **503** `motivo: "indisponible"` if the ledger is down. The owner, `CUOTA_EXENTAS` and users with no Neon row (legacy) are never counted |
| `POST /generar-cv` | Machine key | CV tailored to a posting |
| `POST /generar-carta` | Machine key | Cover letter tailored to a posting |
| `GET /usuarios` | Machine key | User list |
| `POST /crear-oferta` | Machine key | Create a posting |
| `POST /buscar-ofertas-reales` | Machine key | Posting search and ranking |

The machine key travels in the `X-Clave-Maquina` header and must match the `CLAVE_MAQUINA`
variable. If it is not configured, those routes never open (fail closed). The route
inventory is guarded by `tests/test_rutas_de_maquina.py`.

## Invitation-only access

Two separate doors, depending on who is calling:

| Who | How they get in |
|---|---|
| A person (the panel) | Google identity token on `GET /yo` |
| A machine (n8n) | `X-Clave-Maquina` header |

**How `/yo` works.** The panel sends the Google token in `Authorization: Bearer`.
`autenticacion.py` validates it: RS256 algorithm (fixed, so the token does not choose the
verifier), signature against Google's public keys (JWKS cached for 3600 s; an unknown
`kid` triggers a fresh download, at most once every 300 s), issuer in `OIDC_EMISORES`,
audience equal to `OIDC_AUDIENCIA`, expiry with 60 s of leeway, and `email_verified` true.

| Code | Meaning |
|---|---|
| 200 | `{sub, email, nombre, tiene_perfil?, origen_master}` |
| 401 | Token missing or invalid |
| 403 | Valid token, but the email is not invited |
| 503 | Missing configuration or the public keys cannot be reached |

**Invited users.** There are two modes, chosen by whether `DATABASE_URL` is set:

| Mode | Who decides | Database |
|---|---|---|
| Legacy (no `DATABASE_URL`) | the `INVITADAS` list (comma-separated emails, empty = nobody) | never touched |
| Database (`DATABASE_URL` set) | the `invitaciones` table | used on sign-in |

In database mode the identity is the Google `(iss, sub)` pair, not the email. On first
sign-in an unused, unexpired invitation for the verified email creates the user and is
consumed; a second invited mailbox of the same account is attached to the same user; a
mailbox that already belongs to another user is never merged. `INVITADAS` is ignored
unless `INVITADAS_COMO_RESPALDO=1`, a temporary bootstrap fallback that also lets the
owner in while the database is cold. It will be removed once invitations live only in the
table. `/health` never touches the database.

Add an invitation with the helper (it needs `DATABASE_URL` in the environment and never
prints it; `--dias` sets the expiry):

```bash
.venv/bin/python scripts/invitar.py ana@example.com --dias 14
```

`/yo` also returns `tiene_perfil` (true if Neon has a profile or the legacy Notion user
has a Drive master, false only when both are definitely empty, omitted when the database
or Notion cannot be reached) and `origen_master` (`drive`, `neon` or `null`).

**CORS.** The browser routes of the panel (`/yo`, `/health`, `/perfil`,
`/consentimientos`, `/cv`, `/extraccion`, `/interes`, `/cuenta`, `/encajes` and
`/ofertas/<id>/encaje`) allow `GET, POST, PUT, DELETE` with `Authorization` and
`Content-Type`, with exact origin matching against `CORS_ORIGENES`. Empty = no origins.
Machine routes never get CORS.

**The Google client ID is public on purpose.** It appears in the panel and protects
nothing by itself: what protects is the audience check, which rejects tokens issued for
another application.

**Running locally** (with the `OIDC_*` and `INVITADAS` variables from [`.env.example`](.env.example)
exported in the shell, not loaded from a file):

```bash
export CORS_ORIGENES=http://localhost:4200
.venv/bin/gunicorn server:app --bind 127.0.0.1:5000
```

The full design decision is in ADR-003 of the `buscartrabajo` repo.

### Owner-scoped routes

`/perfil`, `/consentimientos`, `/cv`, `/interes` and `/cuenta` act only on the user resolved from the token:
no path or body field names another user, and the data layer
(`RepositorioDeUsuaria(conexion, usuario_id)`) filters every statement by that id, so
another user's data is indistinguishable from data that does not exist (404). Fields are
snake_case (`anios_experiencia`, `salario_min`, `salario_moneda`); the consent types are
`almacenar_cv` and `enviar_cv_a_ia` with version `v1`. Deleting the account removes the
user, mailboxes, profile, CV master, consents and interest leads; the spend ledgers keep its rows with no
user attached, so the monthly cap cannot be bypassed. Without `DATABASE_URL` these routes
answer a generic `503`, and `/yo` and `/health` are unaffected.

**CV upload.** The type is read from the magic bytes, never from the name or the
`Content-Type`; a scanned PDF (under 300 characters of text) is refused so the panel can
offer the manual form. Only the encrypted text is stored (ADR-007), and neither the text nor
the file name is ever logged.

**Extraction gates.** The owner pays for one extraction per user. `extraccion.py` refuses it,
in this order, when the switch is off (`EXTRACCION_ACTIVA=false` or the `ajustes` row), when the
user already used her attempt, or when the month's spend plus a pessimistic estimate would pass
5 EUR; the estimate covers the primary model and its fallback (Claude then Groq, 1200 output tokens each). A failed provider chain keeps the
attempt but its estimate still counts toward the cap.

**Extraction call.** `POST /extraccion` checks the kill switch FIRST (before consent and CV, so
a switched-off extraction asks nothing of the user), then the consent and the stored CV, then
the dedicated key, then the spend gates, and calls `llm.call_llm_extraccion` once. That chain is
its own: Claude (`CV_MODEL`) and, if it fails, Groq (`GROQ_MODEL`), nothing else (never Gemini, never
the general cascade), both with `max_tokens` 1200 (`llm.TOKENS_SALIDA_EXTRACCION`, the same
constant the cost estimate uses), a 30 s timeout and no retries. Claude uses
`ANTHROPIC_CLAVE_ALTA` only, never `CLAUDE_API_KEY`; if it is empty the route answers
`{estado: "manual", motivo: "indisponible"}` without reserving or calling any provider. The CV
travels inside a data block and the answer is validated by `propuestas.py`: every proposal needs
a `cita` that is a literal quote of the CV, salary and modality are never accepted, and a stack
technology must appear in its `cita`. The user reviews each proposal in the panel before anything
is saved. The CV and letter generators keep `call_llm_calidad` unchanged.

Before enabling the switch in production: set `ANTHROPIC_CLAVE_ALTA` (its own Anthropic key with
its own monthly limit), verify the current model ids and the `PRECIO_*` constants in
`extraccion.py`, enable Zero Data Retention on the Groq account, and name Anthropic and Groq
(processing in the United States) in the consent text and the privacy policy.

## Database

User accounts, profiles and encrypted CV masters live in Neon (serverless Postgres, AWS
Frankfurt). Job postings and applications stay in Notion. The service talks to the
database through SQLAlchemy Core and psycopg 3; the engine is created lazily, so the
server starts and `/health` answers even while the database is asleep.

The schema is versioned with Alembic (`migraciones/versions/`). Connection strings come
from the environment only (`DATABASE_URL` for the service, `DATABASE_URL_PRUEBAS` for
the tests), never from `alembic.ini`:

```bash
export DATABASE_URL=...           # a development branch, never production
.venv/bin/alembic upgrade head    # apply every migration
.venv/bin/alembic downgrade base  # remove them all (development only)
```

Database tests are marked `bd` and are skipped when `DATABASE_URL_PRUEBAS` is unset, so
the suite stays green on any machine. To run them against a disposable PostgreSQL 13+
(they migrate it to head and roll back every row they insert):

```bash
export DATABASE_URL_PRUEBAS=...
.venv/bin/python -m pytest -q -m bd
```

One test runs `alembic downgrade base` (it drops every table and then restores them).
It is marked `bd_destructiva` and is skipped unless you opt in explicitly in the command
environment, never in `.env`:

```bash
ALLOW_DESTRUCTIVE_DB_TESTS=1 .venv/bin/python -m pytest -q -m bd
```

Only do this against a disposable database.

## Backups

Neon's free plan only restores the last 6 hours, so `.github/workflows/neon-backup.yml`
takes a daily `pg_dump` (Postgres 18 client), encrypts it with [age](https://github.com/FiloSottile/age)
and uploads **only the encrypted file** as an artifact kept for 30 days. Artifacts of a
public repository can be downloaded by any signed-in GitHub user, which is why a plain
dump is never uploaded. Rationale: [ADR-008](docs/ADR-008-external-encrypted-backup.md).

One-time setup (the workflow fails with a clear message until it is done):

1. Create a key pair on your own machine: `age-keygen -o age-backup.key`. Keep the file
   **offline** (two copies); it is the only way to read a backup. Never commit it.
2. The command prints the public key (`age1...`). Add it as the repository secret
   `AGE_PUBLIC_KEY` (Settings, Secrets and variables, Actions).
3. Add the repository secret `NEON_BACKUP_URL`: a connection string for the database,
   preferably of a read-only role (`pg_read_all_data`).
4. Run the workflow once with "Run workflow" and check that an artifact appears.

Restore, always on a scratch Neon branch (never on the live one):

```bash
age --decrypt -i age-backup.key neon-YYYYMMDDTHHMMSSZ.dump.age > restore.dump
pg_restore --no-owner --no-privileges --dbname "$SCRATCH_BRANCH_URL" restore.dump
```

Then point `DATABASE_URL_PRUEBAS` or a local check at that branch and compare row counts.
The CV masters stay encrypted inside the dump: you also need the application keyring
(`CV_CLAVES`) to read them. Delete `restore.dump` afterwards.

## Pre-production checklist

Environment variables Render MUST have before deploying a change that needs them. A
missing one does not crash the service: the feature quietly degrades.

- [ ] `NOTION_DB_OFERTAS`: id of the Notion offers database. There is no default in the
  code any more. Without it the offer lookups return nothing, `/crear-oferta` answers 502
  and `GET /ofertas/{id}/encaje` and `POST /encajes` answer 503. **Set it on Render before
  deploying the offer-match change (ADR-009).**
- [ ] `NOTION_TOKEN` and `NOTION_DB_USUARIOS`: the owner of an offer is resolved through them.
- [ ] `DATABASE_URL`, `CV_CLAVES`, `CV_CLAVE_ACTIVA`, `CORS_ORIGENES`: see "Database" and
  "Invitation-only access".
- [ ] Generation quota and cap ([ADR-010](docs/ADR-010-owner-paid-generation-quota.md)), BEFORE
  `DATABASE_URL` is set on Render and migration `0002_cuota` is applied:
  - [ ] `CUOTA_EXENTAS`: the owner's mailbox(es), comma-separated. Without it a database outage
    could refuse her own generation.
  - [ ] `CUOTA_SOLICITUDES_MES`, `CUOTA_UNIDADES_CV`, `CUOTA_UNIDADES_CARTA`,
    `TOPE_GENERACION_EUR`: only if the defaults (8, 0.7, 0.3, 20 EUR) are not what you want.
  - [ ] `AVISO_GASTO_EMAIL`, `BREVO_API_KEY`, `BREVO_REMITENTE`: the 70 % alarm mail. Without
    all three no mail is sent (generation still works). The sender must be verified in Brevo.
  - [ ] Verify the `PRECIO_*` constants (primary, Groq, `PRECIO_GEMINI_*`) against the providers'
    price pages, as for the extraction.
  - [ ] Set a monthly **spend limit on the Anthropic console** for the key behind `CLAUDE_API_KEY`:
    a second layer that does not depend on this code's estimate.

## Tests

```bash
pytest -q     # 381 tests
```

Tests are written first. Each one documents in its docstring **the real failure that
prompted it**, with a date, not a hypothetical case.

## Stack

`Python` · `Flask` and `FastAPI` · `Pydantic` · `Claude API` · `Notion API` ·
`Google Drive API` · `python-docx` · `pytest` · `Render`

## License

[PolyForm Noncommercial 1.0.0](LICENSE). You can read, study and use this code for personal, learning or other noncommercial purposes. Commercial use, such as selling it, offering it as a service or using it in a for-profit company, needs permission: get in touch through [cookyourwebai.es](https://cookyourwebai.es).

Code published before 8 Oct 2026 was released under the MIT license, and those earlier versions remain under MIT.
