# Factory evidence map

Each judging claim we make, the evidence behind it, and how to show it.

- **Message ids** are the first eight characters of a message `id` in `room.json`. Search for them in the file, or in the Band console.
- **Times** are UTC from the room log, with UTC+8 (Singapore) in brackets for anyone reading them off a machine in that time zone.
- **Confidence:** HIGH means checked directly against this repository, or re-run on a fresh public clone after the run. MEDIUM means reported in the room with hashes, but its evidence lives in the verifier's private workspace and was not re-run. LOW means an owner statement only.

---

### 1. The run was autonomous

- **Why it matters:** Agent Teamwork (25%), "Autonomy": the dispatch is the only human input; no steering, approvals, debugging hints or reruns.
- **Evidence:**
  - `room.json` holds 2,795 events from exactly four senders, all of type Agent: `architect-x7qk`, `developer-x7qk`, `product-engineer-x7qk` and `independent-verifier-x7qk`. There is no human-authored message.
  - RUN-START `d9a99513` at 08:52:05 (16:52). It says "From now until my END post, no seat asks Lucas anything or waits for him."
  - END `66d0db05` at 12:18:14 (20:18).
  - END-ACKs: `b4824f3e` (developer), `ed8eb1d9` (verifier) and `e202be0e` (product engineer), by 12:19:32.
- **How to show:** In Band Desktop, scroll to RUN-START, then to END. Say that nobody but the seats wrote in between.
- **Confidence:** HIGH that the room has no human message. MEDIUM that the dispatch was the only input. The dispatch went straight to the coordinator's own session, so its text is not in `room.json`. The coordinator recorded "Lucas authorized…" in its memory before RUN-START (tool call at 08:46:30).

### 2. Review changed the product

The stage 2 REJECT at 375 px.

- **Why it matters:** Factory (50%), "how it catches and recovers from bad work"; Teamwork, "review changed something". The participant guide asks the video for "a bad result it caught".
- **Evidence, in order:**

  | Time UTC (UTC+8) | Message | What happened |
  |---|---|---|
  | 10:05:26 (18:05) | `0062bb79` | The coordinator raises A1 from a product-engineer screenshot: the page is shifted about 35 px at 375 px. It quotes the spec line "without horizontal page scrolling". |
  | 10:07:44 (18:07) | `30d9393e` | The product engineer reproduces it: `scrollWidth` 508–546 against `clientWidth` 375. Root cause: absolutely positioned hidden labels escape the grid scroller. |
  | 10:23:47 (18:23) | `e15f88ed` | The verifier ACCEPTs C1 `115aaf55`. Its probe could not reproduce A1, because every fixture row had a free pair. |
  | 10:24:07 (18:24) | `0fb2433b` | The coordinator records the ACCEPT but does not freeze stage 2, and asks for a scenario with no free pairs. |
  | 10:25:43 (18:25) | `19715d9f` | "S2-VERDICT C1 REVISED … REJECT (supersedes my ACCEPT e15f88ed)", with a reproduction and observed vs expected values. |
  | 10:30:04 (18:30) | `e110e8cc` | ACCEPT of C2 `685b1705`, including the new 375 px test. |

  The commits: C1 is `115aaf5`; the fixes are `c889982` and `fc47b5b`; C2 is merge `685b170`.
- **How to show:** In the room, the six messages above. Show `git show --stat c889982` if there is time. In the app, the 375 px search screen, where the grid scrolls inside its frame and the page does not.
- **Confidence:** HIGH.

### 3. Peer review found a real defect, not only the verifier

- **Why it matters:** Teamwork, "more than one seat did it, review changed something".
- **Evidence:** the developer's read-only cross-review of the product engineer's UI, `9de7559c` at 10:09:07. Finding F1: an in-flight booking reply was silently dropped when another cell was clicked. The coordinator ruled on it ("a real review that changes the work", `f332811d`), the product engineer fixed it in `c889982` with tests that fail on C1 (`5593d664`), and it shipped in C2.
- **How to show:** One message in the room, `9de7559c`, which is long, so show the "F1 (medium …)" paragraph.
- **Confidence:** HIGH.

### 4. Handoffs carried the whole task

- **Why it matters:** Teamwork, "handoffs carried the whole task". The guide says pointing at a message id or asking a seat to read the room is not enough.
- **Evidence:**
  - Spec pasted verbatim as numbered parts: S1-SPEC 1/3 is `c08c5b46` (08:57:17), with the spec's sha256 named in each task.
  - Binding rulings follow.
  - Each task names base revision, ownership, non-goals and the evidence wanted back: S1-DEV-T1 `1023054b` (08:59:42), S1-PE-T1, S1-VER-T1.
  - Replies carry SHAs and counts: S1-DEV-T1 DONE `496eed61` (09:19:22) and S1-PE-T1 DONE `1f3861ad`.
- **How to show:** S1-DEV-T1, then the developer's DONE reply with its FINAL SHA.
- **Confidence:** HIGH.

### 5. Seats talked to each other directly

This is gate 2: two seats exchange `@handle` messages, with a reply in each direction.

- **Evidence:** the product engineer's interface note to the developer, `5f1346c5` (09:07:22), and the developer's reply, `e9bdda16` (09:08:10). `harness check` on a fresh clone of `a9de6bc` reports gates 1 and 2 ok.
- **How to show:** Those two short messages, which fit on one screen.
- **Confidence:** HIGH.

### 6. The work was distributed

- **Why it matters:** Teamwork. The guide warns that one seat carrying 90% of the work looks the same however many messages it sent.
- **Evidence:**
  - The 57 run commits, by the task and branch in their subjects: product engineer 27, coordinator 16 (8 of them integration merges) and developer 14.
  - Room messages (`text`): coordinator 58, developer 30, product engineer 19, verifier 19.
  - The developer's tool calls are not mirrored into the room. Its work is traced through its messages and its `S*-DEV-*` commits.
- **How to show:** In `git log --oneline`, the task tags in the subjects (S1-DEV-T1, S1-PE-T1, …).
- **Confidence:** HIGH for the counts. The split is inferred from task tags, because all commits use one repository identity, as the run rules required.

### 7. Independent verification was substantive

- **Why it matters:** Factory, "effective", including what the shipped checks never asked.
- **Evidence:**
  - Black-box suites written from the spec in a separate workspace: suite-s1 424/424 (`6d85ef28`), suite-s2 143/143 (`e110e8cc`), suite-s3 164/164 (`057fc369`) and suite-s4 343/343 with 240 brute-force optimizer-oracle cases and 27 extras checks (`1adde293`).
  - Upgrade tests export from the accepted earlier images.
  - Four of its own test bugs were disclosed and fixed openly, each with no expectation loosened: `6d85ef28`, `e15f88ed`, `057fc369` and `1adde293`.
- **How to show:** One verdict message, for example `1adde293`, with its sections (1), (2)+(3) and "Suite correction (disclosed)".
- **Confidence:** MEDIUM. The suites and their hashed evidence are in the verifier's workspace, which is not in this repository. The developer's separate 400-case brute-force oracle is in `stage-4/tests/unit/test_planner.py`, and it passed in a post-run run of `python -m pytest` (1131 passed): HIGH.

### 8. Every verdict is bound to one exact commit

- **Evidence:** each verdict names the full SHA and the stage tree. The accepted trees are stage-1 `5d0c4e5c`, stage-2 `38233890`, stage-3 `8042e1bb` and stage-4 `c9a35316`. Post-run check on a fresh clone: each folder's tree at HEAD equals its tree at the accepted commit, and no commit touches a stage folder after its acceptance.
- **How to show:** `git rev-parse 685b1705:stage-2 HEAD:stage-2` prints the same hash twice.
- **Confidence:** HIGH.

### 9. The stages accumulate, and each one passes the official checks

- **Evidence:**
  - Post-run, on a fresh clone of `a9de6bc`, `harness run --track tablekeeper --repo <clone> --all --mode isolated` (harness commit `803560d`) gave:
    - stage-1/ suite 1 120/120;
    - stage-2/ 120 + 25/25;
    - stage-3/ 120 + 25 + 7/7;
    - stage-4/ 120 + 25 + 7 + 6/6.
  - Each folder claims its own stage, and each overshoot probe fails as intended.
  - The run's own isolated harness results match: END `66d0db05`.
- **How to show:** A terminal recording of the `--all` run, which takes about 4 minutes and can be sped up. The fallback is the END message's "OFFICIAL HARNESS" section.
- **Confidence:** HIGH. One environment note: the post-run check had to build the harness runner image on a Playwright 1.63.0 base, because the sandbox it ran in blocks `deb.debian.org` and the Playwright CDN. Harness code, tests, network isolation and limits were unchanged.

### 10. The services need no outbound network

- **Evidence:**
  - Post-run, all four stage images were built from the fresh clone with their `RUN.md` commands. Each started with `--network none --cpus 2 --memory 2g` and served `/health` from inside the container in 0.5–1.4 s, with loopback as the only interface, as the non-root user `tablekeeper`.
  - The browser walk-through ran on a Docker `--internal` network with no route out: 0 failed requests and 0 console errors.
- **Confidence:** HIGH.

### 11. The factory caught a security problem in its own evidence

- **Evidence:**
  - F-SEC1 REJECT `3454e223` (12:09:15). Remediation `8b98f39f`. Product-engineer root cause `f633b327`. Developer cross-check `046b3c57`. Final ACCEPT `c2173759`.
  - After END, the coordinator detached the session that held the lease. The old lease was then refused exactly like a random value, while a valid lease was accepted as the control: tool results `877a4705`, `80e04be0` and `d7eae73e` (12:31).
  - `room.json` at HEAD contains no lease value. The original is in public commit `7e5a0be`.
- **Confidence:** HIGH for what the room shows. LOW, owner statement only, for the lease's current revocation status in Band.

### 12. Measured time and spend

- **Evidence:** RUN-START 08:52:05 → END 12:18:14 = 3 h 26 min. Gate closures were at 09:35:58, 10:30:27, 11:04:24 and 11:59:11. Spend: `jam usage daily` showed $284.60 for 2026-10-05 (`73ab41ca`, 11:59).
- **Caveat to say aloud:** the spend is a catalog estimate for every Claude Code session on that machine that day, including rehearsals. It was read 19 minutes before END, and it is not an invoice.
- **Confidence:** HIGH for the time. MEDIUM for the spend: real, but an estimate.

### 13. The mandates are generic

- **Evidence:**
  - `harness check` (which includes the organizers' track-vocabulary scan) passes.
  - A manual read of all four mandates found no product, restaurant, booking, table, endpoint, field or error-code term.
  - The architect mandate says it "must not encode any particular product's routes, types, APIs, field names or demo answers".
- **Confidence:** HIGH.

### 14. The app is responsive and clean at runtime

- **Evidence:** a post-run Playwright walk at 375 × 812 and 1280 × 800 covered:
  - every guest and manager screen;
  - a booking;
  - the `.ics` download;
  - a repair preview and apply.

  Results: page-level horizontal overflow 0 px at every step, 0 console errors, 0 page errors, 0 failed requests and 0 HTTP ≥ 400.
- **Known defects:** `[object Object]` in the Guarantees card on `/passport` and in the Control Room Guarantees table. The simulator's "Already closed" line uses the viewer's time zone.
- **Confidence:** HIGH.
