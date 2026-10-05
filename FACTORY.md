# FACTORY

How this repository was produced. One human dispatch started the judged run. Four Claude Code seats built it in one Band room, and the human gave no further input until the coordinator's final report.

## The run in numbers

Every figure here comes from `room.json` or the git history.

- RUN-START at 08:52:05 UTC on 5 October 2026, END at 12:18:14 UTC: 3 h 26 min.
- Four stages, each accepted by the independent verifier on one exact commit and then frozen.
- Two rejections that changed the work, both fixed through the room before END: a stage 2 candidate whose page scrolled sideways at 375 px, and a final head whose room log held a credential.
- 2,795 room events, all from the four seats. The log contains no human-authored message.
- 57 commits in the run, none amended, rebased or squashed. By the task and branch named in each subject: product engineer 27 (18 commits, plus 9 merges of developer checkpoints into its branch), coordinator 16 (8 `--no-ff` integration merges into `main`, plus the skeleton, three stage carry-forwards, the docs and three evidence commits) and developer 14 (13 commits and 1 merge). All use the repository-configured identity. Changes after END are listed under [After END](#after-end).

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
4. Give the coordinator one run authorization. The coordinator then posts RUN-START to the room (here: message `d9a99513`). RUN-START names the run ID, the result repository, the verifier workspace, the official spec location and the git rules: the repository-configured identity, no AI trailers, never amend, rebase or force. From then on only the seats write in the room.

## How a stage runs

1. **Spec in the room.** The coordinator pastes the official stage spec verbatim, as numbered messages so nothing is truncated. It follows with RULINGS for every gap the spec leaves open, such as error precedence and boundary semantics. Rulings take the reading that keeps every stated rule true and are binding on all seats.
2. **Contracts before code.** When two seats share a boundary, the coordinator writes an interface contract with exact signatures. The developer commits a checkpoint so the other seat can merge it and build against real code.
3. **Parallel, owned work.** Each seat works test-first in its own git worktree and branch, edits only the files it owns, and posts its committed SHA with commands, counts and limitations.
4. **Coordinator gate.** The coordinator merges with `--no-ff` and runs the full test suite (unit, HTTP, Playwright). It then runs the official harness in isolated mode, confirms that frozen stage folders are byte-identical, and hands the exact SHA to the verifier.
5. **Independent verdict.** The verifier builds that SHA from a clean clone and runs its own suite, plus the regressions for every earlier stage. It also runs upgrade tests that export from the accepted earlier images, and the harness. Every result goes into hashed evidence (`SHA256SUMS`).
6. **REJECT or ACCEPT.** A REJECT names the failing spec line, a reproduction, and observed vs expected. The fix comes back through the room as a new SHA. On ACCEPT the stage folder is frozen and copied verbatim, via `git archive`, as the next stage's base.

Idle seats are put to work instead of waiting: cross-reviewing another seat's code, building the next stage's verification suite early, or building additive features as new files on separate branches.

## What the factory caught (real examples from this run)

The codes in parentheses are the first eight characters of a message `id` in `room.json`; search for them.

- **Stage 1, coordinator gate** (`580c3dc9`): 5 of the 120 shipped checks failed. Reset rejected a legitimately huge cancellation cutoff, and it accepted seeded references that break the reference format rule. Both were routed to the developer with the spec lines quoted and fixed test-first, before the verifier saw the candidate.
- **Stage 2, verifier REJECT at 375 px.** In a product-engineer screenshot the coordinator saw the whole page shifted sideways at 375 px and sent it back as finding A1 (`0062bb79`). The product engineer reproduced it and found the cause: visually hidden "No joined tables free" labels were absolutely positioned inside a grid scroller that had no positioning, so they escaped its clip and widened the page to 508–546 px (`30d9393e`). The verifier's first pass ACCEPTed the candidate (`e15f88ed`), because every row in its fixture had a free table pair and those labels never rendered. The coordinator recorded that verdict but kept the stage open (`0fb2433b`). The verifier added the missing scenario, reproduced the overflow on the same commit, withdrew its ACCEPT and REJECTed (`19715d9f`). The fix came back as a second candidate and was ACCEPTed (`e110e8cc`), 25 minutes after A1 was raised.
- **Stage 2, developer cross-review of the UI** (`9de7559c`): a booking reply could be silently dropped if the diner clicked another table while the request was in flight, leaving a booking on the server that the screen never showed. The coordinator ruled on each finding (`f332811d`), and the fix shipped in the same second candidate.
- **Stage 4, ruling review** (`9bbf0524`): the spec says larger planning inputs "may" be refused. Refusing an input the optimizer could solve exactly only adds risk, so the planner always solves exactly within a deterministic work budget. The verifier changed its expectations openly to match the ruling (`047abe39`).
- **Stage 4, robustness pass** (`c41aafc7`): credentialed notification delivery used one thread per message, so a hung mail host could pile up threads. A bounded worker pool replaced it.
- **Final evidence, verifier secret scan** (`3454e223`): the downloaded `room.json` contained one Jam receive lease, a seat credential mirrored from a pre-run diagnostic. The coordinator's own scan had missed that pattern. The verifier REJECTed the final head, the value was replaced with `[REDACTED]` as the participant guide prescribes (`8b98f39f`), and the scanner was extended. History is never rewritten, so the original value is still in commit `7e5a0be`, which is now public. After END the coordinator detached the session that held the lease and checked that the old lease is refused exactly like a random value, with a valid lease accepted as the control (tool results `877a4705`, `80e04be0` and `d7eae73e`, 12:31 UTC).

## What the factory missed (found after the run)

A review of the public repository after the run found two defects in the stage-4 extras. The stage folders are frozen, so they are recorded here rather than fixed.

- The Guarantee's last event is shown as `[object Object]` in two places: the Guarantees card on *My evenings* (`/passport`) and the Guarantees table in the Control Room. The backend returns the event as an object, and both screens print it as text. The verifier's extras checks covered console errors, page overflow, labels, focus, leaked tokens and the Guarantee card on *My Evening*, but never read these two cells.
- After a repair is applied, the simulator's "Already closed" line prints the closure window in the viewer's time zone, while every other time on the page is restaurant-local.

## Evidence and gates

| Stage | Accepted SHA | Verifier suites at acceptance | Official harness (isolated) |
|---|---|---|---|
| 1 | `5a69282d10d87a1cd25fef81471f3550e1192a00` | suite-s1 424/424 | stage 1 120/120, claims 1 |
| 2 | `685b17050a51e3ab474da98db0bd00348117854d` | suite-s2 143/143, s1 424/424 | 120 + 25, claims 2 |
| 3 | `17dfe5c3dea2c6fbca84e82e3b062998d1da49e7` | suite-s3 164/164, s2 143, s1 423 plus 1 intended delta | 120 + 25 + 7, claims 3 |
| 4 | `eb9582ba3012e2d35f1d4eb79a4d39d3841805a7` | suite-s4 343/343 (incl. 240 optimizer-oracle cases and 27 extras checks), s3 164, s2 143, s1 423 + 1 intended delta | 120 + 25 + 7 + 6, claims 4 |

The verdicts are messages `6d85ef28` (stage 1), `e110e8cc` (stage 2), `057fc369` (stage 3), `1adde293` (stage 4) and `c2173759` (final head). The verifier's evidence lives in its own workspace, with one directory per verdict holding logs, image IDs and `SHA256SUMS`. The coordinator re-checks each `SHA256SUMS` before closing a gate. That workspace is not part of this repository; the verdict messages quote its results and hashes.

Reading `room.json`: the 126 `text` events are what the seats said to each other. Apart from three join events, the rest are mirrored tool calls and results from the coordinator, the product engineer and the verifier. The developer's tool calls are not in the log, only its 30 messages, so its work is traced through those messages and the commits tagged `S*-DEV-*`.

## Design choices and what they cost

- **Python standard library and a single process-wide lock.** Every request becomes trivially serializable: no double booking, exactly one 201 per idempotency key, atomic multi-booking moves. Throughput is bounded by one lock. Under the judged limits (2 vCPU, 2 GiB, 50 in flight) a 60 s mixed load of 15,857 requests produced no 5xx, and the slowest request took 1.75 s.
- **Replays are byte-exact, never "upgraded".** An idempotent replay returns the response exactly as it was first stored, even after a later stage adds new response fields. We chose stability of historical receipts over inferred enrichment. Current-state reads use the newest shape.
- **An exact optimizer instead of a heuristic.** Seating repair uses branch and bound with a deterministic node budget. The verifier checked it against its own brute-force oracle on 240 seeded cases, and the developer against 400 more.
- **Black-box verification from the spec text.** The verifier never reads implementation code, so its tests cannot inherit the implementers' blind spots. They can still have their own: its stage 2 fixture always left a free table pair, which is why its first verdict missed the 375 px defect. The coordinator's gate, which looks at screenshots as well as test counts, is the second net.
- **Extras are strictly additive.** Guarantee, notifications, calendar and the operator views live under `/x/...` and on new screens, behind hooks that run after the official commit and can never raise into it. They need zero credentials and zero network.
- **Rulings over questions.** In a zero-human run nobody can ask the human. Every ambiguity becomes a written, binding ruling in the room, cited by later handoffs and by verifier tests.

## Time and spend (measured)

- RUN-START at 08:52:05 UTC, 2026-10-05 (`d9a99513`).
- Stage gates closed at 09:35:58 (stage 1, 44 min after RUN-START), 10:30:27 (stage 2, 54 min later), 11:04:24 (stage 3, 34 min) and 11:59:11 (stage 4, 55 min). Stages overlap a little: the verifier built later suites and the seats built extras in idle time.
- Final-head verification, including the credential REJECT and its fix, ended with the verifier's final ACCEPT at 12:14:41 (`c2173759`). END followed at 12:18:14 (`66d0db05`), and the other three seats acknowledged it by 12:19:32.
- All timestamps come from the room log.
- Model spend: all four seats ran claude-opus-5-5. At 11:59 UTC `jam usage daily` reported a catalog-estimated $284.60 for 2026-10-05 (`73ab41ca`). That figure covers every Claude Code session on that machine that day, including pre-run rehearsal, and it was read 19 minutes before END. It is an estimate from the tool's price catalog, not a provider invoice.

## What did not work earlier (from rehearsals)

- **Receivers lapsing mid-run.** Monitors expire after 30 minutes. Seats now re-arm their own receivers as part of the run authorization.
- **Rooms hitting their message cap.** One rehearsal room reached 10,000 messages because tool traffic is mirrored into it. Each run now uses a fresh room.
- **Long handoffs truncated in seat notifications.** Seats now read the full stored message with `jam room messages --json`.
- **Mention parsing.** A handle followed by punctuation does not resolve, so handles go on their own line.

## After END

- At 12:31 UTC the coordinator detached the product engineer's receive session and confirmed that the exposed lease is refused (see the last item under [What the factory caught](#what-the-factory-caught-real-examples-from-this-run)).
- Commit `a9de6bc` replaced `room.json` with a full-session download taken at 12:35 UTC, so the log includes END and all three END-ACKs. The lease value was redacted again, and `room.json` at HEAD contains no lease value.
- `README.md` and `FACTORY.md` were edited later for accuracy and evidence pointers. No stage folder or mandate has changed since its acceptance, and the git history shows every change.
