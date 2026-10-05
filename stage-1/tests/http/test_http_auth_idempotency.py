"""Bearer authentication and Idempotency-Key handling over HTTP (spec 6, 7; R1, R6)."""
import json

import pytest

from httpkit import PASSWORD, assert_error, booking

PROTECTED = [
    ("GET", "/reservations", None),
    ("POST", "/reservations", {"restaurant_id": "r_anker"}),
    ("GET", "/reservations/ABC123", None),
    ("PATCH", "/reservations/ABC123", {"party_size": 2}),
    ("POST", "/reservations/ABC123/cancel", None),
    ("POST", "/reservation-moves", {"moves": []}),
]
BAD_AUTH = [
    pytest.param(None, id="no-header"),
    pytest.param("", id="empty"),
    pytest.param("Basic YWRhOmNvcnJlY3QgaG9yc2U=", id="basic-scheme"),
    pytest.param("Bearer", id="scheme-only"),
    pytest.param("Bearer ", id="scheme-blank"),
    pytest.param("Bearer not-a-real-token", id="unknown-token"),
    pytest.param("Token abc", id="other-scheme"),
]


@pytest.mark.parametrize("authorization", BAD_AUTH)
@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_protected_routes_need_a_valid_bearer_token(client, method, path, body, authorization):
    headers = {"Idempotency-Key": "k-auth"}
    if authorization is not None:
        headers["Authorization"] = authorization
    assert_error(client.request(method, path, body, headers=headers), 401, "unauthenticated")


def test_bearer_scheme_is_case_insensitive(client, ada):
    resp = client.request("GET", "/reservations", headers={"Authorization": f"bearer {ada}"})
    assert resp.status == 200, resp


def test_signup_then_login_issue_working_tokens(client):
    resp = client.request("POST", "/auth/signup", {"email": "cy@example.com",
                                                    "password": PASSWORD,
                                                    "display_name": "Cy"})
    assert resp.status == 201, resp
    signed_up = resp.json()
    assert signed_up["display_name"] == "Cy" and signed_up["user_id"] and signed_up["token"]
    login = client.request("POST", "/auth/login", {"email": "cy@example.com",
                                                    "password": PASSWORD})
    assert login.status == 200, login
    assert login.json()["user_id"] == signed_up["user_id"]
    for token in (signed_up["token"], login.json()["token"]):
        assert client.request("GET", "/reservations", token=token).json() == {"reservations": []}


def test_login_failures_are_401(client):
    resp = client.request("POST", "/auth/login", {"email": "ada@example.com",
                                                   "password": "wrong password"})
    assert_error(resp, 401, "unauthenticated")
    resp = client.request("POST", "/auth/login", {"email": "nobody@example.com",
                                                   "password": PASSWORD})
    assert_error(resp, 401, "unauthenticated")


def test_duplicate_signup_is_409_email_taken(client):
    resp = client.request("POST", "/auth/signup", {"email": "ada@example.com",
                                                    "password": PASSWORD,
                                                    "display_name": "Ada 2"})
    assert_error(resp, 409, "email_taken")


@pytest.mark.parametrize("path,body", [
    ("/reservations", booking()),
    ("/reservation-moves", {"moves": [{"reference": "ABC123", "table_id": "t_1"}]}),
])
@pytest.mark.parametrize("key", [None, ""])
def test_missing_or_empty_idempotency_key_is_400(client, ada, path, body, key):
    headers = {"Authorization": f"Bearer {ada}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    resp = client.request("POST", path, body, headers=headers)
    assert_error(resp, 400, "missing_idempotency_key")


@pytest.mark.parametrize("path,body", [
    ("/reservations", booking()),
    ("/reservation-moves", {"moves": [{"reference": "ABC123", "table_id": "t_1"}]}),
])
def test_idempotency_key_longer_than_255_is_422(client, ada, path, body):
    resp = client.request("POST", path, body, token=ada, key="k" * 256)
    assert_error(resp, 422, "validation_failed")


def test_idempotency_key_of_255_characters_is_accepted(client, ada):
    resp = client.request("POST", "/reservations", booking(), token=ada, key="k" * 255)
    assert resp.status == 201, resp


def test_replay_returns_200_with_identical_body(client, ada):
    first = client.request("POST", "/reservations", booking(), token=ada, key="k-replay")
    assert first.status == 201, first
    again = client.request("POST", "/reservations", booking(), token=ada, key="k-replay")
    assert again.status == 200, again
    assert again.json() == first.json()
    assert len(client.request("GET", "/reservations", token=ada).json()["reservations"]) == 1


def test_replay_ignores_key_order_and_whitespace(client, ada):
    body = booking()
    first = client.request("POST", "/reservations", body, token=ada, key="k-order")
    assert first.status == 201, first
    reordered = json.dumps(dict(reversed(list(body.items()))), indent=3)
    again = client.request("POST", "/reservations", raw=reordered.encode(), token=ada,
                           key="k-order")
    assert again.status == 200, again
    assert again.json() == first.json()


def test_same_key_different_body_is_409_even_if_new_body_is_invalid(client, ada):
    assert client.request("POST", "/reservations", booking(), token=ada,
                          key="k-reuse").status == 201
    changed = booking(table_id="t_1")
    assert_error(client.request("POST", "/reservations", changed, token=ada, key="k-reuse"),
                 409, "idempotency_key_reuse")
    assert_error(client.request("POST", "/reservations", {"party_size": "x"}, token=ada,
                                key="k-reuse"), 409, "idempotency_key_reuse")


def test_key_after_failed_first_use_is_a_fresh_first_use(client, ada):
    bad = booking()
    bad["party_size"] = 0
    assert_error(client.request("POST", "/reservations", bad, token=ada, key="k-fail"),
                 422, "validation_failed")
    resp = client.request("POST", "/reservations", booking(), token=ada, key="k-fail")
    assert resp.status == 201, resp


def test_keys_are_scoped_per_user(client, ada, bob):
    first = client.request("POST", "/reservations", booking("t_2", "19:00"), token=ada,
                           key="shared-key")
    second = client.request("POST", "/reservations", booking("t_1", "19:00"), token=bob,
                            key="shared-key")
    assert first.status == 201 and second.status == 201, (first, second)
    assert first.json()["reference"] != second.json()["reference"]


def test_same_key_on_another_path_is_not_a_replay(client, ada):
    created = client.request("POST", "/reservations", booking(), token=ada, key="k-path")
    assert created.status == 201
    move = {"moves": [{"reference": created.json()["reference"], "table_id": "t_1"}]}
    resp = client.request("POST", "/reservation-moves", move, token=ada, key="k-path")
    assert resp.status == 201, resp
    assert resp.json()["reservations"][0]["table_id"] == "t_1"
