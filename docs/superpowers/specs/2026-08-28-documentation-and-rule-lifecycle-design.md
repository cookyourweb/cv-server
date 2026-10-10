# Design: the lifecycle of a correction

**28 Aug 2026** · Status: proposed

This service generates a CV tailored to a job offer using an LLM. The person who
receives it corrects it by hand before sending it, and those corrections are where
rules come from.

This document decides what happens to those corrections.

---

## Success criterion

**The system works when the number of corrections goes down.** Not when it produces a
CV that reads well.

A correct document that has to be touched up every time is the current state, and the
current state is the problem. That gives the design its only metric: **corrections per
CV**.

---

## The problem, as it stands today

The adaptation rules exist and are written down. What does not exist is the link that
applies them: **a person copies them into the prompt by hand**.

```
Adaptation rule files
          |
          +-- a PERSON copies them into the prompt, by hand
```

The code does not read them. Every new rule depends on someone remembering to paste it.

### The diagnosis, which is not the obvious one

| Piece | State |
|---|---|
| **Capturing rules** | Solved. They are written down and validated against external feedback |
| **Applying them** | **Does not exist.** It depends on a manual copy |
| **Measuring whether they work** | **Does not exist.** There is no way to know whether fewer corrections are needed today than a month ago |

Rules are not missing. The link that applies them is.

---

## Section 1: a correction is not a rule

A correction is a **candidate**. It becomes a rule when it repeats.

Instinct says the opposite, which is why it is written down: if every correction became
a rule immediately, the prompt would fill up with one-off cases that contradict each
other, and quality would drop the more the system is used. The sign that a correction
generalises is that it was made more than once.

| State | What it is | Where it lives |
|---|---|---|
| Correction | What was changed in THIS document | Next to the offer |
| Candidate | A correction seen twice | A list awaiting review |
| Rule | Promoted by the person, enters the prompt | The rule files, which the code **now does** read |

**The metric**: corrections per CV. If it does not go down, the rules do not generalise
and the prompt is just getting fatter. It is the only figure that tells a system that
learns apart from one that merely accumulates.

---

## Section 2: two axes of rules, not one

Today a single person uses the system. The multi-account user design already exists
(see `ADR-003`), so the decision is made now to avoid rewriting it later.

| | System rules | User rules |
|---|---|---|
| Example | Do not invent figures that are not in the source document. Do not attribute years of experience to the wrong technology | Style and formatting preferences of each person |
| Whose? | Everyone's | One person's |
| Who changes them? | Whoever maintains the product | Each user, their own |
| Where they live | **In the repository**, versioned in git | **With the user's record** |

The system rules **already exist and work**: they are the six guardrails, in code and
with tests. That axis is solved.

The one that does not exist is the second. Today personal rules sit in files inside the
repository, which is exactly where another person's rules cannot live.

**The cheap decision that avoids rewriting everything**: user rules are stored from day
one tied to a user, even though there is only one today. Nothing multi-user is built.
The key is simply stored with the data.

The difference in adding it today: half an hour. In not adding it: rewriting the store
and migrating whatever was in it.

---

## Section 3: how a correction is captured

The two pure approaches both fail:

- **Infer it from the diff.** Zero friction, but the system cannot tell a typo from a
  judgement call. Junk rules.
- **Ask for it blank.** Clean signal, but nobody fills in an empty text box after
  correcting a document.

**The diff proposes, the person confirms:**

```
Generate the CV
     |
     v
They correct it by hand
     |
     v
The system detects WHAT changed and asks ONE thing:

  "You changed X to Y in the headline.
   Always, only for this kind of offer, or just this once?"

     [ Always ]  [ This kind only ]  [ Just this once ]
```

Three buttons, one question. No rule is written: **its scope is chosen**, which is the
one thing the system cannot guess, and is exactly the field that separates a global rule
from one limited to a kind of offer.

This is where the LLM earns its place: turning a messy diff into a readable sentence
that can be confirmed. It does not generate content, it **structures a human
observation**.

**Risk, written down on purpose**: asking on every document is tiring, and a tired
person presses "Always" on everything to make it go away. The system would poison
itself. That is why it only asks about changes that **have already repeated**: the
candidate is born from the diff, and the question appears the second time.

---

## Section 4: rules that contradict each other

When a new rule contradicts an existing one, **the new one wins and the old one is
marked as superseded, with the date and the rule that replaces it**. Just like an ADR.

Nothing is ever deleted. A deleted rule takes its reason with it, and three months
later nobody knows whether it was removed for a reason or by accident.

---

## Order of work

The order matters and is not the intuitive one:

1. **Make the code read the rule files.** The smallest change of all and the one with
   the most effect: from that day a written rule is an applied rule.
2. **Count corrections per CV.** Without a baseline, "this is getting better" is a
   feeling.
3. **The capture loop** (the diff proposes, the person confirms).

The loop comes third on purpose: once the rules apply themselves, it will be clear which
ones really reduce corrections. Without that data, the loop would collect rules without
knowing whether any of them helps.

---

## What is deliberately NOT done

- A generic rules engine
- A new database
- An admin panel for rules
- Rules shared between users

None of that is needed with one user, and every piece added today is one that has to be
maintained before anyone knows whether it is needed.

---

## Open questions

- **The rule files live in a different repository from the code that would read them.**
  A service cannot read files from a repository it does not deploy. Three ways out:
  1. **Move the rules into this repository**, next to the prompt that consumes them.
     The simplest.
  2. Leave them where they are and read them over HTTP. Adds a network dependency at
     startup, for nothing.
  3. Duplicate them. Ruled out: two copies of the same rule drift apart, which is the
     very disease this document exists to cure.

  Recommendation: option 1. It changes where the rules are edited every day, so it is
  for whoever writes them to decide.
- **How many repetitions promote a candidate to a rule.** The design says two. It is a
  chosen number, not a measured one. Revisit it once there is data on corrections per CV.
- **Where exactly the corrections baseline lives.** Next to the offer is the natural
  place, but it needs checking whether the schema can take it without getting messy.
