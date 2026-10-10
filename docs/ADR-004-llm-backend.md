# ADR-004: LiteLLM is written and left switched off, not adopted

**Status:** Accepted · 29 Aug 2026
**Scope:** `cv-server`, module `llm.py`, environment variable `LLM_BACKEND`

> **For whoever picks this up (person or AI):** this document fixes WHY the LLM
> cascade is still three `requests` calls instead of LiteLLM, even though the
> LiteLLM adapter is already written and tested in the repo. If you are going to switch it on, read
> the "The numbers" section first. It was not rejected out of ignorance: it was measured.

---

## Context

`llm.py` resolves the Groq, Gemini and Claude cascade with three hand-written
`requests` blocks, about sixty lines. Each block has its own URL, its own way of extracting
the text from a response with a different shape, and its own `try/except`.

That has cost real money twice:

- **16 Aug 2026:** Groq retired `llama-3.3-70b-versatile`. The job search went ten
  days without bringing in a single offer.
- **28 Aug 2026:** **three models were retired in one day** (Groq, and two from Gemini).
- **28 Aug 2026:** when `llm.py` was extracted from the monolith, the `import anthropic` was left
  behind. The quality layer died and **the CVs that were sent were written by the fallback**
  for a whole day without anyone noticing.

All three are the same underlying problem: **hand-maintaining the integration with
several providers is recurring work and its failures are silent.**

[LiteLLM](https://github.com/BerriAI/litellm) is the standard answer in the industry:
a single call, normalized model names, `fallbacks` out of the box, and a
library that tracks provider changes for you.

## The problem

LiteLLM is not free. Measured in this same repo, with version `1.98.0` installed
in the `cv-server` venv:

## The numbers

| | home-made cascade | with LiteLLM |
|---|---|---|
| New dependencies | 0 | litellm, openai, tokenizers, tiktoken |
| Disk | 0 MB | **+146 MB** (litellm 114, openai 20, tokenizers 8.8, tiktoken 3) |
| Module `import` | immediate | **+5.96 s** |
| Process RAM | 9 MB | **207 MB** |

How they were measured, so that they can be repeated:

```bash
.venv/bin/python -c "from importlib.metadata import version; print(version('litellm'))"
du -sh .venv/lib/python3.14/site-packages/litellm
.venv/bin/python -c "
import os, resource, time
def mb(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024*1024)
base, t = mb(), time.time()
import litellm
print(f'{time.time()-t:.2f}s   {base:.0f} MB a {mb():.0f} MB')
"
```

**Multiplying the process memory by 23 and adding six seconds to the cold start, to
replace sixty lines that work, is not something this service pays for today.**
It is a small web server, and a timeout was already fixed on 28 August because a
request took 10.7 seconds against a limit of 8.

## Decision

**The adapter is written, tested and documented. It is left SWITCHED OFF.**

1. `llm.py` defines a `Protocol` called `BackendLLM` with two implementations:
   `CascadaCasera` (default) and `CascadaLiteLLM`.
2. It is chosen with the environment variable `LLM_BACKEND`. An unknown value raises
   `ValueError` and does not silently degrade to another backend.
3. **The `import litellm` lives INSIDE the method**, never at the top of the module.
   As long as nobody switches the backend on, the process does not pay a single byte.
4. `litellm` is **not in `requirements.txt`**. It lives in
   `requirements-litellm.txt`, which is only installed if it is going to be switched on.

The contract in point 3 does not depend on the goodwill of whoever edits the file:
it is guarded by `tests/test_backend_llm.py::test_importar_llm_no_carga_litellm`, which
starts a clean process and checks that `import llm` does not put `litellm` in
`sys.modules`.

## When to switch it on

When **any** of these holds:

- The hosting plan no longer has tight memory, or the service stops
  suffering cold starts.
- A fourth provider appears. From then on, the cost of maintaining the cascade by
  hand grows faster than that of the library.
- Something is needed that the home-made version does not give and LiteLLM does: per-call
  cost accounting, retries with backoff, or budget-based routing.

Switching it on is `pip install -r requirements-litellm.txt`, setting
`LLM_BACKEND=litellm` and restarting. Not a single line of code.

## Consequences

**In favor**

- The cost of the decision is measured and written down, not guessed.
- Changing backend stops being a refactor and becomes a variable.
- The adapter is tested today, so the day it is switched on it is not a premiere.
- Second place in the repo where the open/closed principle is really applied,
  after the guardrails registry.

**Against**

- There are two paths to maintain instead of one. It is accepted because the second is
  fifteen lines and is covered by tests.
- The switched-off backend is tested against a `litellm` double, not against the real
  library. The day it is switched on, a real call must be made before
  trusting it.

## See also

- `llm.py`, docstring of `BackendLLM` (the three ways to break the contract)
- `tests/test_backend_llm.py`
- `tests/test_capa_calidad.py` (the `import` that was missing and why the fallback covered it up)
- `ADR-002` (why Sonnet writes the CV)
