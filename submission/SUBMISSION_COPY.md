# Submission copy (lablab form)

Ready-to-paste text. Every claim here is backed by `submission/FACTORY_EVIDENCE_MAP.md`. I could not open the live lablab form from the review environment, so check each field's character limit when you paste.

---

## Project title

**Tablekeeper — Reservations that survive reality**

Shorter fallback if the field is tight: **Tablekeeper**

## Tagline

Reservations that survive reality.

## Very short description (one sentence)

A restaurant reservation system built for what happens after the booking, made by a four-seat Band Desktop factory that rejected and repaired its own work without human help.

## Short description (≈ 95 words)

Tablekeeper keeps a reservation's promise when the evening changes. A retry never creates a duplicate booking, a lost response recovers the original confirmation, and guests can see what happened to their deposit. Restaurants can rehearse a table closure on an exact seating planner before applying it. Four Claude Code seats in one Band Desktop room built all four stages from a single dispatch in 3 h 26 min. An independent verifier seat accepted every stage. Along the way it rejected a stage 2 build that scrolled sideways on phones, and the factory fixed it without human help.

## Long description

Most reservation systems stop at "find a table, book it". Then the evening goes wrong in ordinary ways. A confirmation is lost on a bad connection, two people tap the same table, or the restaurant changes its hours. A table breaks an hour before service, or a deposit is taken and nobody can say what happened to it. Tablekeeper is built around those moments.

**For guests, the promise is to protect the evening.**

- A booking is never duplicated by a retry, and a lost response recovers the original confirmation.
- A taken table keeps your form and refreshes the grid.
- Each booking keeps the terms it accepted, even after the restaurant publishes a new policy.
- *My Evening* turns the booking into a companion. It shows the table, a simulated deposit guarantee with a plain "What happened to my money?" timeline, a calendar file, the wishes the kitchen will see, and anything the restaurant changed.

**For restaurants, the promise is to recover the night.**

- When a table becomes unavailable, an exact planner re-seats every affected booking: fewest bookings moved, then fewest empty seats.
- The *Recovery Simulator* shows the bookings before the closure, the closure, the proposed repair and the messages guests would get. Nothing changes until the manager applies it.
- The *Control Room* shows the service day, how full each slot is and the guarantees held.

**How it was built.** Tablekeeper was built by a software factory in Band Desktop. It has four Claude Code seats: a coordinator, a developer, a product engineer and an independent verifier. Each seat has a generic mandate that describes how it works, not what to build. One dispatch started the judged run, and for the next 3 h 26 min only the seats wrote in the room. For each stage, the coordinator:

- pasted the official spec verbatim;
- wrote binding rulings for the gaps;
- split the work by file ownership;
- handed one exact commit to the verifier.

The verifier built that commit from a clean clone and ran its own black-box suites.

**The review was real.** In stage 2, the coordinator spotted the page shifting sideways on a 375-pixel phone. The verifier's first pass accepted the build, because its test data never produced the broken layout. The coordinator refused to freeze the stage. The verifier then added the missing case, reproduced the defect, withdrew its ACCEPT and rejected the candidate. The fix came back through the room 25 minutes after the problem was first raised. At the end, the verifier also rejected the final head because a credential had been echoed into the room log. It was redacted before the run ended.

**Results.** All four stages were accepted. Each stage folder passes the official shipped checks in isolated mode: 120, 25, 7 and 6. They also pass the verifier's own suites: 424, 143, 164 and 343 tests, including 240 brute-force optimizer cases. Model spend for the machine that day, rehearsals included, was a catalog estimate of $284.60.

**Limitations.** Payments are simulated. The e-mail and Telegram adapters have not been tested against live services. Two small display defects found after the run are listed in the README. `FACTORY.md` explains how to stand the factory up, and `room.json` is the full room.

## Technology tags (pick the closest from the form's list)

Band Desktop · Claude Code · Anthropic Claude (claude-opus-5-5) · Python · Docker · Playwright · pytest · JavaScript

## Category tags (pick the closest from the form's list)

AI agents · Multi-agent systems · Developer tools · Hospitality

## GitHub repository

https://github.com/ihatecodingaaa/tablekeeper-dark-factory

---

## Factory summary (for slides, the video or a long-form field)

Four Claude Code seats in one Band Desktop room, each with a generic mandate:

- a **coordinator** that pastes the spec, writes rulings, splits work by file ownership and runs a gate;
- a **developer** that owns domain correctness;
- a **product engineer** that owns the interface and packaging;
- an **independent verifier** that writes black-box suites from the spec and gives a binding ACCEPT or REJECT on one exact commit.

An accepted stage is frozen and copied forward as the next stage's base. In the judged run that took 3 h 26 min from one dispatch. The factory caught a 375 px layout defect its own verifier had first accepted, and a credential in its own evidence. Spend was a catalog estimate of $284.60 for the machine's whole day.

## App summary

Tablekeeper is a reservation system that keeps working after the booking:

- **Correct bookings:** idempotent, serializable bookings, so 50 simultaneous attempts on one table give exactly one booking.
- **Accurate times:** time-zone and DST-correct local times.
- **Durable terms:** effective-dated policies, where each booking keeps its terms.
- **Exact repairs:** seating repair after a closure, previewed read-only and applied atomically.

The guest side is *My Evening*: guarantee, calendar, preferences and change history. The operator side is the *Control Room* and the *Recovery Simulator*. Everything runs from one Docker image with no network at runtime and no credentials. Payments are simulated.

## Agent teamwork summary

The room log has 2,795 events, all from the four seats, and no human message. The work is split across seats in both the room and the git history: 27 product-engineer commits and merges, 16 coordinator commits and integration merges, and 14 developer commits and merges. Every handoff pastes the full spec and task and comes back with a commit SHA and test counts.

Review changed the work more than once:

- the coordinator's gate caught 5 failing checks in stage 1;
- the developer's cross-review found a booking that could vanish from the screen;
- the verifier withdrew a premature ACCEPT and rejected a stage 2 candidate;
- the verifier rejected the final head over a credential in the room log.

---

## Do not write these anywhere

- "Real payments", "PCI" or "card processing": the Guarantee is simulated.
- "Sends email / Telegram": the adapters exist but were never tested against live services.
- "Zero bugs" or "production-ready": two display defects are known.
- "The verifier caught the 375 px bug on its own": the coordinator raised it first, and the verifier's first verdict was ACCEPT.
- "Cost $284.60": it is a catalog estimate for the whole machine-day, including rehearsals, and not an invoice.
- "No human involvement at all": one dispatch started the run, and housekeeping (the room download, retiring the leaked lease, these docs) happened after END.
