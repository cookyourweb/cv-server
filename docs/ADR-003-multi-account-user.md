# ADR-003: One user, several email accounts

**Status:** Accepted · 28 Jul 2026
**Scope:** `cv-server`, `buscar_usuario_por_email`, Notion `Users` database

> **For whoever picks this up (person or AI):** if a second record of the same person
> shows up in `Users` again, do not "fix" it by copying fields by hand. Read the
> section "Why duplicating the record does not work": the patch breaks on its own.

---

## Context

The user receives job offers at **two mailboxes**: `principal@example.com` and
`alias@example.com`. `buscar_usuario_por_email` filtered the `Users` database by the
`Email` field with `equals`, so it only recognized one address.

The solution adopted at the time was to **create a second record** in `Users`,
with the other email. It worked: offers from both mailboxes found a user.

## The problem

**Two records of the same person drift apart.** This is not a hypothesis: it happened.

State when it was detected (28 Jul 2026):

| Field | `principal@example.com` | `alias@example.com` |
|---|---|---|
| `Name` | Persona Ejemplo | persona ejemplo |
| `Email CV` | cv@example.com | **empty** |
| `CV Master URL` | **8,702 chars, with `PERFIL BASE`** | **4,689 chars, WITHOUT `PERFIL BASE`** |
| `Ciudad` | Ciudad, Provincia | madrid |
| `Rol objetivo` | AI Engineer · Full-Stack · Tech Lead… | Senior Frontend Develo**p**er *(typo)* |
| `Perfil` | 3 lines (AI, RAG, agents) | "Senior frontend developer" |
| `Stack` | React, TS, Vue, Node, Python, AI/ML… | only "React Typescript" |

The CV of an IT services company was generated against the second record. Consequences, all
in the document a recruiter sees:

1. Header with `madrid` and `alias@example.com`.
2. Headline `Tech Lead Full Stack | Java · Angular · APIs REST | Arquitectura de
   Microservicios`: **the literal job title**. Pure echo, forbidden by the
   HEADLINE RULES.
3. Technologies foreign to the good Master (Maven, Oracle Cloud).

**And the headline guardrail did not fire.** Not because of a bug: that Master has no
`PERFIL BASE` block, so there was no contract to validate against. A guardrail that
depends on a piece of data only protects when the data exists.

## Why duplicating the record does not work

Duplication is a patch with an expiry date that nobody sees coming: **it works
the day it is created and degrades silently**. Every time the Master, the
profile or the stack is refined, ONE record is touched. The other falls behind, and there is no warning
until an offer comes in through the wrong mailbox and a CV comes out with the identity of
another person.

The domain model is clear: **the person is ONE. What there are is several entry
addresses.** One record per mailbox confuses the identity with the channel.

## Decision

**A user record can declare N addresses.**

- `Email` (email) remains the **primary** address. It does not change.
- **`Emails alias`** (rich_text, NEW): additional addresses, separated by comma,
  semicolon or line break.

`buscar_usuario_por_email` makes **two passes**:

1. `Email equals <email>`: fast path, the usual behavior.
2. If there is no result: `Emails alias contains <email>`, and **verify the exact
   match in Python**.

### Why the Python verification is not optional

Notion's `contains` filter is a **substring** match: `vero@gmail.com` matches
`notvero@gmail.com`. Without the final verification, a user could receive another
user's CV. Covered by `test_no_coincide_por_subcadena`.

### Pure functions

- `emails_de_usuario(props) -> set[str]`: all the addresses, normalized to
  lowercase and without spaces. It discards anything that does not look like an email, so that a stray
  note in the field ("(el viejo)", meaning "the old one") does not turn into an address.
- `usuario_tiene_email(props, email) -> bool`: exact comparison.

Both are pure and testable without touching Notion (15 tests in
`test_usuario_multicuenta.py`).

## Consequences

- **In favor:** a single place to maintain the Master, profile, stack and city. Adding a
  mailbox means writing one more email in a field, not cloning a record.
- **Cost:** a second Notion query when the email is not the primary one. Only in
  that case; the usual path is still a single call.
- **Backward compatible:** if the `Emails alias` field does not exist, the second pass
  returns 400, it is logged and the function behaves as before.

## Migration (manual, in Notion)

1. In `Users`, add the property **`Emails alias`** of type **Text**.
2. In the good record (`Persona Ejemplo` / `principal@example.com`),
   put in `Emails alias`: `alias@example.com`
3. In the offers whose `Usuario` field points to the duplicated record, repoint them to the
   good one.
4. **Deactivate** (`Activo` = off) the record `persona ejemplo` / `alias@example.com`.
   Deactivate before deleting: if any historical offer references it, the relation
   does not break.
5. Verify: `POST /generar-cv` with `email: alias@example.com` must return a CV
   with the header of `Persona Ejemplo` and `cv@example.com`.

## Pending

- [ ] Step 3 of the migration is not automated. If many offers show up
      pointing to the old record, it deserves a script.
- [ ] No guardrail warns that a Master **has no `PERFIL BASE` block**. That is what
      let the echoed headline through. A warning when reading the Master would cover it, and it is
      independent of the model and of this ADR.

---

**Related:** `ADR-002-cv-model.md`, `MULTI-USER-ONBOARDING.md`,
`test_usuario_multicuenta.py`.
