# FACTORY

How this repository was produced. One human dispatch started the judged run. Four Claude Code seats built it in one Band room, and the human gave no further input until the coordinator's final report.

## Seats

| Seat (as the room shows it) | Harness / model | Owns |
|---|---|---|
| `architect-x7qk` (Architect / Coordinator) | Claude Code / claude-opus-5-5 | Reads each official stage spec, writes rulings for gaps, splits work by file ownership, pastes the complete spec and task into every handoff, merges seat branches with `--no-ff`, runs the coordinator gate and hands one exact SHA to the verifier |
| `developer-x7qk` (Developer) | Claude Code / claude-opus-5-5 | Domain and data correctness: booking rules, time zones and DST, idempotency, concurrency, policies and history, the optimizer, import upgrades, the extras backend |
| `product-engineer-x7qk` (Product Engineer) | Claude Code / claude-opus-5-5 | The delivered interface: HTTP boundary, browser product, recurring-series slice, packaging (`Dockerfile`, `RUN.md`), product polish and the extras screens |
| `independent-verifier-x7qk` (Independent Verifier) | Claude Code / claude-opus-5-5 | Writes black-box suites from the spec text in a separate workspace, never from implementer tests. Builds the exact SHA from a clean clone and issues a binding ACCEPT or REJECT |

The mandates in `mandates/` are generic. They say how a seat works, what it owns, how it hands off and when it rejects, and they name nothing about this track. `harness check` confirms that.

### Standing it up

1. Create four Claude Code seats in Band Desktop.
2. Add them to one room and give each its mandate.
3. Keep each seat's receiver alive with a monitor that it re-arms itself when it expires (30 minutes).
4. Paste one run-start into the room. It names the result repository, the verifier workspace, the official spec location, and the git rules: the repository-configured identity, no AI trailers, never amend, rebase or force.

## How a stage runs

1. **Spec in the room.** The coordinator pastes the official stage spec verbatim, as numbered messages so nothing is truncated. It follows with RULINGS for every gap the spec leaves open, such as error precedence and boundary semantics. Rulings take the reading that keeps every stated rule true and are binding on all seats.
2. **Contracts before code.** When two seats share a boundary, the coordinator writes an interface contract with exact signatures. The developer commits a checkpoint so the other seat can merge it and build against real code.
3. **Parallel, owned work.** Each seat works test-first in its own git worktree and branch, edits only the files it owns, and posts its committed SHA with commands, counts and limitations.
4. **Coordinator gate.** The coordinator merges with `--no-ff` and runs the full test suite (unit, HTTP, Playwright). It then runs the official harness in isolated mode, confirms that frozen stage folders are byte-identical, and hands the exact SHA to the verifier.
5. **Independent verdict.** The verifier builds that SHA from a clean clone and runs its own suite, plus the regressions for every earlier stage. It also runs upgrade tests that export from the accepted earlier images, and the harness. Every result goes into hashed evidence (`SHA256SUMS`).
6. **REJECT or ACCEPT.** A REJECT names the failing spec line, a reproduction, and observed vs expected. The fix comes back through the room as a new SHA. On ACCEPT the stage folder is frozen and copied verbatim, via `git archive`, as the next stage's base.

Idle seats are put to work instead of waiting: cross-reviewing another seat's code, building the next stage's verification suite early, or building additive features as new files on separate branches.

## What the factory caught (real examples from this run)

- **Stage 1, coordinator gate:** 5 of the 120 shipped checks failed. Reset rejected a legitimately huge cancellation cutoff, and it accepted seeded references that break the reference format rule. Both were routed to the developer with the spec lines quoted and fixed test-first.
- **Stage 2, verifier REJECT:** at 375 px the page could scroll horizontally once some grid rows had no joined-table option. Absolutely positioned hidden labels escaped the grid's scroll container. The verifier's first ACCEPT missed it because every row in its fixture had a free pair. It withdrew that verdict after the coordinator flagged a suspicious screenshot, added the missing scenario, reproduced the defect and REJECTed. The product engineer fixed the root cause.
- **Stage 2, developer cross-review of the UI:** a booking reply could be silently dropped if the diner clicked another table while the request was in flight, leaving a booking on the server that the screen never showed. It was fixed before acceptance.
- **Stage 4, ruling review:** the spec says larger planning inputs "may" be refused. Refusing an input the optimizer could solve exactly only adds risk, so the planner always solves exactly within a deterministic work budget. The verifier changed its expectations openly to match the ruling.
- **Stage 4, robustness pass:** credentialed notification delivery used one thread per message, so a hung mail host could pile up threads. A bounded worker pool replaced it.
- **Final evidence, verifier secret scan:** the downloaded `room.json` contained one Jam receive lease, a seat credential mirrored from a pre-run diagnostic. The coordinator's own scan had missed that pattern. The verifier REJECTed the final HEAD, the value was replaced with `[REDACTED]` as the participant guide prescribes, and the scanner was extended. The value remains in one unpushed commit because history is never rewritten, so rotating that lease is recorded as a pre-push action for the owner.

## Evidence and gates

| Stage | Accepted SHA | Verifier suites at acceptance | Official harness (isolated) |
|---|---|---|---|
| 1 | `5a69282d10d87a1cd25fef81471f3550e1192a00` | suite-s1 424/424 | stage 1 120/120, claims 1 |
| 2 | `685b17050a51e3ab474da98db0bd00348117854d` | suite-s2 143/143, s1 424/424 | 120 + 25, claims 2 |
| 3 | `17dfe5c3dea2c6fbca84e82e3b062998d1da49e7` | suite-s3 164/164, s2 143, s1 423 plus 1 intended delta | 120 + 25 + 7, claims 3 |
| 4 | `eb9582ba3012e2d35f1d4eb79a4d39d3841805a7` | suite-s4 343/343 (incl. 240 optimizer-oracle cases and 27 extras checks), s3 164, s2 143, s1 423 + 1 intended delta | 120 + 25 + 7 + 6, claims 4 |

The verifier's evidence lives in its own workspace, with one directory per verdict holding logs, image IDs and `SHA256SUMS`. The coordinator re-checks each `SHA256SUMS` before closing a gate.

## Design choices and what they cost

- **Python standard library and a single process-wide lock.** Every request becomes trivially serializable: no double booking, exactly one 201 per idempotency key, atomic multi-booking moves. Throughput is bounded by one lock. Under the judged limits (2 vCPU, 2 GiB, 50 in flight) a 60 s mixed load of 15,857 requests produced no 5xx, and the slowest request took 1.75 s.
- **Replays are byte-exact, never "upgraded".** An idempotent replay returns the response exactly as it was first stored, even after a later stage adds new response fields. We chose stability of historical receipts over inferred enrichment. Current-state reads use the newest shape.
- **An exact optimizer instead of a heuristic.** Seating repair uses branch and bound with a deterministic node budget. The verifier checked it against its own brute-force oracle on 240 seeded cases, and the developer against 400 more.
- **Extras are strictly additive.** Guarantee, notifications, calendar and the operator views live under `/x/...` and on new screens, behind hooks that run after the official commit and can never raise into it. They need zero credentials and zero network.
- **Rulings over questions.** In a zero-human run nobody can ask the human. Every ambiguity becomes a written, binding ruling in the room, cited by later handoffs and by verifier tests.

## Time and spend (measured)

- The run started at 08:52 UTC, 2026-10-05, when RUN-START was posted in the room.
- Stage 1 closed at 09:36, Stage 2 at 10:30, Stage 3 at 11:04, and Stage 4 at 11:59.
- The END notice comes after the final verification, so its timestamp is in the room log rather than here. All timestamps come from the room log.
- Model spend: all four seats ran claude-opus-5-5. `jam usage daily` reports a catalog-estimated $284.60 for 2026-10-05 (all Claude Code sessions on this machine that day, including pre-run rehearsal activity; the judged run is a subset of it) for this machine on the run day. That figure is not a provider invoice, and it includes some pre-run activity on the same machine.

## What did not work earlier (from rehearsals)

- **Receivers lapsing mid-run.** Monitors expire after 30 minutes. Seats now re-arm their own receivers as part of the run authorization.
- **Rooms hitting their message cap.** One rehearsal room reached 10,000 messages because tool traffic is mirrored into it. Each run now uses a fresh room.
- **Long handoffs truncated in seat notifications.** Seats now read the full stored message with `jam room messages --json`.
- **Mention parsing.** A handle followed by punctuation does not resolve, so handles go on their own line.
