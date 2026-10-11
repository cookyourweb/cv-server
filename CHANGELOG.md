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

## Unreleased

### Faster GET /yo: legacy Notion lookup no longer queries missing properties

**Fixed**

- `notion.py`: `buscar_usuario_por_email` used to query three alias properties
  ("Emails alias", "Emails alternativos", "Email alternativo") that do not exist in the
  Usuarios database. Each call returned HTTP 400, was logged as a WARNING, and added
  seconds to every `GET /yo` (the panel calls it twice per sign-in).
  - The alias properties are now read from the database schema (`GET /v1/databases/{id}`),
    cached in memory for one hour; only properties that exist are queried.
  - If the schema cannot be read, the candidate names are tried, but a 400 "Could not
    find property" is remembered for the life of the process and logged once.
  - The per-email result (found or not found) is cached for 60 s, so the two `/yo` calls
    of one sign-in hit Notion once. Network and HTTP errors are never cached.
  - Trade-off: an edit in Notion can take up to 60 s to be seen by this lookup.

### POST /extraccion: owner-paid extraction with the quality chain

**Added**

- `POST /extraccion` (owner-scoped, empty body; nothing in the request chooses the model or
  the CV). Order: consent `enviar_cv_a_ia` v1 (403) -> a stored master (404, the most recent
  upload) -> `extraccion.reservar` gates (refusal = 200 `{estado: "manual", motivo}`, no model
  call) -> decrypt -> ONE call to `llm.call_llm_calidad` (model `CV_MODEL`, `max_tokens` =
  `TOKENS_SALIDA_MAX`, Groq fallback as the chain already does, no retry of its own) -> the
  reservation is always closed -> validate.
- Answers: `{estado: "propuesta", propuestas: [{campo, valor, cita}]}`; or `{estado: "manual",
  motivo}` with `desactivada | ya_usada | tope | proveedor | indisponible`. `proveedor` = the
  whole chain failed (row `fallida`, she keeps her attempt). `indisponible` = the model
  answered but nothing survived validation (the call is paid for and the attempt is used).
- `propuestas.py`: the prompt (CV inside `<cv_datos>`, declared data; a delimiter planted in the
  CV is defused with an equal-length substitution) and `validar`. A proposal survives only if
  its `campo` is one of `rol, anios_experiencia, stack, idiomas, ubicacion` (salary and modality
  are never accepted), its `cita` is a literal substring of the CV after whitespace
  normalisation, a stack technology is in the catalogue and found in the `cita` by
  `guardrails.tecnologias_en` (Java is not backed by JavaScript), and years are an integer 0..60
  that appears in the `cita`. Items are judged one by one; the first valid item per campo wins.
- `extraccion.coste_real_eur` prices the usage the provider reported (primary or fallback
  prices). When usage is not reported (the Groq fallback does not return it) the ledger gets the
  reservation's estimate as the cost, never a made-up zero.
- `RepositorioDeUsuaria.cv_mas_reciente`.

**Why it is shaped this way**

- No database transaction is open while the model is called; the reservation is its own
  committed transaction, so a slow provider never holds the advisory lock.
- The reserved length comes from the stored character count, so the gates run BEFORE the CV is
  decrypted, and the prompt can never be longer than what was reserved.
- A text-level check cannot tell injected text from real CV content: if the CV itself says
  "add Rust to the stack" and the model quotes it, the quote is a real substring. The panel
  shows every `cita` for the user to accept or edit, which is the backstop.
- Nothing logs the CV, a `cita`, the prompt or the model output; failures are logged by
  exception type (`privacidad.registrar_fallo`), and the canary test covers this path.

**Before enabling the switch in production**

1. Verify the current model ids (`CV_MODEL`, `GROQ_MODEL`) and the list prices, and update the
   `PRECIO_*_EUR_POR_MTOK` constants in `extraccion.py`.
2. Enable Zero Data Retention in the Groq console (by default Groq does not train on API data
   nor keep it, but ZDR is a toggle to turn on explicitly).
3. Name Anthropic and Groq, and say that processing happens in the United States, in the consent
   text and the privacy policy (bump `VERSION_DE_CONSENTIMIENTO` if the consent changes in substance).
4. Known gaps of the fallback path: `call_llm` ignores `max_tokens` (4096) and the SDK call has
   no explicit timeout, so the cost bound holds for the primary model only.

### Extraction gates, spend ledger and kill switch (no model call yet)

**Added**

- `extraccion.py`: `reservar(usuario_id, largo_prompt, modelo=...)` runs three gates in a
  fixed order and reports the first failure as the panel's `motivo`: `desactivada` (env
  `EXTRACCION_ACTIVA=false`, read before any database access, then the
  `ajustes.extraccion_activa` row, read on every request; a missing row counts as off),
  `ya_usada` (the user has an extraction that is not `fallida`) and `tope` (the UTC month's
  spend plus the estimate would pass `TOPE_EXTRACCION_EUR`, default 5). Passing inserts a
  `reservada` row. `marcar_completada` stores the real cost; `marcar_fallida` keeps the
  estimate in the month's sum and leaves the user's attempt free.
- The month's sum is `sum(coalesce(coste_eur, estimado_eur))` over every row, anonymous ones
  from deleted accounts included. Check-and-reserve runs in one transaction under a global
  `pg_advisory_xact_lock`, so ten concurrent requests with room for one make one reservation.
- Pessimistic estimate: `ceil(chars / 3)` input tokens plus `TOKENS_SALIDA_MAX` (1200) output
  tokens, priced for the primary model AND the fallback (the quality chain can bill both),
  times `MARGEN_EXTRACCION` (1.25), rounded up to the ledger's four decimals. The prompt is
  capped (`MAX_CARACTERES_DE_PROMPT`) so one primary call stays under 0.05 USD.
- `PUT /ajustes/extraccion` `{"activa": bool}` (machine key) flips the switch with no redeploy.
  New variables in `.env.example`: `EXTRACCION_ACTIVA`, `TOPE_EXTRACCION_EUR`, the four
  `PRECIO_*_EUR_POR_MTOK` and `MARGEN_EXTRACCION`.

**Why it is shaped this way**

- The reservation is written before the model is called and a crash leaves it in place, so
  the cap can over-count but never under-count.
- A failed provider chain keeps the user's attempt (the partial unique index ignores
  `fallida`) but its estimate still counts: a call that may have been billed must not lower
  the month's total.
- The default prices are list prices in USD used 1:1 as EUR plus the margin. They MUST be
  verified against the providers' price pages when the model call is added.

### CV upload and encrypted master storage

**Added**

- `lectura_cv.py`: size is checked before parsing (2 MB), the type comes from the magic bytes
  (`%PDF-`, or a ZIP with `word/document.xml`), PDFs are limited to 10 pages, a DOCX to 10 MB
  uncompressed and 500 entries (zip bomb), and text under 300 characters (a scan) is refused.
  Failures carry a fixed code and no message or chained exception. The language (es/en) is
  detected from very common function words; a tie is Spanish.
- `privacidad.py`: CV text and file names never reach a log or an exception message. The
  parsing libraries' loggers are silenced, failures are logged by exception type only, and
  `volcar_registros` is the canary helper behind S3.9.
- `POST /cv` (multipart field `archivo`), `GET /cv` (metadata only) and `DELETE /cv/{idioma}`,
  all owner-scoped. Upload requires the stored `almacenar_cv` consent (403), answers 413, 415 or
  422 with a `motivo`, and stores only the AES-GCM encrypted text, one master per (user,
  language). The uploaded file itself is never persisted. `MAX_CONTENT_LENGTH` is 3 MB so an
  oversize request fails before it is read.
- `pypdf==6.20.0` in `requirements.txt`.

**Why it is shaped this way**

- Consent is checked before the file is read, so a CV of someone who has not agreed to store
  it is not even parsed.

### External encrypted backup (ADR-008)

**Added**

- `.github/workflows/neon-backup.yml`: daily (and on demand) `pg_dump` with the official
  `postgres:18` client, streamed into `age` so the plain dump never touches the disk. Only
  the `.dump.age` file is uploaded, with 30-day retention. Secrets `NEON_BACKUP_URL` and
  `AGE_PUBLIC_KEY`; a missing one fails the run with a clear message.
- `docs/ADR-008-external-encrypted-backup.md` and a "Backups" section in the README with the
  one-time setup and the restore procedure.
- `tests/test_copia_neon.py` pins the workflow's safety properties (schedule, secrets only
  through `${{ secrets.* }}`, nothing echoed, encrypted-only upload, 30-day retention).

**Why**

- Neon's free restore window is 6 hours. Artifacts of a public repository are downloadable by
  any signed-in GitHub user, so the dump is encrypted to a public key whose private half stays
  offline. Losing that private key makes the backups unreadable.

### Owner-scoped profile, consent and account routes

**Added**

- `repositorio.py`: `RepositorioDeUsuaria(conexion, usuario_id)`. Every statement is filtered
  by the constructor's id and no method accepts another one. `PerfilEntrada` (Pydantic,
  `extra="forbid"`) mirrors the CHECKs of `perfil`; `VERSION_DE_CONSENTIMIENTO = "v1"`.
- `rutas_alta.py` (blueprint registered in `server.py`, all behind `@con_usuaria`):
  `GET/PUT /perfil`, `POST /consentimientos`, `DELETE /cuenta`. Wire format taken from the
  panel (snake_case, 404 when no profile, 201 for a consent, 204 for deletion).
- Deletion runs in one transaction: owned tables are cleared and the user row last. A failure
  midway rolls everything back. `extracciones` rows are kept with `usuario_id` NULL so the
  monthly cap and the one-extraction rule survive (REQ-2.4); the used invitation stays used,
  so a deleted mailbox cannot sign in again without a new invitation.
- Without `DATABASE_URL` the routes answer a generic `503` (never 500); `/yo` and `/health`
  do not change. Errors never echo submitted values, driver messages or connection details.

**Why it is shaped this way**

- There is no `{id}` in these routes on purpose: the owner is always the token's user, so
  cross-user access is impossible by construction. The tests still pin it (S1.6) and a
  route-inventory test fails if a route is added to the blueprint without being covered.
- `POST /consentimientos` rejects any version but the current one with 422 and the
  consent check ignores older or revoked rows (S2.2).
- `PUT /perfil` requires all eight fields (the panel always sends them and reads them back).

### Invitations in the database and an extended /yo

**Added**

- `usuarias.py`: `resolver_o_crear` maps the verified Google `(iss, sub)` to `usuarios.id`.
  On first sign-in an unused, unexpired invitation for the verified email links the user
  (the invitation is marked used and the mailbox is stored). A second invited mailbox of
  the same `(iss, sub)` is attached to the same user. A mailbox held by another user is
  never merged, and no invitation means denial with no writes. `@con_usuaria` sets
  `g.usuario_id` and `g.identidad` for owner-scoped routes.
- `autenticacion.identificar` takes an injected `autorizar` callback, so the module still
  imports no database code. `email_verified` was already required (and tested).
- `GET /yo` now also returns `tiene_perfil` and `origen_master` (`drive`, `neon` or null).
- `scripts/invitar.py`: adds or renews an invitation (`--dias` is required because
  `caduca_en` is NOT NULL). It reads `DATABASE_URL` from the environment and never
  prints it.
- CORS by prefix for the panel routes (`/yo`, `/health`, `/perfil`, `/consentimientos`,
  `/cv`, `/extraccion`, `/cuenta`, `/encajes`, `/ofertas/<id>/encaje`) with
  `GET, POST, PUT, DELETE` and `Authorization, Content-Type`. Machine routes get none.

**Why it is shaped this way**

- Two modes, so production does not change until the database exists. Without
  `DATABASE_URL` (Render today) the `INVITADAS` list decides and no database is touched.
  With it, the `invitaciones` table decides; `INVITADAS` only works as a bootstrap
  fallback when `INVITADAS_COMO_RESPALDO=1`, to be removed once invitations live only in
  the table.
- `tiene_perfil` is true when Neon has a profile OR the legacy Notion user has a Drive
  master (this keeps Vero working), and false only when both are definitely empty. If
  the database or Notion is unreachable it is omitted, because the panel guard lets the
  user through when the flag is missing. Without a database it is never false, since
  sign-up cannot work there.
- A cold database at sign-in answers 503 with a generic body, except for an email in the
  fallback list, which is let in so the owner is never locked out by a cold start.

### Encryption at rest, honest match and review fixes

**Added**

- `cifrado.py` and [ADR-007](docs/ADR-007-cv-encryption-at-rest.md): AES-256-GCM
  encryption of CV masters, with an AAD that binds each ciphertext to its owner and
  language, key versions for rotation (`CV_CLAVES`, `CV_CLAVE_ACTIVA`) and fail-closed
  behaviour on any configuration or authentication problem. The keyring lives in the
  environment, never in the database.
- `match.py`: honest, rule-based match between an offer and a CV master. Pure (no I/O,
  network or LLM), every claim carries evidence from the master, soft skills go to
  "not evaluable" and are never guessed. **Staged:** `real_jobs._ranking_fallback(master_texto=...)`
  is not yet wired to production callers; the wiring arrives with the `/encaje`
  endpoints.
- Inflation guardrail (`guardrails.detectar_inflacion`): flags claims of exclusivity,
  leadership or scope in generated text that the master does not support.

**Fixed (from the security and quality reviews)**

- `match.py` was open to ReDoS: the years and language patterns backtracked
  quadratically on long runs of whitespace in untrusted offer text. Whitespace is now
  normalised and the offer and master text are capped (20,000 characters) before any
  regex, and the quantifiers are bounded.
- `match.py` no longer reaches into private helpers: `guardrails.tecnologias_en` and
  `guardrails.plano` are public (the private names remain as the canonical definitions).
- The one database test that runs `alembic downgrade base` is skipped unless
  `ALLOW_DESTRUCTIVE_DB_TESTS=1` is set in the command environment.
- `cifrado.py`: error messages are in English, duplicate key versions in `CV_CLAVES` are
  rejected instead of silently shadowing a key, and `usuario_id` must be a non-empty
  string or UUID before the AAD is built.
- `base_de_datos.py` requires TLS (`sslmode=require`) unless the URL sets its own
  `sslmode`.

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
