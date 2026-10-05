# Tablekeeper stage 2: build and run

A restaurant reservation service: the JSON API plus a browser product for searching,
booking, and looking up or cancelling reservations, including joined tables for larger
parties. It is Python 3.12 standard library plus the `tzdata` package, packaged as one
Docker image. Pages, styles, scripts and icons are served from the image, and no runtime
network access is needed: dependencies are installed while the image builds.

## Build and start

From this `stage-2/` folder:

```sh
docker build -t tablekeeper-stage-2 .
docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-stage-2
```

The service listens on `0.0.0.0:$PORT` (default `8080`). It is ready when
`GET /health` returns `200 {"status": "ok"}`:

```sh
curl -s http://localhost:8080/health
```

Then open <http://localhost:8080/> in a browser.

| Route | Screen |
|---|---|
| `/` | Search and availability grid, booking form and confirmation |
| `/signup` | Create an account |
| `/login` | Sign in |
| `/lookup` | Look up a reservation by reference, and cancel it |

## Seed data

State starts empty. Load restaurants, tables (and optional `combinable` pairs), users
and reservations through the unauthenticated test endpoint:

```sh
curl -s -X POST http://localhost:8080/_test/reset \
  -H 'Content-Type: application/json' \
  -d '{"users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"}],
       "restaurants": [{"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin",
                        "slot_minutes": 30, "reservation_duration_minutes": 90,
                        "cancellation_cutoff_minutes": 120,
                        "opening_hours": [{"weekday": "thu", "opens": "18:00", "closes": "23:00"}],
                        "tables": [{"id": "t_1", "label": "1", "capacity": 2},
                                   {"id": "t_2", "label": "2", "capacity": 4}],
                        "combinable": [["t_1", "t_2"]]}],
       "reservations": []}'
```

Sign in as `ada@example.com` / `correct horse`, pick a Thursday and search.

`GET /_test/export` and `POST /_test/import` snapshot and restore the whole state. Import
also accepts an export from the stage-1 service, and signed-in browsers stay signed in
across it. State lives in memory and does not survive a container restart.

## Tests

With Python 3.12+, from this `stage-2/` folder:

```sh
python -m pip install -r requirements.txt pytest playwright
python -m playwright install chromium
python -m pytest
```

- `tests/unit/` exercises the service core directly.
- `tests/http/` is black-box over sockets against the real server, started in-process
  on an ephemeral port.
- `tests/browser/` drives Chromium through every screen against the same in-process
  server. It covers out-of-order searches, a table taken by another client, a lost
  booking response and its retry, export and import mid-session, and the layout at a
  375 px viewport.
