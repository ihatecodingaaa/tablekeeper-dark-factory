"""Amending recurring reservations over HTTP (stage 4 'Amend recurring reservations'; S4-R6, D3)."""
import datetime as dt
import threading

import pytest

from httpkit import assert_error
from s3httpkit import day, local, next_transition, offset_at, policy_body, s3_fixture, series_body

ANCHOR_DAY = 20


@pytest.fixture
def s4(client):
    assert client.request("POST", "/_test/reset", s3_fixture()).status == 204
    return client


@pytest.fixture
def ada(s4):
    return s4.login("ada@example.com")


@pytest.fixture
def bob(s4):
    return s4.login("bob@example.com")


@pytest.fixture
def mia(s4):
    return s4.login("mia@example.com")


def book(client, token, start_local, table_id="t_2", restaurant="r_anker", key=None, party_size=2):
    body = {"restaurant_id": restaurant, "table_id": table_id, "party_size": party_size,
            "starts_at_local": start_local}
    resp = client.request("POST", "/reservations", body, token=token,
                          key=key or f"book-{restaurant}-{table_id}-{start_local}")
    assert resp.status == 201, resp
    return resp.json()


def make_series(client, token, count=4, start=None, table_id="t_2", restaurant="r_anker"):
    anchor = book(client, token, start or local(day(ANCHOR_DAY), "19:00"), table_id, restaurant)
    resp = client.request("POST", "/series", series_body(anchor["reference"], count=count),
                          token=token, key="adopt")
    assert resp.status == 201, resp
    return resp.json()


def amend(client, token, sid, key="amend-1", **body):
    return client.request("POST", f"/series/{sid}/amend", body, token=token, key=key)


def current(client, token, sid):
    return client.request("GET", f"/series/{sid}", token=token).json()


def starts(view):
    return [o["reservation"]["starts_at_local"] for o in view["occurrences"]]


def test_amend_moves_eligible_occurrences_on_their_scheduled_dates(s4, ada):
    series = make_series(s4, ada, count=4)
    resp = amend(s4, ada, series["series_id"], expected_revision=1, from_index=1, local_time="20:00")
    assert resp.status == 201, resp
    view = resp.json()
    assert view["revision"] == 2
    assert starts(view) == [local(day(ANCHOR_DAY), "19:00")] + [
        local(day(ANCHOR_DAY + 7 * i), "20:00") for i in (1, 2, 3)]
    assert [o["exception"] for o in view["occurrences"]] == [False] * 4
    assert [o["reservation"]["revision"] for o in view["occurrences"]] == [1, 2, 2, 2]
    assert [o["reference"] for o in view["occurrences"]] == [o["reference"] for o in series["occurrences"]]
    history = s4.request("GET", f"/reservations/{view['occurrences'][1]['reference']}/history",
                         token=ada).json()["entries"]
    assert [e["event"] for e in history] == ["created", "changed"]
    assert history[-1]["changes"] == [{"field": "starts_at_local",
                                       "from": local(day(ANCHOR_DAY + 7), "19:00"),
                                       "to": local(day(ANCHOR_DAY + 7), "20:00")}]
    assert view["occurrences"][2]["reservation"]["table_ids"] == ["t_2"]


def test_exceptions_and_cancelled_occurrences_are_left_alone(s4, ada):
    series = make_series(s4, ada, count=4)
    sid, occ = series["series_id"], series["occurrences"]
    s4.request("PATCH", f"/reservations/{occ[1]['reference']}", {"party_size": 3}, token=ada)
    s4.request("POST", f"/reservations/{occ[2]['reference']}/cancel", token=ada)
    before = current(s4, ada, sid)
    assert before["revision"] == 3
    resp = amend(s4, ada, sid, expected_revision=3, from_index=0, local_time="20:30")
    assert resp.status == 201, resp
    after = resp.json()
    assert after["revision"] == 4
    assert starts(after)[0] == local(day(ANCHOR_DAY), "20:30")
    assert starts(after)[1] == starts(before)[1] and starts(after)[2] == starts(before)[2]
    assert starts(after)[3] == local(day(ANCHOR_DAY + 21), "20:30")
    assert [o["exception"] for o in after["occurrences"]] == [False, True, False, False]


def test_all_no_op_and_empty_eligible_sets_succeed_without_changes(s4, ada):
    series = make_series(s4, ada, count=3)
    sid = series["series_id"]
    resp = amend(s4, ada, sid, key="noop", expected_revision=1, from_index=0, local_time="19:00")
    assert resp.status == 201 and resp.json()["revision"] == 1
    assert [o["reservation"]["revision"] for o in resp.json()["occurrences"]] == [1, 1, 1]
    s4.request("POST", f"/reservations/{series['occurrences'][2]['reference']}/cancel", token=ada)
    resp = amend(s4, ada, sid, key="empty", expected_revision=2, from_index=2, local_time="21:00")
    assert resp.status == 201 and resp.json()["revision"] == 2


def test_stale_revision_comes_before_any_booking_check(s4, ada):
    series = make_series(s4, ada)
    assert_error(amend(s4, ada, series["series_id"], expected_revision=5, from_index=0,
                       local_time="03:00"), 409, "stale_revision")


@pytest.mark.parametrize("change", [
    {"expected_revision": 0}, {"expected_revision": "1"}, {"expected_revision": True},
    {"from_index": -1}, {"from_index": "0"}, {"from_index": True}, {"from_index": 1.0},
    {"local_time": "8:00"}, {"local_time": "24:00"}, {"local_time": "20:60"}, {"local_time": "2000"},
    {"local_time": 2000}, {"local_time": "20:00:00"},
])
def test_invalid_amend_fields_are_422(s4, ada, change):
    series = make_series(s4, ada)
    body = {"expected_revision": 1, "from_index": 0, "local_time": "20:00"}
    body.update(change)
    resp = s4.request("POST", f"/series/{series['series_id']}/amend", body, token=ada, key="bad")
    assert_error(resp, 422, "validation_failed")


def test_from_index_beyond_the_series_is_422_after_ownership(s4, ada, bob):
    series = make_series(s4, ada, count=3)
    assert_error(amend(s4, ada, series["series_id"], expected_revision=1, from_index=3,
                       local_time="20:00"), 422, "validation_failed")
    assert_error(amend(s4, bob, series["series_id"], expected_revision=1, from_index=3,
                       local_time="20:00"), 404, "not_found")
    assert_error(amend(s4, ada, "ser_missing", expected_revision=1, from_index=0,
                       local_time="20:00"), 404, "not_found")


def test_amend_needs_a_token_and_a_key(s4, ada):
    series = make_series(s4, ada)
    path = f"/series/{series['series_id']}/amend"
    body = {"expected_revision": 1, "from_index": 0, "local_time": "20:00"}
    assert_error(s4.request("POST", path, body, key="k"), 401, "unauthenticated")
    assert_error(s4.request("POST", path, body, token=ada), 400, "missing_idempotency_key")
    assert_error(s4.request("POST", path, raw=b"[]", token=ada, key="k"), 400, "malformed_request")
    assert_error(s4.request("GET", path, token=ada), 405, "method_not_allowed")


def test_booking_rule_errors_leave_everything_unchanged(s4, ada):
    series = make_series(s4, ada, count=3)
    sid = series["series_id"]
    before = current(s4, ada, sid)
    assert_error(amend(s4, ada, sid, key="early", expected_revision=1, from_index=0, local_time="16:00"),
                 422, "outside_opening_hours")
    assert_error(amend(s4, ada, sid, key="grid", expected_revision=1, from_index=0, local_time="19:10"),
                 422, "not_on_slot_grid")
    assert current(s4, ada, sid) == before


def test_first_non_occupancy_error_in_index_order_wins(s4, ada, mia, bob):
    series = make_series(s4, ada, count=3)
    sid = series["series_id"]
    # Index 2 falls under a policy whose hours end at 21:00; index 1 collides with Bob at 21:00.
    late = policy_body(day(ANCHOR_DAY + 14), opening_hours=[
        {"weekday": d, "opens": "17:00", "closes": "21:00"}
        for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")])
    assert s4.request("POST", "/restaurants/r_anker/policies", late, token=mia, key="p").status == 201
    book(s4, bob, local(day(ANCHOR_DAY + 7), "21:00"))
    assert_error(amend(s4, ada, sid, key="mixed", expected_revision=1, from_index=0, local_time="21:00"),
                 422, "outside_opening_hours")


def test_an_occupancy_conflict_is_409_and_atomic(s4, ada, bob):
    series = make_series(s4, ada, count=3)
    sid = series["series_id"]
    before = current(s4, ada, sid)
    book(s4, bob, local(day(ANCHOR_DAY + 14), "20:30"))
    assert_error(amend(s4, ada, sid, key="clash", expected_revision=1, from_index=0, local_time="20:00"),
                 409, "table_unavailable")
    assert current(s4, ada, sid) == before


def test_replay_returns_the_original_response(s4, ada):
    series = make_series(s4, ada, count=3)
    sid = series["series_id"]
    first = amend(s4, ada, sid, key="once", expected_revision=1, from_index=0, local_time="20:00")
    assert first.status == 201
    s4.request("PATCH", f"/reservations/{series['occurrences'][1]['reference']}", {"party_size": 3},
               token=ada)
    again = amend(s4, ada, sid, key="once", expected_revision=1, from_index=0, local_time="20:00")
    assert (again.status, again.json()) == (200, first.json())
    assert current(s4, ada, sid)["revision"] == 3
    assert_error(amend(s4, ada, sid, key="once", expected_revision=1, from_index=0, local_time="21:00"),
                 409, "idempotency_key_reuse")


def test_concurrent_amends_from_one_revision_change_at_most_once(s4, ada):
    series = make_series(s4, ada, count=3)
    sid = series["series_id"]
    times = ["20:00", "20:30", "21:00", "18:30", "18:00", "17:30"]
    barrier = threading.Barrier(len(times))
    results = [None] * len(times)

    def worker(i):
        barrier.wait()
        results[i] = amend(s4, ada, sid, key=f"race-{i}", expected_revision=1, from_index=0,
                           local_time=times[i])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(times))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    winners = [r for r in results if r.status == 201]
    assert len(winners) == 1, [r.status for r in results]
    for resp in results:
        if resp.status != 201:
            assert_error(resp, 409, "stale_revision")
    assert current(s4, ada, sid)["revision"] == 2


def test_amend_across_fall_back_keeps_local_time_on_each_date(s4, ada):
    change = next_transition("Europe/Berlin", "fall")
    first = change - dt.timedelta(days=7)
    series = make_series(s4, ada, count=3, start=local(first, "19:00"))
    resp = amend(s4, ada, series["series_id"], expected_revision=1, from_index=0, local_time="20:30")
    assert resp.status == 201, resp
    for i, occurrence in enumerate(resp.json()["occurrences"]):
        date = first + dt.timedelta(days=7 * i)
        assert occurrence["reservation"]["starts_at"] == (
            f"{local(date, '20:30')}:00{offset_at('Europe/Berlin', date, '20:30')}")


def test_amend_works_after_export_and_import(s4, ada):
    series = make_series(s4, ada, count=3)
    document = s4.request("GET", "/_test/export").json()
    assert s4.request("POST", "/_test/reset", s3_fixture()).status == 204
    assert s4.request("POST", "/_test/import", document).status == 204
    resp = amend(s4, ada, series["series_id"], expected_revision=1, from_index=1, local_time="20:00")
    assert resp.status == 201, resp
    assert starts(resp.json())[1:] == [local(day(ANCHOR_DAY + 7 * i), "20:00") for i in (1, 2)]
