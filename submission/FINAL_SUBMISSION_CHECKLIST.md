# Final submission gate

## How to read this

**Status values:**

- **PASS:** verified by a check that actually ran, or a direct read of the evidence, on a fresh clone of the public repository at `a9de6bc`, on 5 Oct 2026, 15:10–16:10 UTC.
- **FAIL:** a check ran and failed.
- **NEEDS HUMAN:** only the owner can do or confirm it.
- **BLOCKED BY ENVIRONMENT:** the review sandbox could not run it.

**Sources:**

- **PG:** `docs/participant-guide.md` in `band-ai/dark-factory-wearedevs` at commit `803560d` (2026-09-26). It calls itself "the authoritative rules and instructions".
- **LL:** the lablab event page, from the owner's screenshots of 5 Oct 2026. The live page was blocked from the sandbox.

## 1. Engineering gate

| Item | Status | How it was verified |
|---|---|---|
| Fresh public clone | PASS | `git clone https://github.com/ihatecodingaaa/tablekeeper-dark-factory`: HEAD `a9de6bc4657bc028865e83f4b138c6e8acc2da89` equals `origin/main`, `git status --porcelain` is empty, and the clone is not shallow. |
| Repository visibility | PASS | The GitHub API returns `"visibility": "public"`, and an anonymous fetch of the repository page returns 200. |
| Structure | PASS | Root holds `README.md`, `FACTORY.md`, `mandates/` (4 files), `room.json` and `stage-1/` … `stage-4/`, each stage with a `Dockerfile` and `RUN.md`. No gitlinks, symlinks or nested `.git`. |
| Stage tree identities | PASS | The HEAD trees are stage-1 `5d0c4e5c…`, stage-2 `38233890…`, stage-3 `8042e1bb…` and stage-4 `c9a35316…`. Each equals its tree at the accepted commit (`5a69282d`, `685b1705`, `17dfe5c3`, `eb9582ba`), and no commit touches a stage folder after its acceptance. |
| Natural history | PASS | 58 commits, 18 of them merges. First-parent dates never go backwards. Every accepted SHA named in the room is an ancestor of HEAD. The run's END reports 57 commits, which matches history plus one post-run commit. |
| Git authorship | PASS | All 58 commits have author and committer `Lucas Tan <2201904f@gmail.com>`. None are signed. Commit messages contain no `Co-authored-by`, `Claude`, `Anthropic`, `OpenAI`, `ChatGPT`, `Generated-by`, `AI-generated`, `AI-authored`, `Copilot` or `GPT`. The README's own "AI assistance" disclosure is deliberate and stays. |
| Official structural check | PASS | `python -m harness check <clone> --track tablekeeper` printed "ok — gates 1, 2 and the mandate part of gate 4 pass". It was run with Python 3.11.15; the guide asks for 3.12+, and `check` is standard-library only. |
| Official isolated harness, all stages | PASS | `harness run --track tablekeeper --repo <clone> --all --mode isolated` (harness `803560d`) took 3 min 46 s. stage-1/ 120/120; stage-2/ 120 + 25/25; stage-3/ 120 + 25 + 7/7; stage-4/ 120 + 25 + 7 + 6/6. Each folder "claims stage N on the shipped checks", and each overshoot probe fails as intended. **Environment note:** the sandbox blocks `deb.debian.org` and the Playwright CDN, so the runner image was built from the official `harness/Dockerfile` with only its base swapped for `mcr.microsoft.com/playwright/python:v1.63.0-noble`, the same Playwright 1.63.0 the harness pins. Harness code, tests, `--internal` network and the 2 vCPU / 2 GiB limits were unchanged. |
| Clean-container build, all stages | PASS | `docker build -t tablekeeper-stage-N .` in each folder, exactly as its `RUN.md` says, succeeded. **Environment note:** `python:3.12-slim` was re-tagged locally to the same upstream digest plus this sandbox's proxy CA, so `pip` could verify TLS. No Dockerfile was edited. |
| Starts and becomes reachable | PASS | Each stage ran with `--network none --cpus 2 --memory 2g -e PORT=8080` and answered `GET /health` → `{"status":"ok"}` from inside the container within 0.5 s (stages 1–3) and 1.4 s (stage 4). The process runs as the non-root user `tablekeeper`. |
| No untracked machine state needed | PASS | Built from a fresh clone with no volumes, no `.env` and no environment variables except `PORT`. |
| No mandatory credential | PASS | Started with no `TK_*` variables. Notifications are delivered in-app, and email/Telegram show as simulated. |
| No outbound network needed | PASS | `--network none`: the only interface is loopback and an outbound probe fails DNS, yet all flows still work. The browser walk ran on a Docker `--internal` network with 0 failed requests. |
| Browser, 375 px and 1280 px | PASS, with non-blocking notes | Playwright (Chromium 153) ran 34 steps on the seeded demo: sign-in, search with Best Times, booking, My Evening (Guarantee, Google Calendar link, `.ics` download, preferences, share), My evenings, Messages, Look up, Control Room, Recovery Simulator preview and apply, and My Evening after the repair. Page-level horizontal overflow was 0 px at every step; console errors 0; page errors 0; failed requests 0; HTTP ≥ 400 responses 0. |
| Guest flow · booking · My Evening · Guarantee · calendar/.ics · preferences · Passport/share · Best Times · Control Room · Recovery Simulator | PASS | Each is a step above. The `.ics` begins `BEGIN:VCALENDAR`, has a `VEVENT` and `DTSTART`, and contains no token. The Google link starts `https://calendar.google.com/calendar/render?action=TEMPLATE&`. The share fallback text appears. Applying the repair moved Ada from Booth 4 to Corner 4, and her history shows "Moved by the restaurant". |
| Broken assets | PASS | No failed or ≥ 400 requests on any screen. Every asset is served from the image. |
| Runtime text defects | NON-BLOCKING | A text scan of every screen found `[object Object]` in two places, at both widths: the Guarantees card on `/passport` and the *Last event* column of the Control Room Guarantees table. The cause is that `extras/guarantee.py:178` and `extras/views.py:119` return `last_event` as an object, while `x-passport.js:91` and `x-control-room.js:222` print it as text. There were no `undefined`, `NaN`, `null` or `Invalid Date` hits. These are frozen and not fixed; they are listed in the README and FACTORY.md. |
| Time-zone display | NON-BLOCKING | After apply, the simulator's "Already closed: Booth 4 (…)" line prints in the browser's time zone. The rest of the page is restaurant-local. |
| Documentation commands | PASS, with non-blocking notes | README: build, run, `curl /health`, the seeder (exit 0, prints accounts and references) and the `pytest` flow. RUN.md tests: stage-1 588 passed, stage-2 765 passed, stage-3 942 passed, stage-4 1131 passed, each exit 0. The demo README's API calls work. **Notes:** the three docs use three image tags (`tablekeeper-s4`, `tablekeeper-stage-4`, `tablekeeper`), each consistent within its own doc. The demo README's `best-times` example uses `$(date +%F)`, which returns an empty list on Mondays, a closed day. `python -m playwright install chromium` was a no-op in the sandbox because the browser was preinstalled. |
| Secrets at HEAD | PASS | All 239 tracked files scanned. 0 matches for bearer tokens, `sk-` / `sk-ant-` keys, AWS keys, GitHub tokens, Slack tokens, JWTs, private-key blocks, URL credentials, Telegram bot tokens, Google API keys and Jam leases (`jrx_` + 16 or more hex characters). The 192 64-hex strings in `room.json` are SHA-256 evidence digests, not credentials. `tablekeeper-demo` is a published demo-only password. The `TK_*` assignments in `room.json` are local URLs, an unroutable test SMTP host and image tags. |
| `room.json` integrity | PASS | Valid JSON with `scope: full`, 2,795 events and four Agent senders. Each later download keeps every earlier message byte-identical and appends new ones (`7e5a0be` → `04e0f05`: 1 message changed, the redaction; → `af5a424`: 0 changed, 168 appended; → `a9de6bc`: 0 changed, 92 appended). |
| Secrets in history | NEEDS HUMAN | One Jam receive lease appears in history: added in `7e5a0be`, removed in `04e0f05`, and public. The room shows it refused after END, exactly like a random value, with a valid-lease control accepted (tool results `877a4705`, `80e04be0`, `d7eae73e`, 12:31 UTC). **Confirm in Band that the product engineer's receive lease is revoked.** The guide's remedy is rotation; deleting does not unpublish. |

**Engineering release verdict: ENGINEERING READY WITH NON-BLOCKING NOTES.**

## 2. Submission materials gate

| Item | Status | Notes |
|---|---|---|
| README.md | PASS on `main`; improved on branch | Branch `submission-polish-cloud` adds the team line, evidence ids, the runnable harness commands, a live-service caveat and known issues. **Merge it**, and confirm the team line. |
| FACTORY.md | PASS on `main`; improved on branch | Branch fixes a stale security statement ("unpushed commit") and adds the measured END time, message ids for every catch, the post-END changes and the misses. **Merge it.** |
| Mandates | PASS | 4 files named after the seats, each starting `Harness: Claude Code` / `Model: claude-opus-5-5`. |
| Generic mandate audit | PASS | See §4. |
| Stage directories | PASS | All four claim their stage. |
| `room.json` | PASS | See §1. |
| END evidence | PASS | END `66d0db05` at 12:18:14 UTC; END-ACKs from the developer `b4824f3e`, verifier `ed8eb1d9` and product engineer `e202be0e`. |
| Video | NEEDS HUMAN | Use `VIDEO_SCRIPT.md` and `VIDEO_SHOTLIST.md`. |
| Band Desktop room recording inside the video | NEEDS HUMAN | Mandatory (LL disqualifier). Record the real room in Band Desktop, and send nothing into it. |
| Walkthrough | NEEDS HUMAN | Script 1:55–3:00, or `JUDGE_DEMO_ROUTE.md`. |
| Cover image | NEEDS HUMAN | Use `COVER_BRIEF.md`. |
| Slide deck | NEEDS HUMAN | Use `SLIDE_OUTLINE.md`; export PDF. |
| Project title, short description, long description, tags | NEEDS HUMAN, content ready | In `SUBMISSION_COPY.md`. |
| GitHub URL | NEEDS HUMAN, content ready | `https://github.com/ihatecodingaaa/tablekeeper-dark-factory` |
| Submission page | NEEDS HUMAN | Submit, save the receipt, and check the public page while signed out. |
| Deadline | NEEDS HUMAN | **Tuesday 6 Oct 2026, 06:59 UTC**: Mon 5 Oct 23:59 PDT (PG) = Tue 6 Oct 14:59 Singapore time (LL). |

**Submission materials verdict: SUBMISSION MATERIALS READY FOR REVIEW.** The video, slides and cover are still to be produced, so this is not ready to submit yet.

## 3. Official requirements matrix

| Requirement | Official source | Repository evidence | Status | Human action |
|---|---|---|---|---|
| Register on lablab and its Discord; enroll | LL, "How to participate" | — | NEEDS HUMAN | Confirm. |
| Team of 1–6 | LL, "Teams" | README "Team: Lucas Tan" (branch) | NEEDS HUMAN | Confirm the members. |
| ≥ 3 distinct coding-agent seats in Band Desktop | PG Eligibility, gate 1; LL item 1 | 4 Agent senders in `room.json` | PASS | — |
| A mandate per seat, named after the seat, naming harness and model | PG gate 1, "The repository you submit"; LL item 1 | `mandates/*-x7qk.md`, each starting with `Harness:` and `Model:` | PASS | — |
| Mandates generic: no endpoint paths, field names, error codes or track vocabulary | PG "Your mandates must be generic", gate 4; LL item 2 (disqualifier) | `harness check` ok, plus a manual audit | PASS | — |
| Two seats exchange `@handle` messages, a reply each way | PG gate 2 | `5f1346c5` ↔ `e9bdda16`, among many | PASS | — |
| Public GitHub repo, clonable without Band membership | PG "Check and submit"; LL item 3 | visibility `public` | PASS | Keep it public. |
| Layout: README, FACTORY.md, `mandates/`, `room.json`, `stage-N/` (Dockerfile, RUN.md, source) | PG "The repository you submit"; LL item 3 | present | PASS | — |
| README covers team, track and how to read the repository | PG "The repository you submit" | track and reading guide on `main`; team added on the branch | NEEDS HUMAN | Merge the branch and confirm the team. |
| Each stage folder is a complete, buildable service holding that stage's solution, not a later one | PG; LL item 3 | `--all` isolated: each claims its own stage; overshoot probes fail | PASS | — |
| Minimum: a complete stage 1 | PG Eligibility; LL item 3 | stage-1 120/120 | PASS | — |
| Each folder counts only if every earlier one counts | PG "The chain is what scores" | 1 → 2 → 3 → 4 all claim | PASS | — |
| No submodules, symlinks or nested `.git` | PG | none | PASS | — |
| `room.json` is Band's "Download full session", unchanged except `[REDACTED]` | PG "Record the room" | `scope: full`; downloads append-only; one permitted redaction | PASS | — |
| Download the room after the work is done | PG "Record the room" | includes END and all END-ACKs | PASS | — |
| No credentials in the repository or its history; rotate if found | PG "Prepare", "Record the room", "Before you submit" #7 | HEAD clean; one revoked lease in history | NEEDS HUMAN | Confirm the lease is revoked in Band. |
| Code must come from the room; hand-built code does not count | PG "The three rules" | every stage commit carries a room task id; post-run commits touch root files only | PASS | Never commit to `stage-*/`. |
| Code written to the spec, not the tests | PG "The three rules" (enforced after close) | verifier suites from spec text (424/143/164/343) against the 120/25/7/6 shipped checks | NO ISSUE FOUND | Organizers decide after close. |
| Autonomy: the dispatch is the only human input | PG Rubric, "Build and check each stage"; LL Agent Teamwork | no human message in 2,795 events; RUN-START → END | PASS | The dispatch text itself is not in `room.json`; see §5. |
| Submitted run uses a fresh room and a fresh repository | PG "Build and check each stage" | room created 08:16 UTC on run day; history starts at the run | PASS | — |
| History pushed as made: no amend, rebase or squash | PG "Agent Teamwork evidence" | all accepted SHAs are ancestors; counts match | PASS | Use normal merges only. |
| Stage 1 builds and serves from a clean container per its RUN.md (gate 3) | PG gate 3; LL item 5 | done | PASS | — |
| Service builds and serves from a clean container with no outbound network | LL item 5 (disqualifier); PG isolated mode | all four stages | PASS | — |
| Limits: 2 vCPU, 2 GiB, 50 in flight, 5 s per request, healthy within 60 s | spec stage 1 + harness (LL: "published with the spec") | healthy in ≤ 1.4 s at 2 vCPU / 2 GiB; the run's load test gave 15,857 requests, 0 5xx, max 1.75 s (`c41aafc7`) | PASS (load figure is as reported) | — |
| FACTORY.md: seats and setup, design choices and costs, what failed, measured time and spend, how it catches bad work | PG "Check and submit", Rubric; LL Factory | sections on `main`; the branch adds the END time and evidence ids | PASS | Merge the branch. |
| README and FACTORY written by the team, not placeholders | PG "Check and submit", "Before you submit" #5 | no placeholders | PASS | See discrepancy D7. |
| Video shows the factory working: the room, a handoff and the result | PG Eligibility | script covers it | NEEDS HUMAN | Record. |
| Video includes a recording of the Band Desktop room, plus a walkthrough | LL item 4 (disqualifier) | script and shot list | NEEDS HUMAN | Record in Band Desktop itself. |
| Presentation and video explain design, cost, a bad result caught and the stage reached | PG Rubric | script, slides 4–6 | NEEDS HUMAN | Make the deck. |
| Form: title, short and long description, tags, cover, video, slides, repository | LL "Submission form" | `SUBMISSION_COPY.md` | NEEDS HUMAN | Fill the form. |
| Before submitting: fresh clone plus `harness check`; `--all --mode isolated`; RUN.md by hand plus the UI; read `room.json`; re-read mandates; skim for secrets | PG "Before you submit" #1–7 | done in this review (§1) | PASS | — |
| Submit the URL, presentation and video; keep the receipt | PG "Before you submit" #8 | — | NEEDS HUMAN | — |
| Deadline | PG "Schedule"; LL | Tue 6 Oct 06:59 UTC | NEEDS HUMAN | Submit well before. |
| Judging: Factory 50%, App 25%, Agent Teamwork 25% | PG Rubric; LL | — | — | Same weights in both sources. |

## 4. Disqualifier audit

| Disqualifier | Where it is stated | Finding |
|---|---|---|
| A mandate that names track-specific detail | LL; PG gate 4 | **Clear.** The organizers' vocabulary scan in `harness check` passes. A whole-word search of all four files found none of these terms: tablekeeper, reservation(s), restaurant(s), table(s), booking(s), book, diner(s), guest(s), menu, dinner, party, slot(s), cutoff, availability, seating, venue, opentable, pocketful, wallet, payment(s), endpoint, `/reservations`, `/_test`, `table_id`, `starts_at`, `party_size`, 404, 409, 422, `cutoff_passed`, `table_unavailable`, `data-testid`, "stage 1" or `stage-1`. The only "table" substrings are "testable" and "stable". "Seat" always means a Band seat. Generic engineering words do appear ("retries and replays", "concurrent writes"); they apply to any system. A line-by-line read agrees, and the architect mandate itself forbids encoding "any particular product's routes, types, APIs, field names or demo answers". |
| A video without the Band Desktop room recording | LL | **Open.** The video does not exist yet. The script makes the room recording central (0:15–1:55 and 3:30–4:05). |
| A service that does not start from a clean container | LL; PG gate 3 (stage 1) | **Clear** for all four stages: built from a fresh clone, started with no network, healthy in ≤ 1.4 s. |
| A failed gate 1 or 2 | PG | **Clear:** `harness check` ok. |
| Hand-built code | PG | **No evidence of it.** Every stage commit traces to a room task; post-run commits touch only `README.md`, `FACTORY.md`, `room.json` and `submission/`. |
| Code written to the tests | PG (enforced after close) | **No evidence of it.** The verifier's suites came from the spec text and are several times larger than the shipped checks. Rulings in the room cite spec lines, not test names. The organizers decide this. |

## 5. Discrepancies between sources

| # | PG says | LL says | Safer reading we follow |
|---|---|---|---|
| D1 | Only a `stage-1/` that does not start is an unranked entry; a later folder that does not start costs that stage and those above it | Lists "A service that does not start from a clean container" as a disqualifier, and "a service that doesn't start scores zero" | Every folder must start from a clean container. All four do. |
| D2 | The video shows "the room, a handoff between seats, and the result it produced". Use the presentation and video for design, cost, a bad result caught and the stage reached | The video must include "a recording of the BAND Desktop room that generated your solution, and a walkthrough" | Do all of it, and record the room in **Band Desktop**, not only the web console. |
| D3 | Autonomy: "no steering, approvals, debugging hints or reruns" | "no steering, approvals or reruns" | PG's stricter list. The room shows none. |
| D4 | Submissions close Mon Oct 5, 23:59 PDT | Deadline Oct 6, 2:59 PM SST | Not a conflict: both are 06:59 UTC on 6 Oct. "SST" here means Singapore time (UTC+8). |
| D5 | Bring your own model-provider access | Featherless credits or your own provider | No conflict. The seats used Claude Code with claude-opus-5-5. |
| D6 | Mandate file named after the seat, starting with `Harness:` and `Model:` | "each with a mandate file" | PG's stricter form. It is met. |
| D7 | "Write README.md and FACTORY.md yourself" | — | Read as "the team writes them; no tool generates them". The docs were drafted by the coordinator seat during the run and polished after the run. The owner should read and own the final wording before merging. |
| D8 | — (no formats given) | Form lists a cover image, video and slides; lablab's general guidance (unverified search summary) says 16:9 PNG/JPG, MP4 and PDF | Use those formats. |
| D9 | No video length | No video length seen in the screenshots | Keep it under 5 minutes. The script runs 4:20. |
| D10 | Dispatch = the only human input; judges compare the room log and git | — | The owner's dispatch went to the coordinator's own session, so `room.json` starts with the coordinator's RUN-START. FACTORY.md now says so. If the owner still has the exact dispatch text, adding it verbatim to FACTORY.md would let judges see the one human input. |
