# Tablekeeper stage 1: build and run

A restaurant reservation HTTP API. Python 3.12 standard library plus the `tzdata`
package, packaged as a single Docker image. No runtime network access is needed:
dependencies are installed while the image builds.

## Build and start

From this `stage-1/` folder:

```sh
docker build -t tablekeeper-stage-1 .
docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-stage-1
```

The service listens on `0.0.0.0:$PORT` (default `8080`) and is ready when
`GET /health` returns `200 {"status": "ok"}`:

```sh
curl -s http://localhost:8080/health
```

## Seed data

State starts empty. Load restaurants, tables, users and reservations with the
unauthenticated test endpoint:

```sh
curl -s -X POST http://localhost:8080/_test/reset \
  -H 'Content-Type: application/json' \
  -d '{"users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"}],
       "restaurants": [{"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin",
                        "slot_minutes": 30, "reservation_duration_minutes": 90,
                        "cancellation_cutoff_minutes": 120,
                        "opening_hours": [{"weekday": "thu", "opens": "18:00", "closes": "23:00"}],
                        "tables": [{"id": "t_1", "label": "1", "capacity": 2}]}],
       "reservations": []}'
```

`GET /_test/export` and `POST /_test/import` snapshot and restore the whole state.
State lives in memory and does not survive a container restart.

## Tests

With Python 3.12+ and `pytest` installed, from this `stage-1/` folder:

```sh
python -m pip install -r requirements.txt pytest
python -m pytest
```

- `tests/unit/` exercises the service core directly.
- `tests/http/` is black-box: it starts the real HTTP server in-process on an
  ephemeral port and talks to it over sockets, including concurrent requests.
