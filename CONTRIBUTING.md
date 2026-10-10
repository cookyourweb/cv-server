# How we work in this repository

This is not a manual of good intentions: it is what this repository **requires**, and
part of it is checked by git itself before it lets you commit.

## Enable it, once per clone

```bash
git config core.hooksPath scripts/hooks
```

From then on, every `git commit` runs the suite. If it is red, there is no commit.

---

## The cycle: red, green, commit

**The failing test first. Always.**

If you have never seen a test fail, you do not know whether it tests anything. Writing it after the
code only proves that the code does what it does.

```
1. Write the test that describes the failure or the missing behavior
2. Run it and WATCH it go red. Read the message: does it say what you want it to say?
3. Write the minimum code that turns it green
4. Run the WHOLE suite, not just your test
5. Commit
```

Step 2 is not ceremony. On 28 Aug 2026 a test written here passed on the first run
while the code was wrong: it compared with `not in` and the substring it was looking for
was contained in the correct form. Seeing it red first is what exposes that.

## Where the tests live

In `tests/`, at the root of the repository. Not next to the code they test.

It is the convention already used in the osapiens technical test, and here it was adopted
on 28 Aug 2026 by moving 23 test files out of the root. The move exposed two
tests that depended on being physically next to the source they read: a
dependency nobody knew existed because they had never been moved.

## Language: commits and comments in English

Since 8 October 2026. The repository is public and read by companies from
abroad, so what is written from now on goes in English:

- **Commit messages and PR descriptions, in English.** They are the first thing read
  in the history. The conventional format is kept (`fix:`, `feat:`...) and so is
  the rule of explaining the why.
- **Comments in new code, or in code you touch, in English.**
- **Domain names stay in Spanish** (`Oferta`, `Candidatura`,
  `autenticacion`, `ClavesPublicas`...). They are the language of the business, a
  job search in Spain, and the code uses the same words (ubiquitous
  language). They are not renamed.
- **Old comments are not translated all at once:** they move to English when that file
  is touched. Translating everything at once fills the history with noise.
- **Documentation stays bilingual:** `README.md` in English and `README.es.md` in
  Spanish, with the same facts.

## One commit, one unit of work

A commit has to be explainable in one sentence and revertible without dragging
anything else along. If the message needs an "and also", it is two commits.

Tests travel **with** the code they test, in the same commit. A commit that
adds behavior without its test is incomplete.

## The message says WHY, not what

The "what" is already in the diff. What gets lost is the why, and that is what is needed
six months from now.

[Conventional](https://www.conventionalcommits.org/) format: `fix:`, `feat:`,
`refactor:`, `docs:`, `test:`, `chore:`, `ci:`.

**`test:` is for commits that are ONLY tests**, and it is worth telling apart two things
that are not the same:

```
test: add test suite with TDD for input validation   <- the test came first
test: add missing tests for the happy path           <- filling a gap afterwards
```

Both are legitimate, but they are not equal, and the message has to say which one it is.
Calling gap-filling TDD is fooling yourself six months from now.

```
fix(guardrails): `_tecnologias_en` was defined twice and the bad one won

Measured over the 519 combinations of the catalog, they differ in 9, all with
MULTI-word technologies, where the middle space is not a word character:

  "react native"  =>  {React Native}          correct
                  =>  {React, React Native}   naive, it invents React
```

When there is a number, the number goes in. "Improves performance" says nothing;
"from 22 seconds to 3" does.

## Tests follow the code

If you move a function to another module, the tests that look at it are updated **in the
same commit**. And watch out for this, it bites:

```python
# This NO LONGER patches anything if `call_llm_calidad` lives in another module:
patch.object(servidor, "call_claude", ...)

# You have to point to where the function LIVES, not where it is re-exported:
patch.object(llm, "call_claude", ...)
```

## A test is never touched just to make it pass

A test is touched when **what it tests** has changed, or when it looks at
internal details that have moved. Never to cover up a failure.

The difference is what separates a refactor from a wreck: during the split of
`server.py` into six modules, all 175 tests passed without a single one being relaxed.

## Before calling something done

- The whole suite green, not just your part
- CI green on GitHub
- If you touched something that gets deployed, check it **in production**, not on your machine

The last one is not paranoia. On that same day a fix was green locally for
hours while production kept serving the previous day's code.

---

## What the machine checks and what it does not

| | Who |
|---|---|
| The suite green before committing | The `scripts/hooks/pre-commit` hook |
| The suite green on every push and PR | GitHub Actions |
| Retired models, once a week | CI cron, Monday 06:00Z |
| One commit per unit of work | You |
| The message that says why | You |
| Seeing the test red before fixing it | You |

The last three cannot be automated. That is why they are written down.
