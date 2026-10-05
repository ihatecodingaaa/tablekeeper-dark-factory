# Tablekeeper stage 4: build and run

A restaurant reservation service: the JSON API plus a browser product for searching,
booking, and looking up or cancelling reservations, including joined tables for larger
parties, dated booking policies, per-booking history and recurring reservations. Stage 4
adds seating repairs after a table closure (preview, then apply) and amending a whole
recurring series. It also adds additive extras for guests and managers, under `/x/...`
and new screens; they never change an official response. It is Python 3.12 standard
library plus the `tzdata` package, packaged as one Docker image. Pages, styles, scripts and
icons are served from the image, and no runtime network access is needed: dependencies
are installed while the image builds.

## Build and start

From this `stage-4/` folder:

```sh
docker build -t tablekeeper-stage-4 .
docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-stage-4
```

The service listens on `0.0.0.0:$PORT` (default `8080`). It is ready when
`GET /health` returns `200 {"status": "ok"}`:

```sh
curl -s http://localhost:8080/health
```

Then open <http://localhost:8080/> in a browser.

| Route | Screen |
|---|---|
| `/` | Search and availability grid, Best Times, booking form and confirmation |
| `/signup` | Create an account |
| `/login` | Sign in |
| `/lookup` | Look up a reservation by reference, and cancel it |
| `/evening/{reference}` | My Evening: the booking, its guarantee, calendar, messages and preferences |
| `/passport` | My evenings: upcoming and past bookings, guarantees and default preferences |
| `/notifications` | Messages about your bookings |
| `/control-room` | Managers: the service day, slot pressure, guarantees and the message outbox |
| `/simulator` | Managers: rehearse a table closure on the real planner, then apply it |

The confirmation and lookup screens link to My Evening. After a seating repair, every
screen shows the booking's current tables.

## A demo world

With the container running, from this folder:

```sh
python3 demo/seed_demo.py --base http://localhost:8080
```

This resets the service and books a realistic week through the official API and `/x`.
It prints the demo accounts, which use a documented demo-only password, and the
references. `demo/README.md` walks through the screens.

## Seed data

`POST /_test/reset` loads restaurants, tables (with optional `combinable` pairs and
`manager_user_ids`), users and reservations. `GET /_test/export` and `POST /_test/import`
snapshot and restore the whole state. Import accepts exports from the stage-1, 2, 3 and 4
services; signed-in browsers, confirmation links and earlier retries keep working. State
lives in memory and does not survive a container restart.

Optional notification adapters are configured only through the environment
(`TK_SMTP_HOST`, `TK_SMTP_PORT`, `TK_SMTP_USER`, `TK_SMTP_PASSWORD`, `TK_SMTP_FROM`,
`TK_TELEGRAM_BOT_TOKEN`, `TK_TELEGRAM_CHAT_ID`). Without them, deliveries are simulated
locally and nothing leaves the container.

## Tests

With Python 3.12+, from this `stage-4/` folder:

```sh
python -m pip install -r requirements.txt pytest playwright
python -m playwright install chromium
python -m pytest
```

- `tests/unit/` and `tests/extras/` exercise the service core and the extras directly.
- `tests/http/` is black-box over sockets against the real server, started in-process
  on an ephemeral port. It covers replans, series amend and the earlier stages' API.
- `tests/browser/` and `tests/browser_x/` drive Chromium through every screen against the
  same in-process server, including an applied seating repair and the 375 px layout.
