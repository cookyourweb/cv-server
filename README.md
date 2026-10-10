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
| `GET /yo` | Google token (`Authorization: Bearer`) | Who the user is |
| `POST /registro` | Machine key | User sign-up |
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
| 200 | `{sub, email, nombre}` |
| 401 | Token missing or invalid |
| 403 | Valid token, but the email is not invited |
| 503 | Missing configuration or the public keys cannot be reached |

**Invited users.** The list is the `INVITADAS` variable (comma-separated emails, empty =
nobody gets in). It is temporary until there is a user database.

**CORS.** Only `/yo` and `/health` allow it, with exact origin matching against
`CORS_ORIGENES`. Empty = no origins.

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
