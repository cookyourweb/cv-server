# Google OAuth and the Drive token

**Status:** current · **Date:** 18 August 2026

This file exists because the same failure has hit three times (24 Jul, 11 Aug and
18 Aug) and each time it was diagnosed again from scratch. The missing piece was not
the mechanism: it was **which Google project**.

## The facts

| What | Value |
|---|---|
| Google project | `<id-del-proyecto>` (the project ID), project number `<numero-de-proyecto>` |
| How it was identified | CONFIRMED by Vero on 18 Aug 2026 in the Google console. Before that it was only an inference by elimination |
| Client used by Render | `cv-server-render-web`, type Web application, created on 2 May 2026, ID `<numero-de-proyecto>-<prefijo-web>...` |
| Other client in the project | `subirCv`, type Desktop, created on 9 Apr 2026, ID `<numero-de-proyecto>-<prefijo-escritorio>...`. It is NOT the Render one |
| How to tell them apart | By the characters after the hyphen in `GOOGLE_CLIENT_ID`: `<prefijo-web>` is the Render web client, `<prefijo-escritorio>` is the desktop one (the real prefixes are looked up in the Google console, they are not published here) |
| Requested scope | `https://www.googleapis.com/auth/drive` (full Drive, restricted category) |
| Where the credentials live | Render, service `cv-server`, Environment tab |
| Variables | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` |
| Deployed service | `https://cv-server-ggd8.onrender.com` |

**The other project, `n8n-asistente-correo`, is NOT this one.** That one belongs to the
email assistant, its client is of type Web with a redirect to n8n, and it is already
published in production.

## Why the token dies, with the quote

Google documentation, `developers.google.com/identity/protocols/oauth2`:

> A Google Cloud Platform project with an OAuth consent screen configured for an
> external user type and a publishing status of "Testing" is issued a refresh
> token expiring in 7 days, unless the only OAuth scopes requested are a subset
> of name, email address, and user profile

cv-server requests full Drive, which is not in that subset. Therefore, in Testing
mode **the token dies every seven days exactly**. The error that appears is
`invalid_grant: Token has been expired or revoked`.

The dates confirm it: token regenerated on 24 Jul, dead on 31 Jul, and nobody
noticed until 11 Aug because the system was stopped from 24 Jul to 5 Aug.
Regenerated on 11 Aug, dead on 18 Aug.

## The permanent fix, once

Publish the consent screen:

`console.cloud.google.com/auth/audience?project=<id-del-proyecto>` and click
PUBLISH APP.

Moving to "In production" removes the seven-day expiry. An unverified-app warning
appears, and it is irrelevant: Vero is the only user of her own
application and the unverified limit is 100 users.

## The architecture fix, when the time comes

Use a **service account** instead of user consent. A server
that reads a document with nobody in front of it should not depend on a
human consent. The CV Master is shared with the service account address
and its key is used. None of the seven expiry causes that Google
lists applies to a service account.

## Regenerating the token by hand: IT TAKES TWO STEPS

One alone is not enough, and this already failed on 11 Aug.

```bash
# 1. generar. Ojo: el venv es oculto y las dependencias no estan en el python del sistema
# (desde la raiz del repositorio cv-server)
.venv/bin/python scripts/regenera_token.py
# abre localhost:8080, se elige la cuenta dueña del Drive,
# guarda el token en .env y verifica que lee CV_MASTER_VERONICA_ES

# 2. llevarlo a produccion
#    Render > cv-server > Environment > GOOGLE_REFRESH_TOKEN, pegar y desplegar
```

In plain English, the commented steps are: 1. generate the token (note that the venv is
hidden and the dependencies are not in the system Python; run it from the root of the
`cv-server` repository). The script opens `localhost:8080`, you choose the account that
owns the Drive, and it saves the token in `.env` and verifies that it can read
`CV_MASTER_VERONICA_ES`. 2. Take it to production: in Render, go to cv-server >
Environment > `GOOGLE_REFRESH_TOKEN`, paste it and deploy.

Generating the token without pasting it into Render leaves the system exactly as broken.

## How to check whether it is alive

`/health` does NOT check Drive, so it is no use for this. The only real test is
to approve an offer in Notion and see whether the CV is generated, or to look at the payload of the
n8n Error Trigger in `execution.error.description`, which is where the useful
message is. The execution status shows `success` even if it failed.

## Log: 18 August 2026, resolved

1. Confirmed in the console that the project is `<id-del-proyecto>` and that the
   Render client is `cv-server-render-web`, type Web application.
2. **Published the app to production.**
3. Regenerated the token AFTER publishing, which is the order that matters.
   Verified by the script itself: `REFRESH OK` and `LEE EL MASTER:
   'CV_MASTER_VERONICA_ES'` (the script's own Spanish output: "reads the Master").
4. Pasted into Render and redeployed.

**This token no longer expires after seven days.** If it fails again, the cause is
another one and this document no longer explains it.

## Two traps in the procedure, for next time

**The consent URL can end up invisible.** If the script is launched without a
terminal, Python buffers the output and the link does not appear: it looks
hung when it is actually waiting on `localhost:8080`. Launch it with
`python -u` so the output comes out immediately.

And if a previous attempt was left running, the port is busy and the second attempt
collides. Check with:

```bash
lsof -nP -iTCP:8080 -sTCP:LISTEN
```

**The script prints the token in clear text** on the last line. If it is launched from a
tool that records the output, the token ends up written in that log. To
take it to Render without displaying it:

```bash
pbcopy < <(rg -o '^1//[A-Za-z0-9_-]+$' ruta/de/la/salida)
```

(`ruta/de/la/salida` means "path to the output file".)

Compare the length of the original with that of the clipboard before
pasting: an extra line break breaks authentication and the error Google gives
is the same `invalid_grant`, so it gets misdiagnosed.
