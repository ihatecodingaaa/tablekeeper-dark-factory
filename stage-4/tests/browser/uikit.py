"""Shared data and helpers for the Playwright browser tests."""
import atexit
import datetime as dt
import http.client
import json

from playwright.sync_api import expect, sync_playwright

PASSWORD = "correct horse"
_PLAYWRIGHT = None
_BROWSER = None


def shared_browser():
    """One Chromium per test process. Several test folders (browser, browser_x) need a
    browser, and the sync API cannot run two Playwright instances in one thread."""
    global _PLAYWRIGHT, _BROWSER
    if _BROWSER is None:
        _PLAYWRIGHT = sync_playwright().start()
        _BROWSER = _PLAYWRIGHT.chromium.launch()
        atexit.register(_close_browser)
    return _BROWSER


def _close_browser():
    if _BROWSER is not None:
        _BROWSER.close()
    if _PLAYWRIGHT is not None:
        _PLAYWRIGHT.stop()


def sign_in(page, email="ada@example.com", password=PASSWORD):
    page.goto("/login")
    page.get_by_test_id("login-email").fill(email)
    page.get_by_test_id("login-password").fill(password)
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("current-user")).to_be_visible()


def search(page, date, party_size=2, restaurant="r_anker"):
    page.get_by_test_id("restaurant-select").select_option(restaurant)
    page.get_by_test_id("date-input").fill(date)
    page.get_by_test_id("party-size-input").fill(str(party_size))
    page.get_by_test_id("search-button").click()
WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def future_date(days_ahead: int = 30) -> str:
    return (dt.date.today() + dt.timedelta(days=days_ahead)).isoformat()


def open_hafen_date() -> str:
    """A future date the harbour restaurant is open (any day but Monday)."""
    day = dt.date.today() + dt.timedelta(days=31)
    if day.weekday() == 0:
        day += dt.timedelta(days=1)
    return day.isoformat()


def closed_date() -> str:
    """A future Monday: the fixture's harbour restaurant is closed on Mondays."""
    day = dt.date.today() + dt.timedelta(days=30)
    while day.weekday() != 0:
        day += dt.timedelta(days=1)
    return day.isoformat()


def make_fixture() -> dict:
    every_day = [{"weekday": d, "opens": "17:00", "closes": "22:00"} for d in WEEK]
    return {
        "users": [
            {"id": "u_ada", "email": "ada@example.com", "password": PASSWORD, "display_name": "Ada"},
            {"id": "u_bob", "email": "bob@example.com", "password": PASSWORD, "display_name": "Bob"},
            {"id": "u_mia", "email": "mia@example.com", "password": PASSWORD, "display_name": "Mia"},
        ],
        "restaurants": [
            {
                "id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin",
                "slot_minutes": 30, "reservation_duration_minutes": 90,
                "cancellation_cutoff_minutes": 120, "opening_hours": every_day,
                "tables": [
                    {"id": "t_1", "label": "1", "capacity": 2},
                    {"id": "t_2", "label": "2", "capacity": 4},
                    {"id": "t_3", "label": "3", "capacity": 2},
                    {"id": "t_garden", "label": "Garden", "capacity": 6},
                ],
                "combinable": [["t_1", "t_2"], ["t_2", "t_3"]],
                "manager_user_ids": ["u_mia"],
            },
            {
                "id": "r_hafen", "name": "Hafenblick", "timezone": "America/New_York",
                "slot_minutes": 60, "reservation_duration_minutes": 120,
                "cancellation_cutoff_minutes": 60,
                "opening_hours": [{"weekday": d, "opens": "18:00", "closes": "23:00"}
                                  for d in WEEK if d != "mon"],
                "tables": [
                    {"id": "h_window", "label": "Window", "capacity": 2},
                    {"id": "h_bar", "label": "Bar", "capacity": 3},
                ],
            },
            {
                "id": "r_strict", "name": "Strenge Stube", "timezone": "Europe/Berlin",
                "slot_minutes": 30, "reservation_duration_minutes": 90,
                "cancellation_cutoff_minutes": 60 * 24 * 3650, "opening_hours": every_day,
                "tables": [{"id": "s_1", "label": "1", "capacity": 4}],
            },
        ],
        "reservations": [],
    }


class Api:
    """A plain JSON client used to arrange and check state around the browser."""

    def __init__(self, base_url: str):
        host_port = base_url.split("//", 1)[1]
        self.host, port = host_port.split(":")
        self.port = int(port)

    def call(self, method, path, body=None, token=None, key=None):
        headers = {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if key:
            headers["Idempotency-Key"] = key
        conn = http.client.HTTPConnection(self.host, self.port, timeout=15)
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
        finally:
            conn.close()

    def reset(self, fixture=None):
        status, _ = self.call("POST", "/_test/reset", fixture or make_fixture())
        assert status == 204

    def login(self, email="ada@example.com"):
        status, body = self.call("POST", "/auth/login", {"email": email, "password": PASSWORD})
        assert status == 200, body
        return body

    def book(self, token, table_id="t_2", time="19:00", party_size=2, restaurant="r_anker",
             key="api-booking", table_ids=None):
        body = {"restaurant_id": restaurant, "starts_at_local": f"{future_date()}T{time}",
                "party_size": party_size}
        if table_ids:
            body["table_ids"] = table_ids
        else:
            body["table_id"] = table_id
        status, data = self.call("POST", "/reservations", body, token=token, key=key)
        assert status == 201, data
        return data

    def reservations(self, token):
        status, body = self.call("GET", "/reservations", token=token)
        assert status == 200
        return body["reservations"]
