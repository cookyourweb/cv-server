# ADR-011: The semantic fit score measures topic affinity, never requirements, and never sends an invited user's profile to Gemini

**Status:** Accepted · 18 Oct 2026
**Scope:** `cv-server`, modules `encaje_semantico.py`, `embeddings.py`, `vectores.py`, `puntuacion.py`, migration `0003_embeddings`, route `POST /puntuar-ofertas`, Notion properties `Encaje`, `Avisos` (Ofertas) and `Evitar` (Usuarios)

> **For whoever picks this up (person or AI):** this document fixes WHAT the `Encaje` number
> means, WHO may have their text embedded, and WHY nothing is discarded automatically.
> Do not read `Encaje` as "can I apply" (that is ADR-009), do not add an invited user to the
> scored set without changing ADR-010 first, and do not turn a flag into a filter because the
> margins look clear: they are small.

---

## Decision

1. **Affinity, not requirements.** `Encaje` is `similarity(profile, offer) - similarity(avoid text, offer)`,
   times 1000 and rounded (+25, -13...), using Gemini embeddings and cosine. It answers
   "is this the kind of work she wants?". ADR-009's match answers a different question,
   "can she honestly apply?", with rules. The two never mix and neither feeds the other.
2. **An invited user's profile never goes to Gemini.** Only users exempt under ADR-010
   (`cuota.es_exenta`, i.e. `CUOTA_EXENTAS`, any of her mailboxes) are scored. Everybody else is
   counted as `saltadas` BEFORE any text is built, in line with `llm.call_llm_invitada`: the
   consent text of an invited user names Anthropic and Groq, not Google. The offer text is not
   personal data; the profile and the `Evitar` text are.
3. **Hard rules flag, they never discard.** `reglas_duras` adds `salario_bajo` and `ubicacion`
   to `Avisos`; an unparseable salary or location is "no data", never a reason. A near-identical
   stored offer (cosine >= 0.95) adds `posible_duplicada`. The offer is scored and kept in every case.
4. **Vectors live in pgvector, 768 dimensions.** Table `embeddings_oferta` (migration `0003`),
   HNSW index with cosine ops, one row per Notion offer page, scoped by `usuario_id`.
   768 because HNSW supports at most 2000 dimensions and it halves the storage of the default size.
   `huella` is the sha256 of the embedded text.
5. **Batch, not on creation.** n8n creates offers with its own Notion node, so scoring is a
   separate daily call to `POST /puntuar-ofertas` (machine key). It scores each exempt user's
   `Pendiente` offers with an empty `Encaje`, 100 at most, so a second run finds nothing.
   Profile, `Evitar` and offers travel in ONE embeddings call per user.
6. **Degrade, never block.** One failing offer (Gemini or Notion) is counted in `errores` and the
   batch goes on. Without `DATABASE_URL` or a Neon row for her, the offer is still scored and
   written to Notion, but no vector is stored and no duplicates are sought (`sin_vectores`).
   The route never creates a Neon account.
7. **Not used to sort the email yet.** First observe a few weeks of scores on real offers.

## Context

The experiment `scripts/experimento_embeddings.py` showed the score orders offers well
(frontend and full stack on top; ML, data and annotation at the bottom) but with thin margins
(about 0.025), and that an embedding does not see salary or location. Salary arrives as free
text ("$120k 150k", or empty), so an automatic discard would lose good offers.

## Consequences

- Production needs the extension `vector` on Neon, the Notion properties `Encaje` (number),
  `Avisos` (multi-select) and `Evitar` (text, Users), and a daily n8n call.
- A new exempt user enters the scored set only by being added to `CUOTA_EXENTAS`.
- The cost is one embeddings call per exempt user per run, in pennies.
- An offer whose text changes after scoring keeps its old `Encaje`; clear the property to rescore.
- The number is relative to one profile: compare scores of the same user, never across users.
