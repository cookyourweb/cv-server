# ADR-002: The CV is written by Sonnet 4.6, not Haiku 4.5

**Status:** Accepted · 7 Oct 2026 (proposed on 27 Jul 2026; production writes the CV with `claude-sonnet-4-6`, verifiable at `/health`, field `modelos`)
**Scope:** `cv-server`, environment variable `CV_MODEL`
**Supersedes:** the cost note of `ADR-001` ("Cost note" section)

> **For whoever picks this up (person or AI):** this document fixes WHY the CV is
> generated with Sonnet and not with Haiku. If you are about to downgrade the model again to save cost,
> read the "The numbers" and "Evidence" sections first.

---

## Context

From the start, `CV_MODEL=claude-haiku-4-5` and `CARTA_MODEL=claude-sonnet-4-6`.
The choice was **deliberate and is documented**:

- `CHANGELOG.md`: *"Adapted CV (`/generar-cv`): Claude Haiku 4.5 (`CV_MODEL`), **cheap and obedient**."*
- `ADR-001`: *"on purpose, for cost... **the difference is small; if CV quality ever matters more, the jump is cheap**."*

In other words: **the critical document (the CV) is written by the small model, and the
secondary document (the cover letter) is written by the big one.** It is inverted.

## The problem

The `/generar-cv` prompt has **~68 distinct directives** (~1,650 tokens of rules
alone), plus the CV Master (~2,200 tokens), plus the offer description. Haiku 4.5
follows most of them and **skips a few, non-deterministically**.

### Evidence (27 Jul 2026)

The rules that were broken **were already written in the prompt**. No rule is missing:

| Prompt rule | Where it is | How it was broken |
|---|---|---|
| Ban on vague quantifiers ("millions of", "thousands of") | `PROMPT_CV`, rule 4bis (PROHIBICIÓN DE CIFRAS, the figures ban) | Malwarebytes CV: *"platform handling **millions of transactions**"* |
| Write the ACTION, never the attributed effect | `PROMPT_CV`, style block (Escribe la ACCIÓN) | Revolut: *"reducing manual effort and error rates"*. Malwarebytes: *"improving operational efficiency"* |
| EVIDENCE RULE (only what the Master backs) | `PROMPT_CV`, rule 1 (REGLA DE EVIDENCIA) | Malwarebytes: *"I have **designed backend services**"*. The Master only says *"Integrated REST APIs and coordinated data contracts **with** the backend team"* |
| The headline is a real identity, not the job title | HEADLINE RULES | With the title `Senior Product Engineer (Fullstack)` the headline came out duplicated and with the job title inside; with `Applied AI Engineer` it came out perfect **in the same commit** |

**The last case is the diagnosis:** same code, same commit in PROD, different results
depending on the input job title. A code bug ALWAYS fails the same way. This fails
DIFFERENTLY each time, which is the signature of a small model saturated by the number of
simultaneous constraints.

**Corollary:** adding more rules to the prompt makes the problem WORSE. It would mean asking a
model that is already saturated to hold 75 constraints instead of 68.

## The numbers

**MEASURED, not estimated** (27 Jul 2026, `POST /v1/messages/count_tokens` with the real
prompt: rules + EN CV Master + a Remotive offer; 13,816 characters):

| Model | Price ($/1M in-out) | Tokens in | $/CV | **40 CVs/month** | vs Haiku |
|---|---|---|---|---|---|
| Haiku 4.5 (current) | 1 / 5 | 3,532 | $0.0117 | **$0.47** | n/a |
| **Sonnet 4.6 (proposed)** | 3 / 15 | 3,532 | $0.0352 | **$1.41** | **+$0.94** |
| Sonnet 5 (intro until 31 Aug 2026) | 2 / 10 | **5,313** | $0.0353 | $1.41 | +$0.94 |

**The real extra cost is $0.94 a month. Less than one euro. Eleven dollars a year.**

> **Update 2 Oct 2026:** with the current prompt (about 9,600 input tokens) a CV
> with claude-sonnet-4-6 costs about 0.05 USD and a cover letter about 0.013 USD (measured on
> 2 Oct 2026). The table above is the historical measurement of 27 Jul with a prompt of
> 3,532 tokens. Monthly estimate with the new cost (CV plus cover letter per offer, about 0.063
> USD): 20 offers a month are about 1.3 USD and 60 offers a month about 3.8 USD (estimate
> of 2 Oct 2026).

> An earlier estimate in this ADR said $0.019/CV with Haiku and ~1.50 EUR/month of
> extra cost. It was **inflated by 70%**: it overestimated the prompt. The numbers
> above come from the token-counting API, not from a back-of-the-envelope calculation.

**Finding that reinforces decision 3 (do not move to Sonnet 5):** Sonnet 5 counts **5,313
tokens where Haiku and Sonnet 4.6 count 3,532**, 50% more for the SAME text,
because it has a new tokenizer. Its lower introductory price ($2/$10 versus
$3/$15) is eaten up entirely: the cost per CV comes out practically identical to Sonnet
4.6 ($0.0353 vs $0.0352). There is no saving, and there is a truncation risk from adaptive
thinking. The decision to stay on Sonnet 4.6 holds for two independent reasons.

The CV is the only artifact a recruiter sees. An invented technology or a false figure
does not cost $0.94: it costs the whole process, and it is indefensible in the interview.

## Decisions

1. **`CV_MODEL=claude-sonnet-4-6`.** It is an environment variable on Render: no code
   change, no deploy, reversible in 30 seconds.
2. **The prompt is NOT touched in the same change.** First the model variable is isolated. If
   the failures disappear with Sonnet, the prompt was fine all along. Only if they
   persist is the prompt touched.
3. **We do NOT move to Sonnet 5 yet**, even though today it is better AND cheaper than Sonnet 4.6
   because of the introductory price. Reason: Sonnet 5 has **adaptive thinking enabled by
   default**, and thinking consumes from the same `max_tokens` as the response. With
   `max_tokens=4096` the CV could be truncated. It requires raising `max_tokens` or passing
   `thinking: {"type": "disabled"}`, and that is already a code change.

### Why the change is safe

`call_claude()` (`llm.py`) sends **only** `model`, `max_tokens` and
`messages`. It does not pass `temperature`, `top_p`, `top_k` or `thinking`. Those are exactly the
parameters that break (400) when moving up a model. **There is no API incompatibility
between Haiku 4.5 and Sonnet 4.6 in this code.**

## Consequences

- **In favor:** a model with ample capacity for 68 simultaneous directives; fewer
  manual corrections; less risk of invention in the document the recruiter sees.
- **Cost:** +$0.94/month in the 27 Jul measurement (40 CVs, 3,532-token prompt). The
  ~1.50 EUR figure from the first estimate was discarded (see above). With the current
  prompt, see the 2 Oct 2026 update.
- **Controlled risk:** it is an environment variable. If it does not improve things, it is reverted
  instantly and the diagnosis becomes the prompt's, not the model's.

## How to verify

1. Change `CV_MODEL` on Render to `claude-sonnet-4-6`.
2. Approve in Notion **one** offer with a full description (Tecnoempleo or Remotive,
   not LinkedIn or Indeed: those bring 172-245 characters and there is no material to adapt).
3. Download the generated CV and run it through the checklist in
   `buscartrabajo/docs/runbooks/09-RUNBOOK-DIRECT-CONTACT-OFFER-2026-07-23.md`, plus these four
   specific cases, which are the ones that failed with Haiku:
   - unsupported vague quantifiers ("millions of", "thousands of")
   - benefit tag-lines without a metric ("improving X", "reducing Y")
   - claims about role scope not backed by the Master ("designed backend
     services", "led X across distributed systems")
   - a duplicated headline or one with the job title inside
4. Compare against the raw reference CV of 25 Jul (the Malwarebytes one),
   which is the base case with Haiku.

## Pending

- [x] Change `CV_MODEL` on Render to `claude-sonnet-4-6`. Done; verified on
      7 Oct 2026 with `GET /health`.
- [ ] Control comparison against the four Haiku failures (list above). Pending:
      there is no evidence in the repo that it was done.
- [ ] **Known debt: the default value of `CV_MODEL` in `llm.py` is still
      `claude-haiku-4-5`.** Production sets Sonnet through an environment variable; if the variable
      is lost, the CV falls back to Haiku without any error. A separate change, with tests, will move the
      default value.
- [ ] If failures keep appearing with Sonnet, THEN touch the prompt.
- [ ] **Extend the guardrail to ROLE claims.** Today it detects technologies
      (`tecnologias_no_respaldadas`) and figures (`cifras_no_respaldadas`), both by
      text match against the Master. It does not detect "designed backend services",
      which is semantic. It is the real hole in the guardrails, independent of the model.
- [ ] Evaluate Sonnet 5 when `max_tokens` can be touched (better and, until
      31 Aug 2026, cheaper than Sonnet 4.6).

---

**Related:** `ADR-001-fastapi-migration.md` ("Cost note" section),
`CHANGELOG.md`, `buscartrabajo/docs/runbooks/09-RUNBOOK-DIRECT-CONTACT-OFFER-2026-07-23.md`.
