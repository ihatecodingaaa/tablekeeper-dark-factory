"""New stage-3 routes: policies, history, decision and explain over HTTP (S3-R2, S3-R6, S3-R7)."""
import pytest

from httpkit import JSON_TYPE, assert_error
from s3httpkit import day, local, policy_body, s3_fixture


@pytest.fixture
def s3(client):
    assert client.request("POST", "/_test/reset", s3_fixture()).status == 204
    return client


@pytest.fixture
def tokens(s3):
    return {name: s3.login(f"{name}@example.com") for name in ("ada", "bob", "mia")}


def booked(s3, token, start=None):
    body = {"restaurant_id": "r_anker", "table_id": "t_2", "party_size": 2,
            "starts_at_local": start or local(day(20), "19:00")}
    resp = s3.request("POST", "/reservations", body, token=token, key="booked")
    assert resp.status == 201, resp
    return resp.json()


# -- policies ------------------------------------------------------------------------


def test_policy_list_is_public_and_starts_empty(s3):
    resp = s3.request("GET", "/restaurants/r_anker/policies")
    assert resp.status == 200 and resp.headers["content-type"] == JSON_TYPE
    assert resp.json() == {"policies": []}
    assert_error(s3.request("GET", "/restaurants/r_missing/policies"), 404, "not_found")


def test_publishing_checks_token_then_body_then_restaurant_then_manager(s3, tokens):
    body = policy_body(day(10))
    assert_error(s3.request("POST", "/restaurants/r_anker/policies", body, key="p"), 401,
                 "unauthenticated")
    assert_error(s3.request("POST", "/restaurants/r_anker/policies", raw=b"{nope",
                            token=tokens["mia"], key="p"), 400, "malformed_request")
    assert_error(s3.request("POST", "/restaurants/r_missing/policies", body, token=tokens["mia"],
                            key="p"), 404, "not_found")
    assert_error(s3.request("POST", "/restaurants/r_anker/policies", body, token=tokens["ada"],
                            key="p"), 403, "forbidden")
    assert_error(s3.request("POST", "/restaurants/r_anker/policies", body, token=tokens["mia"]),
                 400, "missing_idempotency_key")


def test_manager_publishes_and_the_list_shows_it(s3, tokens):
    body = policy_body(day(10), slot_minutes=15, note="ignored")
    resp = s3.request("POST", "/restaurants/r_anker/policies", body, token=tokens["mia"], key="p1")
    assert resp.status == 201, resp
    published = resp.json()
    assert published["policy_version"] == 1 and published["slot_minutes"] == 15
    assert "note" not in published
    replay = s3.request("POST", "/restaurants/r_anker/policies", body, token=tokens["mia"], key="p1")
    assert (replay.status, replay.json()) == (200, published)
    assert s3.request("GET", "/restaurants/r_anker/policies").json() == {"policies": [published]}
    # The ordinary restaurant detail keeps the fixture's own configuration.
    assert s3.request("GET", "/restaurants/r_anker").json()["slot_minutes"] == 30


def test_policy_routes_reject_other_methods(s3):
    resp = s3.request("DELETE", "/restaurants/r_anker/policies")
    assert_error(resp, 405, "method_not_allowed")
    assert set(resp.headers["allow"].split(", ")) == {"GET", "POST"}


# -- history and decision ----------------------------------------------------------------


@pytest.mark.parametrize("suffix", ["history", "decision"])
def test_history_and_decision_are_404_for_anyone_but_the_owner(s3, tokens, suffix):
    ref = booked(s3, tokens["ada"])["reference"]
    path = f"/reservations/{ref}/{suffix}"
    assert s3.request("GET", path, token=tokens["ada"]).status == 200
    assert_error(s3.request("GET", path), 404, "not_found")
    assert_error(s3.request("GET", path, headers={"Authorization": "Bearer not-a-token"}), 404,
                 "not_found")
    assert_error(s3.request("GET", path, headers={"Authorization": "Basic abc"}), 404, "not_found")
    assert_error(s3.request("GET", path, token=tokens["bob"]), 404, "not_found")
    assert_error(s3.request("GET", path, token=tokens["mia"]), 404, "not_found")  # managers too
    assert_error(s3.request("GET", f"/reservations/NOPE0000/{suffix}", token=tokens["ada"]), 404,
                 "not_found")
    assert_error(s3.request("POST", path, token=tokens["ada"]), 405, "method_not_allowed")


def test_history_records_create_change_and_cancel(s3, tokens):
    ada = tokens["ada"]
    ref = booked(s3, ada)["reference"]
    s3.request("PATCH", f"/reservations/{ref}", {"table_id": "t_3"}, token=ada)
    s3.request("PATCH", f"/reservations/{ref}", {"table_id": "t_3"}, token=ada)  # no-op
    s3.request("POST", f"/reservations/{ref}/cancel", token=ada)
    history = s3.request("GET", f"/reservations/{ref}/history", token=ada).json()
    assert history["reference"] == ref
    entries = history["entries"]
    assert [e["seq"] for e in entries] == [1, 2, 3]
    assert [e["event"] for e in entries] == ["created", "changed", "cancelled"]
    assert entries[1]["changes"] == [{"field": "table_id", "from": "t_2", "to": "t_3"}]
    assert entries[2]["changes"] == []
    assert [e["revision"] for e in entries] == [1, 2, 3]
    decision = s3.request("GET", f"/reservations/{ref}/decision", token=ada).json()
    assert decision == {"reference": ref, "revision": 3,
                        "accepted_terms": entries[-1]["accepted_terms"]}


# -- explain ---------------------------------------------------------------------------


def test_explain_passes_through_the_availability_query(s3):
    base = f"/availability?restaurant_id=r_anker&date={day(20)}&party_size=3"
    plain = s3.request("GET", base).json()
    assert all("explain" not in slot for slot in plain["slots"])
    explained = s3.request("GET", base + "&explain=true").json()
    first = explained["slots"][0]
    assert [e["table_id"] for e in first["explain"]] == ["t_1", "t_2", "t_3"]
    assert first["explain"][0]["rules"] == [{"rule": "capacity", "holds": False},
                                            {"rule": "no_overlap", "holds": True}]
    for value in ("false", "1", "", "True"):
        assert_error(s3.request("GET", f"{base}&explain={value}"), 422, "validation_failed")
