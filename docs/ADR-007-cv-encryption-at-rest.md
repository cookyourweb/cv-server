# ADR-007: CV masters are encrypted at rest by the application

**Status:** Accepted · 9 Oct 2026
**Scope:** `cv-server`, module `cifrado.py`, environment variables `CV_CLAVES` and `CV_CLAVE_ACTIVA`

> **For whoever picks this up (person or AI):** this document fixes WHY the CV text
> stored for new users is encrypted by the application with AES-256-GCM and
> a key that never touches the database. Do not replace it with "the provider
> already encrypts the disk": that protects against a stolen disk, not against
> someone who can read the database.

---

## Context

The "sign up with your CV" flow (change `alta-con-cv`) stores the text of each
user's CV (the CV Master) in Neon. It is personal data about third parties. The
threats that matter are a leaked backup or dump, a compromised database credential
and a bug that returns another user's row. Disk encryption at the provider covers
none of them: whoever can run a `SELECT` reads plain text.

## Decision

1. **Algorithm:** AES-256-GCM through the `cryptography` library. Authenticated
   encryption: tampering is detected, not just hidden.
2. **AAD (additional authenticated data):** `cv_master:{usuario_id}:{idioma}`.
   The ciphertext is bound to its owner and language. A row copied to another user
   or language fails to authenticate. This is why Fernet was discarded: it has no AAD,
   so rows would be swappable between users.
3. **Stored row:** `(clave_version, nonce, cifrado)`. The nonce is 12 random bytes
   per encryption (a database CHECK enforces the length). The raw uploaded file is
   never persisted, only the extracted text, encrypted.
4. **Keyring outside the database:** environment `CV_CLAVES="1:<b64>,2:<b64>"`
   (32 random bytes each, base64) and `CV_CLAVE_ACTIVA="2"`. The key lives
   where the service runs (Render), never in Neon: a database leak alone is useless.
5. **Rotation:** add a new version, make it active, then re-encrypt rows with
   `cifrado.recifrar` (a script wraps it once the database layer exists). Old
   versions keep decrypting until the last row is migrated; only then remove them.
6. **Fail closed:** a missing or malformed keyring, an inactive version that
   is not in the ring, an unknown row version, a wrong nonce length or any failed
   authentication raises `ErrorDeCifrado`. There is no plain-text fallback.
7. **Errors carry nothing:** messages are generic and chained exceptions are
   suppressed, so neither content, ids nor key material reach logs.

## Consequences

- Losing every copy of a key makes the rows encrypted with it unrecoverable. The
  keyring must be backed up separately from the database backups (ADR-008).
- A leaked key plus a leaked dump exposes the CVs; the two live in different
  systems on purpose.
- Encrypted text cannot be searched in SQL. Nothing needs it: the master is read
  whole, for one user, at generation time.
- Cost: one decryption per read, negligible next to the LLM call.

## How to verify

`tests/test_cifrado.py`: round trip, AAD mismatch (other user or language), old key
version still decrypts, tampered nonce or ciphertext, wrong nonce length, missing
or malformed key configuration, and errors that never contain the content.

## Pending

- `scripts/recifrar.py` (database-backed rotation) arrives with the database layer (C1).
- Document where the production keyring is backed up (outside Neon and outside Render).
