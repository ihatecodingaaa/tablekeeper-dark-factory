# Tablekeeper stage 3: build and run

A restaurant reservation service: the JSON API plus a browser product for searching,
booking, and looking up or cancelling reservations, including joined tables for larger
parties. Stage 3 adds dated booking policies published by restaurant managers,
availability explanations, per-booking history and accepted terms, and recurring
reservations (series). It is Python 3.12 standard library plus the `tzdata` package,
packaged as one Docker image. Pages, styles, scripts and icons are served from the image,
and no runtime network access is needed: dependencies are installed while the image builds.

## Build and start

From this `stage-3/` folder:

```sh
docker build -t tablekeeper-stage-3 .
docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-stage-3
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

The grid follows whichever policy is in force for the searched date, so its times,
seat counts and the reasons a table is unavailable come from the server.

## Seed data

State starts empty. Load restaurants, tables (and optional `combinable` pairs and
`manager_user_ids`), users and reservations through the unauthenticated test endpoint:

```sh
curl -s -X POST http://localhost:8080/_test/reset \
  -H 'Content-Type: application/json' \
  -d '{"users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"},
                 {"id": "u_mia", "email": "mia@example.com", "password": "correct horse", "display_name": "Mia"}],
       "restaurants": [{"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin",
                        "slot_minutes": 30, "reservation_duration_minutes": 90,
                        "cancellation_cutoff_minutes": 120,
                        "opening_hours": [{"weekday": "thu", "opens": "18:00", "closes": "23:00"}],
                        "tables": [{"id": "t_1", "label": "1", "capacity": 2},
                                   {"id": "t_2", "label": "2", "capacity": 4}],
                        "combinable": [["t_1", "t_2"]],
                        "manager_user_ids": ["u_mia"]}],
       "reservations": []}'
```

Sign in as `ada@example.com` / `correct horse` to book. `mia@example.com` manages the
restaurant and may publish policies with `POST /restaurants/r_anker/policies`.

Stage-3 API additions: `GET|POST /restaurants/{id}/policies`,
`GET /availability?...&explain=true`, `GET /reservations/{ref}/history`,
`GET /reservations/{ref}/decision`, `POST /series` and `GET /series/{id}`.

`GET /_test/export` and `POST /_test/import` snapshot and restore the whole state. Import
accepts exports from the stage-1, stage-2 and stage-3 services. Signed-in browsers,
confirmation links and earlier booking retries keep working across it. State lives in
memory and does not survive a container restart.

## Tests

With Python 3.12+, from this `stage-3/` folder:

```sh
python -m pip install -r requirements.txt pytest playwright
python -m playwright install chromium
python -m pytest
```

- `tests/unit/` exercises the service core directly.
- `tests/http/` is black-box over sockets against the real server, started in-process
  on an ephemeral port. It covers series and the stage-3 routes. The upgrade test that
  imports a real stage-2 export runs only when the `stage-2/` folder sits beside this one.
- `tests/browser/` drives Chromium through every screen against the same in-process
  server, including the grid and lookup under a published policy.
