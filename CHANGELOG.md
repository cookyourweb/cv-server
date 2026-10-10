# Technical CHANGELOG: cv-server

Internal technical doc for `cv-server` (repo `github.com/cookyourweb/cv-server`, branch `main`).
The USER guide (sign-up and daily use) is `docs/USAGE-GUIDE.md`; the `README.md` presents
the project. This file is the trail
of WHY the code does what it does: decisions, fixes and traps that cannot be seen by reading
the code alone.

Service in production: `https://cv-server-ggd8.onrender.com` (Render).

> **Render does NOT read the `Procfile`.** It has its own *Start Command* stored in
> the dashboard (Settings, Start Command), and that is the one that rules. On 28 Aug 2026 the
> rename to `server.py` took down a deploy because of this: the Procfile said
> `server:app` and the dashboard still said `cv_server_railway:app`.
> If you change the module or the start flags, **it has to be changed in both
> places**. The good command, with the timeout that CV generation needs:
>
>     gunicorn server:app --bind 0.0.0.0:$PORT --timeout 120
Main file: `server.py`. Offer ranking: `real_jobs.py`.

**28 Aug 2026. The main file was split into six and renamed.** It was
`cv_server_railway.py` with 2,640 lines; now it is `server.py` with 1,165 and the
endpoints. The rest lives in `guardrails.py`, `notion.py`, `drive.py`,
`docx_render.py`, `llm.py` and `templates/alta.html` (deleted on 7 Oct). The old name said
*Railway* and the service has been running on **Render** for months.

**Architecture decisions:** see `docs/ADR-*`.
- [`docs/ADR-001-fastapi-migration.md`](docs/ADR-001-fastapi-migration.md): incremental migration from Flask to FastAPI + Pydantic (pure core + HTTP wrapper, coexistence, TDD).
- [`docs/ADR-002-cv-model.md`](docs/ADR-002-cv-model.md): which model writes the CV.
- [`docs/ADR-003-multi-account-user.md`](docs/ADR-003-multi-account-user.md): one user with several emails.
- [`docs/ADR-004-llm-backend.md`](docs/ADR-004-llm-backend.md): LiteLLM written and switched off.
- Authentication (sign-in, invitation, machine key) is in ADR-003 of the `buscartrabajo` repo (`docs/adr/ADR-003-authentication.md`), which is not the ADR-003 of this repo.

---

## LLM models (current state, 7 Oct 2026)

What production uses. The code defaults are in `llm.py`; the environment
overrides them, and `/health` (field `modelos`) shows the active ones.

| Task | Model | Variable |
|---|---|---|
| Adapted CV (`/generar-cv`) | `claude-sonnet-4-6` | `CV_MODEL` |
| Cover letter (`/generar-carta`) | `claude-sonnet-4-6` | `CARTA_MODEL` |
| CV and letter fallback (`call_llm_calidad` and `call_llm`) | If Claude fails: Groq (`openai/gpt-oss-120b`), then Gemini, then Claude Haiku. `modelo_usado` reports the model that actually wrote it | `GROQ_MODEL`, `GEMINI_MODEL`, `CLAUDE_MODEL` |
| Offer ranking (`real_jobs.rankear_con_groq`) | `openai/gpt-oss-120b` (Groq), with a deterministic heuristic fallback | `GROQ_MODEL` |
| General text (`call_llm`) | Groq, then Gemini, then Claude Haiku 4.5 | `GROQ_MODEL`, `GEMINI_MODEL`, `CLAUDE_MODEL` |

Notes:

- The default value of `CV_MODEL` in the code is still `claude-haiku-4-5`. Production
  uses Sonnet because the environment sets it that way (ADR-002).
- `llama-3.3-70b-versatile`, which ranked offers until August, is **retired**: Groq
  discontinued it on 16 Aug 2026 and the ranking now uses `openai/gpt-oss-120b`.
- Until ADR-002 (27 Jul 2026) the CV was written by Claude Haiku 4.5.

**The prompt that adapts the CV and the letter is documented in
[`docs/CV-ADAPTATION-PROMPT.md`](./docs/CV-ADAPTATION-PROMPT.md)**: 3-step structure,
HEADLINE RULES, positioning by offer type and the anti-AI rules. Read it before
touching the prompt f-string in `server.py`.

---

## October 2026

### 10-oct · Neon Postgres foundation for sign-up with CV

**What changed**

- New `base_de_datos.py`: SQLAlchemy Core engine on psycopg 3 (`pool_size=2`,
  `pool_pre_ping`, `pool_recycle=300`) plus a `transaccion()` context manager. The
  engine is built on first use from `DATABASE_URL`; importing the module neither reads
  the environment nor connects, so cold starts and `/health` never depend on the database.
- Alembic setup (`alembic.ini`, `migraciones/env.py`) that reads `DATABASE_URL` from the
  environment only, and migration `0001_alta` with users, emails, invitations, profile,
  encrypted CV masters, the extraction ledger, consents and runtime settings
  (`extraccion_activa` seeded to true). Fully reversible.
- Tests marked `bd` run against a real PostgreSQL and are skipped without
  `DATABASE_URL_PRUEBAS`.

**Why it is shaped this way**

- The extraction ledger keeps the one-attempt rule with a partial unique index,
  `WHERE usuario_id IS NOT NULL AND estado <> 'fallida'`: a provider failure does not
  consume the user's single attempt, and rows orphaned by an account deletion
  (`ON DELETE SET NULL`, no personal data) stay in the ledger so the monthly cap still
  counts them.
- Deleting a user cascades to emails, profile, CV masters and consents in one statement.

### 7-oct · Google sign-in for invited users

**What changed**

- New route `GET /yo`: receives a Google identity token (`Authorization: Bearer`)
  and returns `{sub, email, nombre}` if the person is invited.
- New module `autenticacion.py` that validates the token: RS256 only, signature against
  Google's public keys (JWKS cached for 3600 s; an unknown `kid` triggers a fresh
  download, at most every 300 s), expected issuer and audience, expiry with a
  60 s margin and `email_verified` true.
- Invited-users list by email (`INVITADAS`), provisional until there is a database.
- Exact CORS only on `/yo` and `/health` (`CORS_ORIGENES`).

**Why**

The panel needs to know who the user is without trusting an email that arrives in the body
of the request, which is exactly the hole that was closed the same day (next entry). The
user comes from the token and from nowhere else. The full decision is in ADR-003 of the
`buscartrabajo` repo (`docs/adr/ADR-003-authentication.md`).

**`/yo` responses**

| Code | When |
|---|---|
| 200 | Valid token and invited person |
| 401 | Token missing or not valid |
| 403 | Valid token, but the person is not invited |
| 503 | Configuration missing (`OIDC_*`) or the public keys cannot be reached |

**What protects it**

| Test | Guarantee |
|---|---|
| `tests/test_autenticacion.py` | Token validation: algorithm, signature, issuer, audience, expiry, verified email and key cache. With no cache and Google down, a failed download is not retried for 30 s (`REINTENTO_EN_FRIO`), so as not to block the single worker; a malformed key does not discard the others |
| `tests/test_ruta_yo.py` | Contract of `/yo`: 200, 401, 403, 503 and CORS |

---

### 7-oct · Closing the sign-up form routes

**What changed**

- Deleted `/check-email` and `/accion-existente`.
- `POST /registro` requires the machine key (`X-Clave-Maquina`) and on a failure
  returns a generic error (500), without the exception.
- `GET /` serves an invitation page (`templates/inicio.html`) with `no-store`.
- Deleted `templates/alta.html`: no route serves it any more.

**Why**

The three routes trusted an email that arrived in the request body, without
checking who sent it. That allowed:

- Enumerating accounts: asking whether an email existed.
- Launching searches on behalf of other people.
- Signing up without an invitation.

It is point 4 of the authentication ADR-003, which lives in the `buscartrabajo` repo (`docs/adr/ADR-003-authentication.md`): the user comes from the token and from nowhere else.

**What protects it**

| Test | Guarantee |
|---|---|
| `tests/test_rutas_de_maquina.py` (inventory and `test_rutas_retiradas_no_existen`) | Every machine route requires the key and the retired routes do not exist |
| `tests/test_pagina_de_inicio.py` | The landing page has no form, does not call retired routes and does not link to `/usuarios`. `test_buscar_ahora.py::test_la_portada_no_se_cachea` covers `no-store` |

---

## July 2026

### 20-jul: Typographic sanitizer. Zero long dashes or arrows in CV and letter
Commit `f0ba838`. New pure function `sanear_tipografia(texto, idioma)` in
`server.py`.

- **What it does**: removes long dashes, medium dashes and arrows from the final
  text. Arrows are translated to the transition word of the language ("a" in ES,
  "to" in EN); dashes become a normal hyphen. It is a typographic trace of AI and it CANNOT
  go out to a company.
- **Why this way**: it is a DETERMINISTIC net. It does not depend on the LLM obeying the prompt.
- **TRAP (do not break)**: it is applied only at RENDER time (DOCX and letter), NEVER on the
  text that the DOCX parser uses to detect structure. The detection of the company
  line uses the long dash as a MARKER, so the parser keeps reading the raw line
  and only the text that is written out is cleaned. If you add a global cleanup before
  parsing, you lose the bold text and the structure.
- **Tests**: `test_sanear_tipografia.py` and `test_render_sin_guiones.py`.

### 03-jul: Headlines: real identity + specialization, and adjustable years of experience
Commits `9136979`, `d70a5c6`.

- Headline system that combines real identity (Full-Stack and AI first when
  applicable) with a summary adapted per offer.
- Years of experience: base **10+**, adjustable per offer. Do NOT hardcode 15+.

### 01-jul: Refined CV rules and headline seniority
Commits `1c3702a`, `e95cf17`, `5c9d4e5`, `0da513c`.

- Discard the "ANÁLISIS INTERNO" (internal analysis) block from the CV (it must not reach the final document).
- The headline KEEPS the seniority (Tech Lead / Senior); it does not drop to the level of the offer.
- Leadership adjusted according to the level of the position.
- Rules from Vero: AI headline only in AI offers, Python as a tool,
  ATS optimization, non-grandiose tone.

---

## Operational / environment changes (NOT in git)

These fixes were configuration on Render or Brevo, not code. That is why they leave no
trace in the history and why they are documented here: if someone clones the repo, they do not see them.

### 17-jul: 500 on /generar-cv: expired Google token on Render
- **Symptom**: `/generar-cv` and `/generar-carta` returned 500 and broke the offer approval
  chain in n8n (on Approve, no letter/CV/email arrived).
- **Root cause** (confirmed with token fingerprints): Render had the OLD/expired
  `GOOGLE_REFRESH_TOKEN`. The local `.env` already had the good one (they were told apart
  by the last characters of the token).
- **Fix**: update `GOOGLE_REFRESH_TOKEN` in the Render environment variables with
  the good value. After a redeploy, 200 OK.
- **Note**: the Google Cloud project with the OAuth credentials is
  `<id-del-proyecto>` (WATCH OUT: there are two projects called "My Project" in the account, do not
  trust the name). Utilities to regenerate the token: `regenera_token.py`,
  `get_refresh_token.py`, `diagnostico_drive.py`.

### 18-jul: The approval email goes through Brevo, not Gmail
- The mail sent when an offer is approved goes out through **Brevo** (SMTP API), not Gmail.
- Verified sender: `remitente@example.com`. The Brevo credential in n8n must
  use the live API key and that exact sender; a sender or key mismatch makes Brevo
  not deliver even though the request looks correct.
- A direct test to `api.brevo.com/v3/smtp/email` with that sender returns 201 and delivers.

---

**Last updated:** 7 October 2026
**Operational source of truth for the full flow:** `../buscartrabajo/README.md`
