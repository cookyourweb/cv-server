# ADR-009: The offer match is rule based, and an offer is yours only if Notion says so

**Status:** Accepted · 11 Oct 2026
**Scope:** `cv-server`, modules `match.py` and `rutas_encaje.py`, `notion.py` (offer reads), routes `GET /ofertas/{id}/encaje` and `POST /encajes`

> **For whoever picks this up (person or AI):** this document fixes WHY the "does this
> offer fit me" answer is computed by plain rules and not by a model, and WHO may ask
> about which offer. Do not "improve" the match by sending the CV to an LLM: the whole
> point is that it is free, repeatable and cannot invent a skill. Do not relax the
> ownership rule to "any offer id works": offers are keyed by Notion page ids, which are
> not secrets.

---

## Context

The panel shows, per offer, whether the candidate can honestly apply. The generators
(CV and letter) are expensive and are guarded against invention (ADR-002, guardrails);
a match built on the same model would be paid per click and could flatter the candidate.
The offers live in Notion (n8n writes them), each with a "Usuario" relation to the
Notion page of the user it was found for. Until now nothing read an offer on behalf of a
signed-in user, so there was no rule for which offers she may see.

## Decision

1. **Rule based, no model.** `match.evaluar(oferta, perfil, master)` is pure: no I/O,
   network, clock or LLM (enforced by `tests/test_match.py`). A technology is covered only
   if the master names it (registry of `guardrails`, word boundaries). Years of
   experience, language and work mode can be eliminatory gaps. Soft skills and anything
   unknown are `no_evaluables`, never guessed. It is reachable when no gap is eliminatory,
   coverage is at least 0.6 and at most two technologies are missing.
2. **Never feeds the generators.** Only `real_jobs` and `rutas_encaje` import `match`
   (`test_REQ_6_3_match_never_reaches_the_generators`).
3. **Two routes**, both behind the panel's Google token (`@con_usuaria`, 401 without it):
   `GET /ofertas/{id}/encaje` and `POST /encajes {"ids": [...]}` (at most 50 ids, 51 is
   422). The batch answers a flat object keyed by the id exactly as the caller sent it,
   `{"<id>": {"alcanzable", "cobertura"}}`: the summary only, with no requirements, gaps or
   evidence on the wire. Ids that are not hers are omitted, `{"ids": []}` is `{}`, and if the
   same offer is sent in two spellings it is answered once, under the first one.
4. **Ownership rule.** An offer belongs to the caller only if its Notion "Usuario"
   relation contains the caller's Notion page id. That page is found by her verified email
   with the existing `buscar_usuario_por_email` (main address or alias, active users only).
   Ids are compared normalised (32 hex characters), and the page must live in the offers
   database (`NOTION_DB_OFERTAS`) and not be archived.
5. **No existence oracle.** An offer that is somebody else's, nobody's (**an offer with no
   "Usuario" is nobody's, so no user can see its match**), in another database, archived,
   missing or with a malformed id gets the SAME `404 {"ok": false, "error": "no
   encontrado"}`. In the batch those ids are silently omitted; there are no per-id errors.
   A caller with no Notion record owns nothing (404 / empty batch).
6. **Fail closed.** If Notion is unconfigured, unreachable, rate limited twice, or answers
   something unexpected, the answer is a generic `503` with no detail, never a guess and
   never a partial batch. Same for a failing database or master source.
7. **Profile and master.** The profile is her own row (`RepositorioDeUsuaria`). The master
   comes from `fuente_master.resolver_master`, so a master stored in Neon is read only with
   the `enviar_cv_a_ia` consent (ADR-007 / C9) even though no model is called here; the legacy
   Drive master keeps working. It is read once per language of the offers, not per offer.
   **With neither a profile nor a master the answer is `409`** with `motivo:
   "sin_perfil_ni_master"` (not 422: the request is valid, the account state is what
   conflicts). With only one of them the match runs; with no master nothing is covered,
   which is what the rules mean by "not evidenced". The 409 is decided AFTER ownership, so
   a stranger's id is still a 404.
8. **Nothing but the match goes out.** The response holds the requirement names and the
   short evidence snippets `match.py` builds (one master line, cut to 160 characters),
   never the master (REQ-6.5; tested with a canary sentence). Logs carry no email, id or CV
   text.
9. **How offers are fetched.** Notion cannot filter a query by page id, and a relation
   query would have to page through all her offers (unbounded). Each distinct id is read
   with `GET /pages/{id}` instead, 3 at a time (Notion averages 3 requests per second), with
   10 s timeouts and one retry on 429. A batch of 50 is therefore up to 50 Notion calls: the
   cap of 50 is what bounds it.

## Consequences

- Offers created without a user (n8n `/crear-oferta` without an email that matches a Notion
  user) cannot be matched by anyone. The fix is upstream: give them an owner.
- A large batch is slow (several seconds) and a Notion outage turns into a 503 for the
  panel, which should keep showing the offers without the match.
- A Notion lookup failure on the USER record cannot be told apart from "no such user"
  (`buscar_usuario_por_email` returns None for both), so it answers 404 rather than 503.
  Fail-closed, but misleading; fix it if it shows up in practice.
- `NOTION_DB_OFERTAS` must be set on Render before deploying this change (it no longer has
  a default in the code). See the pre-production checklist in the README.
- Matching quality is bounded by the technology registry in `guardrails`: a technology
  that is not in it is invisible to the match.
