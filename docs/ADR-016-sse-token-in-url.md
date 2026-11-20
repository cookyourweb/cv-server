# ADR-016: Stop credentials travelling in the SSE URL

**Status:** Proposed (20 Nov 2026). The app change is NOT implemented. Only the ingress log
redaction is written (`infra/k8s/platform/ingress-nginx.values.yaml`), and it is not applied.
**Scope:** `GET /buscar-para-usuaria/progress` in `api.py`, ingress-nginx, uvicorn, Render

## Context

`EventSource` cannot send headers, so the panel opens
`/buscar-para-usuaria/progress?usuario_id=...&token=<credential>`. The route accepts two kinds of token:

1. **The panel user's Google ID token (JWT).** It is short-lived (about 1 h), but it is a bearer
   credential for every authenticated route while it lives.
2. **`CLAVE_MAQUINA`, the long-lived machine key.** It is compared in constant time, but it is
   still put in a URL.

Everything that logs a URL keeps it in plain text:

- the ingress-nginx access log (`"$request"` includes the query string), shipped to Cloud
  Logging because `WORKLOADS` logging is on;
- the uvicorn access log, on GKE (also shipped to Cloud Logging) and on Render;
- browser history and any proxy on the way.

So anyone with log read access holds a valid user token for up to an hour. If any caller ever
put `CLAVE_MAQUINA` in that URL, they hold a permanent key.

## Decision (proposed)

**A short-lived, single-use SSE ticket.**

1. `POST /buscar-para-usuaria/ticket`, authenticated with the normal `Authorization: Bearer`
   header (a header, so it is never logged). It returns `{"ticket": "<random 32 bytes, url-safe>",
   "expires_in": 30}` and stores `sha256(ticket)` with the user id, the allowed parameters and an
   expiry 30 seconds out.
2. The panel opens `EventSource(".../progress?ticket=<ticket>")`.
3. The route looks up the hash, checks expiry, **deletes it (single use)**, and takes the user
   from the ticket, never from the query. Storage: a table in Neon (both hosts share it). An
   in-process dict would break with 2 replicas, because the ticket and the stream can land on
   different pods.
4. Stop accepting `CLAVE_MAQUINA` and Google JWTs in the query string, after the panel has
   shipped the ticket flow.

A ticket that leaks to a log is useless: it has already been used, or it is about to expire,
and it only opens that one stream.

## Defence in depth (independent of the app change)

- **ingress-nginx logs `$uri` instead of `$request`** (no query string). Written, applied in
  runbook phase 4b. It covers the GKE edge only.
- **uvicorn:** add `--no-access-log` on GKE, or a log filter that drops `token=`. The ingress log
  then stays the only access log, already redacted. Render needs the same filter in its start command.
- **Rotate `CLAVE_MAQUINA`** if Cloud Logging or Render logs show it in a URL. Check by counting
  matches only, never printing them (runbook, phase 4b).

## Alternatives considered

| Option | Why not (alone) |
|---|---|
| Log redaction only | Removes one leak path. Browser history, Render and any other proxy still see the token. |
| Cookie-based session for SSE | Needs cookies across the panel and API domains, plus CSRF handling. Heavier than a ticket. |
| `fetch()` streaming instead of `EventSource` (headers allowed) | Valid. It changes the panel's reconnect logic. A good follow-up, but the ticket works with the current client. |

## Tracking

GitHub issue [#11](https://github.com/cookyourweb/cv-server/issues/11).
