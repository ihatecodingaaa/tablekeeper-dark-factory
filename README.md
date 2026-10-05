# TABLEKEEPER

**Reservations that survive reality.**

Track: `tablekeeper` · Dark Factory (WeAreDevelopers hackathon) · built by a four-seat
autonomous agent factory in one Band room (see [`FACTORY.md`](FACTORY.md)).

Most booking products stop at "find a table, book it". Real evenings are messier: a
response is lost on a bad connection, two people grab the same table, the restaurant
changes its hours, a table breaks an hour before service, a deposit is taken and someone
asks what happened to their money. Tablekeeper is built around those moments.

- **For guests — "Protect the evening."** A booking is never duplicated by a retry, a lost
  response is recovered to the original confirmation, and if the restaurant has to move you,
  you are told what changed in plain language.
- **For restaurants — "Recover the night."** When a table becomes unavailable, Tablekeeper
  computes the provably best re-seating for every affected booking, shows it before anything
  changes, and applies it atomically without rewriting anyone's history or terms.

## What is in this repository

| Path | What it is |
|---|---|
| `stage-1/` | JSON API: idempotent, atomic bookings; DST-correct local times; atomic multi-booking moves; export/import |
| `stage-2/` | The browser product (search grid, booking, confirmation, lookup) with recovery from stale state and lost responses; combined tables |
| `stage-3/` | Effective-dated policies with accepted terms, revisions, truthful history, explanations, recurring agreements |
| `stage-4/` | Closure re-planning (exact optimizer, read-only preview, atomic apply), series amendments — plus the Tablekeeper product layer below |
| `mandates/` | One generic mandate per seat (harness and model named in each) |
| `FACTORY.md` | How the factory works, what it cost, how it catches bad work |
| `room.json` | The full Band room session of the judged run |

Each `stage-N/` folder is a complete service: the previous stage carried forward and
widened to the next official specification, accepted by an independent verifier before the
next stage began, and never modified afterwards.

## Run it

Every stage builds and runs the same way (Docker only; no network needed at run time):

```sh
cd stage-4
docker build -t tablekeeper-s4 .
docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-s4
# then open http://localhost:8080/
```

Each folder's `RUN.md` has the exact commands for that stage. To explore the full product
with realistic data, seed the demo world (standard-library Python, talks only to your
container):

```sh
python3 stage-4/demo/seed_demo.py --base http://localhost:8080
```

`stage-4/demo/README.md` lists the demo accounts and a guided walk-through.

## Test it

```sh
cd stage-4
python -m pip install -r requirements.txt pytest playwright
python -m playwright install chromium
python -m pytest                   # unit, HTTP, extras and Playwright browser tests
```

Official checks (from the kickoff package):

```sh
python -m harness run --track tablekeeper --repo <this repo> --all --mode isolated
```

## The four official stages (what each folder guarantees)

1. **Reservations API** — two confirmed bookings never overlap on a table, even with 50
   concurrent requests; `Idempotency-Key` replays return the original response byte-for-byte;
   restaurant-local times follow IANA rules through daylight-saving changes; several bookings
   move atomically; state exports and re-imports exactly, including sessions and receipts.
2. **Online booking** — a warm, accessible booking product; late search responses never
   overwrite newer ones; a taken table keeps your form and refreshes the grid; a lost response
   shows an honest "we couldn't confirm" state and a safe retry recovers the original
   reference; declared table pairs for larger parties.
3. **Policies, history and agreements** — managers publish dated policies; each booking keeps
   the terms it accepted; amendments adopt the terms of their new date; every change is in a
   truthful, ordered history; "why is this table unavailable?" explanations; recurring
   agreements with per-occurrence identity and exceptions.
4. **Seating repairs and series amendments** — an exact, deterministic optimizer re-seats every
   affected booking after a closure (fewest moved, then fewest empty seats, then a fixed
   preference order), previewed read-only and applied atomically; series clock-time changes in
   one atomic step.

## The Tablekeeper product layer (stage 4)

Additive features that never change an official response (they live under `/x/...` and on
their own screens) and work with **zero credentials and no internet**:

- **Tablekeeper Guarantee** — a simulated, finance-grade deposit / no-show protection layer:
  integer minor units only, idempotent transitions, an append-only ledger
  (`HELD → CAPTURED | RELEASED`, `CAPTURED → REFUNDED`), automatic release on cancellation, and a
  plain-language "What happened to my money?" timeline. Not real card processing.
- **My Evening** — the booking as an evening companion: time, party, tables, what changed if
  the restaurant re-seated you, preferences, guarantee, notifications, calendar and sharing.
- **Calendar companion** — Google Calendar link and a standards-based `.ics` download.
- **Notification hub** — in-app notifications for every guest-relevant event; optional e-mail
  (SMTP) and Telegram adapters send only when configured through environment variables, and
  otherwise a deterministic local outbox shows exactly what would be sent.
- **Guest preferences** — dietary needs, allergies, accessibility, occasion, seating; shown to
  the restaurant as "we'll do our best", never as a promise.
- **Best Times, Passport, shareable booking, recovery suggestions after a lost table.**
- **Operator Control Room** — today's service, capacity pressure, closures, policy in force,
  recent guest-impacting changes, guarantee settlement and the outbox.
- **Recovery Simulator** — pick a table and a window, see the impacted bookings, the exact
  repair the optimizer proposes (before → disruption → repair → after) and the messages
  guests would receive; applying it is a separate, explicit step through the official API.

Optional integrations (environment variables, all optional):
`TK_SMTP_HOST`, `TK_SMTP_PORT`, `TK_SMTP_USER`, `TK_SMTP_PASSWORD`, `TK_SMTP_FROM`,
`TK_TELEGRAM_BOT_TOKEN`, `TK_TELEGRAM_CHAT_ID`. Without them nothing leaves the container.

## Architecture (brief)

- Python 3.12 standard library HTTP server (threaded) plus `tzdata`; no framework, no database.
- One process-wide lock makes every operation serializable; idempotency check-and-store runs
  inside it; password hashing (scrypt) runs outside it.
- `service.py` holds the domain rules; `http_app.py` maps HTTP to it with one error envelope;
  the browser client is dependency-free JavaScript served from the image (no CDN, no web fonts).
- Export/import is a versioned, strictly validated JSON snapshot that each later stage upgrades.

## Accessibility and responsiveness

Visible labels and focus, keyboard-operable grid cells, state shown by text and shape (never
colour alone), reduced-motion support, and no horizontal page scrolling at 375 px or desktop
widths — each checked by browser tests.

## AI assistance

This code was written by AI coding agents (Claude Code) working as a coordinated factory in a
Band room; the human owner dispatched each run and did not edit the stage folders. See
`FACTORY.md` and `room.json`.
