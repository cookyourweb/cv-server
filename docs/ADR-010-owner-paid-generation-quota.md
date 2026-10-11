# ADR-010: Generation is paid by the owner within a monthly quota and a global cap

**Status:** Accepted · 11 Oct 2026
**Scope:** `cv-server`, module `cuota.py`, migration `0002_cuota`, routes `/generar-cv`, `/generar-carta`, `GET /yo` (field `cuota`) and `POST /interes`. Amends ADR-004 of the `buscartrabajo` repo ("Everything else remains BYOK").

> **For whoever picks this up (person or AI):** this document fixes WHY invited users
> generate CVs and cover letters on the owner's AI keys, and HOW that spend is bounded.
> Do not lift the limits "because the month is quiet", and do not move the check after the
> model call: the whole point is that the refusal costs nothing. Moving to paid packs has
> explicit triggers below; until they are all true, the owner pays.

---

## Context

ADR-004 made every user bring their own AI key, except the single CV extraction at sign-up
(owner-paid, one per user, 5 EUR monthly cap). In practice the invited users are people the
owner knows, and asking them to create an Anthropic account and paste a key before they can
see one CV is the largest drop-off of the whole flow. The owner decided (11 Oct 2026) to pay
for their generations for now, with limits that make the worst month a known number.

## Decision

1. **Owner-paid, bounded in two places.**
   - **Per-user quota:** 8 "applications" per UTC calendar month. A tailored CV costs 0.7
     units and a cover letter 0.3, so a CV plus its letter is exactly 1.
   - **Global hard cap:** 20 EUR per UTC month across ALL users, separate from the 5 EUR
     extraction cap (its own table, its own advisory lock).
   - Defaults, overridable by env: `CUOTA_SOLICITUDES_MES=8`, `CUOTA_UNIDADES_CV=0.7`,
     `CUOTA_UNIDADES_CARTA=0.3`, `TOPE_GENERACION_EUR=20`.
2. **Block before any model.** `cuota.generar` reserves first, in one transaction under a
   Postgres advisory lock (so two concurrent requests cannot jointly pass either limit), and
   only then calls the model. Order: quota, then cap.
3. **Pessimistic reservation, honest close.** The reservation holds the worst case: the
   prompt at 3 characters per token plus the call's `max_tokens` at the primary price, PLUS
   the whole fallback cascade of `call_llm_calidad` (Groq, Gemini, Claude, each at 4096
   output tokens), times a 1.25 margin. A successful call closes with the real cost from the
   usage `llm.py` attaches (the estimate when the provider reported none). A crash leaves the
   row `reservada`, which over-counts and never under-counts.
4. **Refunds in units, not in euros.** A failed generation (the call raised) gives the
   user's units back, but its estimate keeps counting toward the cap, because the call may
   have been billed. Same rule as the extraction ledger.
5. **Refusals are structured.** HTTP **429** for both limits, body
   `{"ok": false, "error": "...", "motivo": "cuota" | "tope", "se_renueva": "YYYY-MM-01"}`;
   `se_renueva` is the first day of the next UTC month. 429 because the request is valid and
   the same one succeeds after that date; the caller (n8n, panel) branches on `motivo`. If the
   ledger itself cannot be read for an identified user the answer is **503**
   `motivo: "indisponible"`: it refuses rather than spend unmetered. A provider failure keeps
   answering what it answered before (503).
6. **Who is exempt.** The owner and anybody else who must never be counted or blocked:
   - no `DATABASE_URL` (legacy mode): the quota logic is skipped entirely, no database access;
   - an email in `CUOTA_EXENTAS` (comma-separated), or any mailbox of a user who has one of
     them, for the day the owner has a Neon row too;
   - a mailbox with no Neon user: her legacy flow (user in Notion, master in Drive) is
     byte for byte what it was.
   If the mailbox lookup itself fails, the call goes through as legacy (like the master
   source does); this is bounded by the Anthropic console limit below.
7. **Alarm.** When the month's generation spend reaches 70 % of the cap
   (`AVISO_GASTO_UMBRAL`), ONE mail per month goes to `AVISO_GASTO_EMAIL` through Brevo
   (`BREVO_API_KEY`, `BREVO_REMITENTE`). A marker row in `avisos_gasto` is inserted in the same
   savepoint as the send, so concurrent requests send once and a failed send releases the
   marker for a later retry. A failure logs the exception type only and never blocks a
   generation.
8. **Panel state.** `GET /yo` returns `cuota: {usadas, limite, se_renueva}` (units with one
   decimal) for Neon users, and omits it for exempt and legacy users. The panel reads `/yo`
   field by field, so an extra field breaks nothing.
9. **Demand signal.** `POST /interes {tipo: "paquetes" | "academia", organizacion?}` stores one
   row per user and kind (idempotent upsert, nothing but `organizacion`, 120 characters at
   most). Deleting the account deletes these rows (CASCADE). The generation ledger is the
   opposite: `usuario_id` is set to NULL on deletion so an account cannot reset the cap.
10. **Second layer outside the code.** Set a monthly spend limit on the Anthropic console key
    used by the generators. The code cap is an estimate; the console limit is the provider's
    own number.

## The numbers

- A tailored CV is about 0.02 EUR and a letter about 0.01 EUR on Sonnet (order of magnitude,
  from the `consumo` the routes log), so a full quota is roughly 0.25 EUR per user per month.
  20 EUR covers about 80 users who use all of it; the alarm fires at 14 EUR.
- The worst case of ONE reservation is a few tenths of a euro (primary plus the whole
  fallback cascade, with margin). That is what a failed call keeps counting.

## Triggers to move to paid packs

Move when ALL of these are true:

1. At least 30 % of the active users hit their quota two months in a row, AND
2. the global cap was exhausted two consecutive months, AND
3. there were at least 5 unsolicited requests (`POST /interes`, or by hand) for packs.

**B2B, by hand:** when an organisation asks for 10 seats or more, agree it directly; do not
build self-service for it. Until the triggers hold, the limits above stay.

## Consequences

- Worst month spend is bounded by the cap plus the in-flight reservations at the moment it
  closes (a few euros at most), not by the number of users.
- When the cap is exhausted everybody (except the exempt) is refused until the 1st; the
  refusal says so and gives the date.
- `CUOTA_EXENTAS` must contain the owner's mailbox before the database is enabled in
  production, or a database outage could refuse her flow.
- The estimate is conservative by design: a generation answered by the fallback providers
  (no usage reported) is closed at the full estimate.
- ADR-004 (`buscartrabajo` repo) must be amended: "Everything else remains BYOK" is no
  longer true for generation.
