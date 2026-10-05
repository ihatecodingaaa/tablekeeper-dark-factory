"""Helpers for the black-box HTTP tests: fixture data, a socket client, assertions."""
import datetime as dt
import http.client
import json

JSON_TYPE = "application/json; charset=utf-8"
PASSWORD = "correct horse"
WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def future_date(days_ahead: int = 30) -> str:
    """A local date far enough ahead that the cancellation cutoff never applies."""
    return (dt.date.today() + dt.timedelta(days=days_ahead)).isoformat()


def make_fixture() -> dict:
    return {
        "users": [
            {"id": "u_ada", "email": "ada@example.com", "password": PASSWORD,
             "display_name": "Ada"},
            {"id": "u_bob", "email": "bob@example.com", "password": PASSWORD,
             "display_name": "Bob"},
        ],
        "restaurants": [{
            "id": "r_anker",
            "name": "Zum Anker",
            "timezone": "Europe/Berlin",
            "slot_minutes": 30,
            "reservation_duration_minutes": 90,
            "cancellation_cutoff_minutes": 120,
            "opening_hours": [{"weekday": d, "opens": "12:00", "closes": "23:00"} for d in WEEK],
            "tables": [
                {"id": "t_1", "label": "1", "capacity": 2},
                {"id": "t_2", "label": "2", "capacity": 4},
            ],
        }],
        "reservations": [],
    }


def booking(table_id: str = "t_2", time: str = "19:00", party_size: int = 2,
            days_ahead: int = 30) -> dict:
    return {"restaurant_id": "r_anker", "table_id": table_id,
            "starts_at_local": f"{future_date(days_ahead)}T{time}", "party_size": party_size}


class Response:
    def __init__(self, status: int, headers: dict, raw: bytes):
        self.status = status
        self.headers = headers
        self.raw = raw

    def json(self):
        return json.loads(self.raw)

    def __repr__(self):
        return f"<Response {self.status} {self.raw[:300]!r}>"


class Client:
    """One fresh connection per request, so it is safe to share across threads."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def request(self, method, path, body=None, headers=None, raw=None, token=None, key=None):
        data = raw if raw is not None else (
            None if body is None else json.dumps(body).encode("utf-8"))
        hdrs = dict(headers or {})
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        if token is not None:
            hdrs["Authorization"] = f"Bearer {token}"
        if key is not None:
            hdrs["Idempotency-Key"] = key
        conn = http.client.HTTPConnection(self.host, self.port, timeout=15)
        try:
            conn.request(method, path, body=data, headers=hdrs)
            return read_response(conn)
        finally:
            conn.close()

    def login(self, email: str = "ada@example.com", password: str = PASSWORD) -> str:
        resp = self.request("POST", "/auth/login", {"email": email, "password": password})
        assert resp.status == 200, resp
        return resp.json()["token"]


def read_response(conn: http.client.HTTPConnection) -> Response:
    resp = conn.getresponse()
    return Response(resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read())


def assert_error(resp: Response, status: int, code: str) -> None:
    assert resp.status == status, resp
    assert resp.headers.get("content-type") == JSON_TYPE, resp.headers
    body = resp.json()
    assert set(body) == {"error"}, body
    assert body["error"]["code"] == code, body
    assert isinstance(body["error"]["message"], str) and body["error"]["message"], body
