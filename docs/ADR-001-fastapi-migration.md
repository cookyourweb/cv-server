# ADR-001: Incremental migration of cv-server to FastAPI + Pydantic

**Status:** Accepted · 22 Jul 2026
**Scope:** `cv-server` (repo `github.com/cookyourweb/cv-server`, branch `develop`)

> **For whoever picks this up (person or AI):** this document fixes the architecture
> decisions of the migration. Do NOT re-derive them or re-argue them from memory: if you are going to
> touch an endpoint, read it in full first and follow the "pure core + HTTP wrapper" pattern.

---

## Context

- `cv-server` is currently a Flask monolith (`server.py`, ~1500 lines) with business
  logic and the HTTP layer **mixed together** in the routes. Example: `generar_cv()` mixes
  request parsing, Drive/Notion/LLM orchestration and response building in the
  same function.
- The module reads environment variables that are **required at import time** (`GROQ_API_KEY`,
  `NOTION_TOKEN`, `GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN`). That makes testing hard: importing the
  module without those env vars blows up.
- Goals of the migration:
  1. Typed contracts and input/output validation (guardrails for the AI pipelines).
  2. Separate business logic from transport: clean, testable architecture.
  3. REAL FastAPI practice for Vero's AI Engineer profile (grounded experience, not
  invented: it goes on the CV because it was actually done).

## Decisions

1. **Coexistence, not big-bang.** FastAPI is added IN PARALLEL in `api.py`; Flask
   (`server.py`) stays alive and keeps serving. Endpoints are migrated one by one.
2. **Separate logic from HTTP.** The core of each endpoint is extracted into an
   orchestration function (e.g. `generar_cv_core(email, empresa, puesto, descripcion, idioma) -> dict`).
   The Flask route and the FastAPI route are thin wrappers that call the SAME core. The extraction
   is behavior-preserving: the output does not change.
3. **Errors as a typed exception.** The core raises `CVError(status, message)`; each HTTP layer
   maps it to its own format (Flask: `jsonify` + status; FastAPI: `HTTPException`).
4. **Pydantic contracts.** Typed request and response (`GenerarCVRequest`, `GenerarCVResponse`).
   This is the code materialization of the "JSON structured outputs + validation +
   guardrails" positioning.
5. **TDD.** Test first. Because of config-at-import, tests set dummy env vars and mock the
   core / the helpers so that they do not touch real Drive/Notion/LLM.

## Consequences

- **In favor:** testable, reusable logic; the automatic OpenAPI documentation that FastAPI provides;
  a base for migrating the rest; it reinforces the AI profile with real evidence.
- **Cost:** two frameworks in the repo for a while (Flask + FastAPI) until the
  migration is complete; `uvicorn` is needed to serve FastAPI.
- **Controlled risk:** the core extraction is covered by tests and Flask stays as a safety
  net until FastAPI covers the endpoint with passing tests.

## Rejected alternatives

- **Big-bang migration** (rewrite everything at once): high risk on a service in production.
- **Duplicating the endpoint logic in FastAPI:** it would duplicate the ~290-line prompt and
  would diverge over time. Rejected in favor of extracting the core and sharing it.

## Implementation status

- **Slice 1 (in progress):** `/generar-cv` moves to `generar_cv_core` + `api.py` (FastAPI/Pydantic) + tests.
- **Next:** `/generar-carta`, `/usuarios`, `/crear-oferta`, etc., same pattern.

## API example (to understand it quickly)

Serve FastAPI locally: `uvicorn api:app --reload` (interactive docs at `/docs`).

**Valid request** (`POST /generar-cv`):

```bash
curl -X POST http://localhost:8000/generar-cv \
  -H "Content-Type: application/json" \
  -d '{
    "email": "principal@example.com",
    "empresa": "Hostaway",
    "puesto": "Senior Frontend Engineer",
    "descripcion": "React, TypeScript, design systems, testing",
    "idioma": "en"
  }'
```

**200 response** (validated against `GenerarCVResponse`):

```json
{
  "ok": true,
  "link": "https://drive.google.com/file/d/1a-Bnd.../view",
  "modelo_usado": "llama-3.3-70b-versatile",
  "archivo": "cv-veronica-serna-perez-senior-frontend-engineer-2026.docx",
  "email": "principal@example.com",
  "cv_master_usado": true,
  "idioma": "en",
  "cv_master_url": "https://docs.google.com/document/d/1XzZm1.../edit"
}
```

**A required field is missing** (e.g. no `empresa`): **automatic 422**, with none of the
core running. That is the Pydantic guardrail in action:

```json
{
  "detail": [
    {"type": "missing", "loc": ["body", "empresa"], "msg": "Field required"}
  ]
}
```

This is the typed contract: whatever does not match the shape does not get in; whatever comes out has the exact shape.

## Related findings (they do not block this migration)

- **PRICE decision (not a bug):** the CV is generated with **Groq (`llama-3.3-70b`) for now**,
  on purpose, for cost. `CV_MODEL=claude-haiku-4-5` is declared, but since no
  `CLAUDE_API_KEY` is set, `call_llm_calidad` falls back to Groq. Claude would give better quality,
  but it is deferred on price (Vero, 22 Jul). Do NOT "fix" this without an explicit decision from Vero.
  Cost note: Claude Haiku 4.5 costs ~$0.02/CV according to the code header, so the difference
  is small; if CV quality ever matters more, the jump is cheap.
- **`modelo_usado` label:** the response returns a hardcoded `GROQ_MODEL` (~L1359). TODAY it is
  correct because Groq is the one running. It would only lie if Claude were enabled and it kept saying
  Groq. Minor; when migrating, `generar_cv_core` should return the REAL model used.

## Rules for future sessions (AI included)

- Do not mix logic and HTTP in the routes again. Every new or migrated endpoint: **pure core +
  HTTP wrapper**.
- Do not break Flask until FastAPI covers that endpoint with **passing tests**.
- A technology goes on the CV only if it is real experience: this migration counts as grounded
  FastAPI practice (it was actually done).
