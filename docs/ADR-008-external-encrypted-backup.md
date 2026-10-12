# ADR-008: Daily external backup, encrypted before it leaves the database host

**Status:** Accepted · 11 Oct 2026
**Scope:** `cv-server`, `.github/workflows/neon-backup.yml`, repository secrets `NEON_BACKUP_URL` and `AGE_PUBLIC_KEY`

> **For whoever picks this up (person or AI):** this document fixes WHY the database
> is backed up outside Neon with an encrypted dump, and why the dump is encrypted
> with a public key whose private half is not in this repository or in GitHub. Do not
> "simplify" it by uploading a plain dump: artifacts of a public repository are
> downloadable by any signed-in GitHub user.

---

## Context

Neon's free plan keeps a point-in-time restore window of only **6 hours**. A mistake
noticed the next morning (a bad migration, a deletion bug, a dropped table) cannot be
undone with it. Real users' profiles and encrypted CV masters will live in the
database, so we need a copy that survives that window and that does not depend on
Neon being the only holder of the data.

Constraints:

- No budget for a paid plan or a storage bucket; the repository is public and already
  uses GitHub Actions.
- Artifacts of workflows in a **public repository can be downloaded by any logged-in
  GitHub user**. Anything uploaded must be useless without a secret that GitHub does
  not hold.
- The CV text is already encrypted by the application (ADR-007), but the dump also
  holds emails, names and profiles in plain columns.

## Decision

1. **Where:** a scheduled GitHub Actions workflow (`neon-backup.yml`), daily at 03:17 UTC
   and on manual dispatch.
2. **How:** `pg_dump --format=custom --no-owner --no-privileges` run with the official
   `postgres:18` image, so the client major version matches the server (a mismatched
   `pg_dump` refuses to run). The connection string comes from the secret
   `NEON_BACKUP_URL`; a read-only database role is preferred.
3. **Encrypted before it exists as a file:** `pg_dump` streams into `age -r <public key>`.
   The plain dump is never written to the runner's disk. The recipient is the public key
   in the secret `AGE_PUBLIC_KEY`.
4. **Private key offline:** the `age` private key stays with the repository owner, outside
   GitHub, Render and Neon. Whoever can read the artifact cannot read the data.
5. **Only the `.age` file is uploaded**, as an artifact with **30-day retention**. The
   upload step fails if the file is missing, and the dump step fails if the file is
   suspiciously small.
6. **Fails loudly:** a missing secret stops the run with a clear `::error::` message
   before any connection is attempted. No step echoes a secret or traces the shell, and
   secrets are only bound to environment variables, never interpolated into commands.
7. **Least privilege:** the workflow has `contents: read` only and a 15-minute timeout.

## Consequences

- Recovery point is at most about 24 hours old, against Neon's 6 hours. Acceptable for the
  size and criticality of this data; the schedule can be tightened if that changes.
- **Losing the age private key makes every backup unreadable.** Keep two offline copies.
  The application keyring (ADR-007) is a different secret and needs its own backup:
  a restored dump is useless without it.
- GitHub may disable scheduled workflows in repositories with no activity for 60 days;
  a manual run or any push re-enables them. Check the Actions tab now and then.
- Secrets live in the repository settings, so anyone with admin access can change them;
  the workflow cannot be triggered from forks and receives no secrets on pull requests.
- A backup that was never restored is not a backup. Rehearse the restore (see the
  README) on a scratch Neon branch after the first run and after schema changes.

## How to verify

`tests/test_copia_neon.py` reads the workflow and pins: daily schedule plus manual
dispatch, both secrets read through `${{ secrets.* }}` and only bound to environment
variables, no command that prints them, the Postgres 18 client, `pg_dump | age` with no
plain file, a single upload path ending in `.dump.age`, 30-day retention and failure on a
missing file.
