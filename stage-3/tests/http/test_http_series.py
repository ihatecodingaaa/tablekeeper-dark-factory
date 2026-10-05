"""Recurring reservations over HTTP (stage 3 'Recurring reservations'; S3-R8, S3-CONTRACT C3/C4)."""
import copy
import datetime as dt

import pytest

from httpkit import assert_error
from s3kit import (day, local, next_transition, offset_at, policy_body, s3_fixture,
                   series_body)

ANCHOR_DAY = 20  # days ahead: far outside every cutoff


@pytest.fixture
def s3(client):
    assert client.request("POST", "/_test/reset", s3_fixture()).status == 204
    return client


@pytest.fixture
def ada(s3):
    return s3.login("ada@example.com")


@pytest.fixture
def bob(s3):
    return s3.login("bob@example.com")


@pytest.fixture
def mia(s3):
    return s3.login("mia@example.com")


def book(client, token, start_local, table_id="t_2", party_size=2, restaurant="r_anker", key=None,
         table_ids=None):
    body = {"restaurant_id": restaurant, "starts_at_local": start_local, "party_size": party_size}
    if table_ids:
        body["table_ids"] = table_ids
    else:
        body["table_id"] = table_id
    resp = client.request("POST", "/reservations", body, token=token,
                          key=key or f"book-{restaurant}-{start_local}-{table_id}-{table_ids}")
    assert resp.status == 201, resp
    return resp.json()


def adopt(client, token, reference, key="series-1", **kwargs):
    return client.request("POST", "/series", series_body(reference, **kwargs), token=token, key=key)


def references(client, token):
    return sorted(r["reference"] for r in client.request("GET", "/reservations", token=token)
                  .json()["reservations"])


# -- creation ----------------------------------------------------------------------


def test_weekly_series_books_every_occurrence(s3, ada):
    start = day(ANCHOR_DAY)
    anchor = book(s3, ada, local(start, "19:00"))
    resp = adopt(s3, ada, anchor["reference"], count=4, interval_weeks=1)
    assert resp.status == 201, resp
    series = resp.json()
    assert set(series) == {"series_id", "revision", "interval_weeks", "occurrences"}
    assert series["revision"] == 1 and series["interval_weeks"] == 1
    occurrences = series["occurrences"]
    assert [o["index"] for o in occurrences] == [0, 1, 2, 3]
    assert all(o["exception"] is False for o in occurrences)
    assert occurrences[0]["reference"] == anchor["reference"]
    refs = [o["reference"] for o in occurrences]
    assert len(set(refs)) == 4
    for i, occurrence in enumerate(occurrences):
        reservation = occurrence["reservation"]
        assert reservation["reference"] == occurrence["reference"]
        assert reservation["starts_at_local"] == local(day(ANCHOR_DAY + 7 * i), "19:00")
        assert reservation["table_ids"] == ["t_2"] and reservation["party_size"] == 2
        assert reservation["status"] == "confirmed" and reservation["revision"] == 1
    # Occurrence zero is the anchor itself, unchanged.
    current_anchor = s3.request("GET", f"/reservations/{anchor['reference']}", token=ada).json()
    assert occurrences[0]["reservation"] == current_anchor
    for field in ("reservation_id", "created_at", "starts_at", "ends_at", "revision", "accepted_terms"):
        assert current_anchor[field] == anchor[field]
    # Generated occurrences are ordinary reservations of the anchor's owner and occupy their tables.
    assert references(s3, ada) == sorted(refs)
    slots = s3.request("GET", f"/availability?restaurant_id=r_anker&date={day(ANCHOR_DAY + 14)}"
                              "&party_size=2").json()["slots"]
    at_seven = next(s for s in slots if s["starts_at_local"].endswith("T19:00"))
    assert "t_2" not in at_seven["available_table_ids"]
    history = s3.request("GET", f"/reservations/{refs[2]}/history", token=ada).json()
    assert [e["event"] for e in history["entries"]] == ["created"]


def test_interval_weeks_spaces_the_occurrences(s3, ada):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "18:30"), table_id="t_1")
    resp = adopt(s3, ada, anchor["reference"], count=3, interval_weeks=3)
    assert resp.status == 201, resp
    starts = [o["reservation"]["starts_at_local"] for o in resp.json()["occurrences"]]
    assert starts == [local(day(ANCHOR_DAY + 21 * i), "18:30") for i in range(3)]


def test_a_pair_anchor_repeats_the_same_pair(s3, ada):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "20:00"), table_ids=["t_2", "t_1"], party_size=5)
    resp = adopt(s3, ada, anchor["reference"], count=2)
    assert resp.status == 201, resp
    second = resp.json()["occurrences"][1]["reservation"]
    assert second["table_ids"] == ["t_1", "t_2"] and "table_id" not in second
    assert second["party_size"] == 5


def test_weekly_series_across_fall_back_keeps_the_local_clock_time(s3, ada):
    change = next_transition("Europe/Berlin", "fall")
    first = change - dt_days(7)
    anchor = book(s3, ada, local(first, "19:00"))
    resp = adopt(s3, ada, anchor["reference"], count=3)
    assert resp.status == 201, resp
    for i, occurrence in enumerate(resp.json()["occurrences"]):
        date = first + dt_days(7 * i)
        reservation = occurrence["reservation"]
        assert reservation["starts_at_local"] == local(date, "19:00")
        assert reservation["starts_at"] == f"{local(date, '19:00')}:00{offset_at('Europe/Berlin', date, '19:00')}"
    offsets = {o["reservation"]["starts_at"][-6:] for o in resp.json()["occurrences"]}
    assert len(offsets) == 2  # same wall-clock time, different UTC offsets


def test_repeated_local_time_takes_the_first_occurrence(s3, ada):
    change = next_transition("America/New_York", "fall")
    anchor = book(s3, ada, local(change - dt_days(7), "01:30"), table_id="n_1", restaurant="r_night")
    resp = adopt(s3, ada, anchor["reference"], count=2)
    assert resp.status == 201, resp
    repeated = resp.json()["occurrences"][1]["reservation"]
    assert repeated["starts_at"] == (
        f"{local(change, '01:30')}:00{offset_at('America/New_York', change, '01:30', fold=0)}")


def test_nonexistent_local_time_rejects_the_whole_series(s3, ada):
    change = next_transition("America/New_York", "spring")
    anchor = book(s3, ada, local(change - dt_days(14), "02:30"), table_id="n_1", restaurant="r_night")
    before = references(s3, ada)
    assert_error(adopt(s3, ada, anchor["reference"], count=4, key="dst-gap"), 422, "invalid_local_time")
    assert references(s3, ada) == before
    # Nothing was claimed: the same key works for a valid series afterwards.
    resp = adopt(s3, ada, anchor["reference"], count=2, key="dst-gap")
    assert resp.status == 201, resp


# -- failures and their precedence --------------------------------------------------


def test_first_failing_occurrence_decides_the_error(s3, ada, bob, mia):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"))
    # Index 1 collides with Bob; index 2 onwards falls outside a later policy's hours.
    book(s3, bob, local(day(ANCHOR_DAY + 7), "19:00"))
    late = policy_body(day(ANCHOR_DAY + 14), opening_hours=[
        {"weekday": d, "opens": "20:00", "closes": "23:00"}
        for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")])
    assert s3.request("POST", "/restaurants/r_anker/policies", late, token=mia, key="p1").status == 201
    assert_error(adopt(s3, ada, anchor["reference"], count=4, key="a"), 409, "table_unavailable")
    # With index 1 free, index 2 is now the first failure.
    s3.request("POST", f"/reservations/{references(s3, bob)[0]}/cancel", token=bob)
    assert_error(adopt(s3, ada, anchor["reference"], count=4, key="b"), 422, "outside_opening_hours")


def test_each_occurrence_uses_its_own_dates_policy(s3, ada, mia):
    longer = policy_body(day(ANCHOR_DAY + 14), reservation_duration_minutes=120,
                         capacities={"t_1": 2, "t_2": 6, "t_3": 2})
    published = s3.request("POST", "/restaurants/r_anker/policies", longer, token=mia, key="p1")
    assert published.status == 201, published
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"))
    resp = adopt(s3, ada, anchor["reference"], count=3)
    assert resp.status == 201, resp
    terms = [o["reservation"]["accepted_terms"] for o in resp.json()["occurrences"]]
    assert [t["policy_version"] for t in terms] == [0, 0, 1]
    assert terms[2]["reservation_duration_minutes"] == 120 and terms[2]["capacities"]["t_2"] == 6
    last = resp.json()["occurrences"][2]["reservation"]
    assert last["ends_at"].startswith(local(day(ANCHOR_DAY + 14), "21:00"))


def test_capacity_from_a_later_policy_can_reject_an_occurrence(s3, ada, mia):
    smaller = policy_body(day(ANCHOR_DAY + 7), capacities={"t_1": 2, "t_2": 1, "t_3": 2})
    assert s3.request("POST", "/restaurants/r_anker/policies", smaller, token=mia,
                      key="p1").status == 201
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"))
    assert_error(adopt(s3, ada, anchor["reference"], count=2), 422, "party_exceeds_capacity")


def test_anchor_inside_its_cutoff_is_409(s3, ada):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"), table_id="s_1", restaurant="r_strict")
    assert_error(adopt(s3, ada, anchor["reference"], count=2), 409, "cutoff_passed")


def test_cancelled_anchor_is_409(s3, ada):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"))
    s3.request("POST", f"/reservations/{anchor['reference']}/cancel", token=ada)
    assert_error(adopt(s3, ada, anchor["reference"], count=2), 409, "reservation_cancelled")


def test_a_reservation_joins_at_most_one_series(s3, ada):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"))
    created = adopt(s3, ada, anchor["reference"], count=3).json()
    assert_error(adopt(s3, ada, anchor["reference"], count=2, key="again"), 409, "already_in_series")
    generated = created["occurrences"][1]["reference"]
    assert_error(adopt(s3, ada, generated, count=2, key="nested"), 409, "already_in_series")


def test_unknown_or_someone_elses_anchor_is_404(s3, ada, bob):
    theirs = book(s3, bob, local(day(ANCHOR_DAY), "19:00"))
    assert_error(adopt(s3, ada, theirs["reference"], count=2), 404, "not_found")
    assert_error(adopt(s3, ada, "NOPE0000", count=2, key="k2"), 404, "not_found")


@pytest.mark.parametrize("change", [
    {"count": 1}, {"count": 13}, {"count": "4"}, {"count": True}, {"count": 2.0},
    {"interval_weeks": 0}, {"interval_weeks": 5}, {"interval_weeks": False},
    {"anchor_reference": 12345}, {"anchor_reference": None},
])
def test_invalid_series_fields_are_422(s3, ada, change):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"))
    body = series_body(anchor["reference"], count=2, interval_weeks=1)
    body.update(change)
    assert_error(s3.request("POST", "/series", body, token=ada, key="bad"), 422, "validation_failed")


@pytest.mark.parametrize("field", ["anchor_reference", "count", "interval_weeks"])
def test_missing_series_fields_are_422(s3, ada, field):
    body = series_body("ABC123", count=2, interval_weeks=1)
    del body[field]
    assert_error(s3.request("POST", "/series", body, token=ada, key="missing"), 422, "validation_failed")


def test_series_validation_precedes_the_anchor_lookup(s3, ada):
    body = series_body("NOPE0000", count=99)
    assert_error(s3.request("POST", "/series", body, token=ada, key="order"), 422, "validation_failed")


def test_series_needs_a_token_and_an_idempotency_key(s3, ada):
    body = series_body("ABC123", count=2)
    assert_error(s3.request("POST", "/series", body, key="k"), 401, "unauthenticated")
    assert_error(s3.request("POST", "/series", body, token=ada), 400, "missing_idempotency_key")
    assert_error(s3.request("POST", "/series", body, token=ada, key="k" * 256), 422,
                 "validation_failed")
    assert_error(s3.request("POST", "/series", raw=b"[]", token=ada, key="k"), 400,
                 "malformed_request")


def test_failure_leaves_no_partial_series(s3, ada, bob):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"))
    book(s3, bob, local(day(ANCHOR_DAY + 21), "19:00"))  # index 3 collides
    before = references(s3, ada)
    assert_error(adopt(s3, ada, anchor["reference"], count=5), 409, "table_unavailable")
    assert references(s3, ada) == before
    slots = s3.request("GET", f"/availability?restaurant_id=r_anker&date={day(ANCHOR_DAY + 7)}"
                              "&party_size=2").json()["slots"]
    assert "t_2" in next(s for s in slots if s["starts_at_local"].endswith("T19:00"))[
        "available_table_ids"]


# -- reading, counters and replays --------------------------------------------------


def test_only_the_owner_can_read_a_series(s3, ada, bob):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"))
    created = adopt(s3, ada, anchor["reference"], count=2).json()
    sid = created["series_id"]
    assert s3.request("GET", f"/series/{sid}", token=ada).json() == created
    assert_error(s3.request("GET", f"/series/{sid}", token=bob), 404, "not_found")
    assert_error(s3.request("GET", f"/series/{sid}"), 404, "not_found")
    assert_error(s3.request("GET", f"/series/{sid}", headers={"Authorization": "Bearer nope"}),
                 404, "not_found")
    assert_error(s3.request("GET", "/series/ser_missing", token=ada), 404, "not_found")


def test_exceptions_and_series_revision_follow_individual_changes(s3, ada):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"))
    created = adopt(s3, ada, anchor["reference"], count=4).json()
    sid, occ = created["series_id"], created["occurrences"]

    def state():
        view = s3.request("GET", f"/series/{sid}", token=ada).json()
        return view["revision"], [o["exception"] for o in view["occurrences"]]

    # A real individual change: exception, revision + 1.
    patched = s3.request("PATCH", f"/reservations/{occ[1]['reference']}", {"party_size": 3}, token=ada)
    assert patched.status == 200, patched
    assert state() == (2, [False, True, False, False])
    # A no-op changes nothing.
    s3.request("PATCH", f"/reservations/{occ[2]['reference']}", {"party_size": 2}, token=ada)
    assert state() == (2, [False, True, False, False])
    # A failed change changes nothing.
    failed = s3.request("PATCH", f"/reservations/{occ[2]['reference']}", {"party_size": 99}, token=ada)
    assert failed.status == 422
    assert state() == (2, [False, True, False, False])
    # Cancelling: revision + 1, no exception; a repeat cancel does nothing.
    s3.request("POST", f"/reservations/{occ[2]['reference']}/cancel", token=ada)
    assert state() == (3, [False, True, False, False])
    s3.request("POST", f"/reservations/{occ[2]['reference']}/cancel", token=ada)
    assert state() == (3, [False, True, False, False])
    # One moves batch changing two occurrences: both exceptions, revision + 1 once.
    moves = {"moves": [{"reference": occ[0]["reference"], "table_id": "t_3"},
                       {"reference": occ[3]["reference"], "table_id": "t_3"}]}
    moved = s3.request("POST", "/reservation-moves", moves, token=ada, key="move-1")
    assert moved.status == 201, moved
    assert state() == (4, [True, True, False, True])
    # A failed batch changes nothing.
    bad = {"moves": [{"reference": occ[1]["reference"], "party_size": 99}]}
    assert s3.request("POST", "/reservation-moves", bad, token=ada, key="move-2").status == 422
    assert state() == (4, [True, True, False, True])


def test_cancelling_the_anchor_keeps_its_siblings(s3, ada):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"))
    created = adopt(s3, ada, anchor["reference"], count=3).json()
    s3.request("POST", f"/reservations/{anchor['reference']}/cancel", token=ada)
    view = s3.request("GET", f"/series/{created['series_id']}", token=ada).json()
    assert [o["reservation"]["status"] for o in view["occurrences"]] == [
        "cancelled", "confirmed", "confirmed"]
    assert [o["reference"] for o in view["occurrences"]] == [
        o["reference"] for o in created["occurrences"]]


def test_replay_returns_the_original_response_after_changes(s3, ada):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"))
    first = adopt(s3, ada, anchor["reference"], count=3, key="replay")
    assert first.status == 201
    occ = first.json()["occurrences"]
    s3.request("PATCH", f"/reservations/{occ[1]['reference']}", {"party_size": 4}, token=ada)
    again = adopt(s3, ada, anchor["reference"], count=3, key="replay")
    assert (again.status, again.json()) == (200, first.json())
    view = s3.request("GET", f"/series/{first.json()['series_id']}", token=ada).json()
    assert view["revision"] == 2  # the replay changed no counter
    assert_error(adopt(s3, ada, anchor["reference"], count=4, key="replay"), 409,
                 "idempotency_key_reuse")


def test_series_survive_export_and_import(s3, ada):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"))
    created = adopt(s3, ada, anchor["reference"], count=3, key="exported")
    sid = created.json()["series_id"]
    occ = created.json()["occurrences"]
    s3.request("PATCH", f"/reservations/{occ[1]['reference']}", {"party_size": 3}, token=ada)
    before = s3.request("GET", f"/series/{sid}", token=ada).json()
    document = s3.request("GET", "/_test/export").json()
    assert s3.request("POST", "/_test/reset", s3_fixture()).status == 204
    assert s3.request("POST", "/_test/import", document).status == 204
    assert s3.request("GET", f"/series/{sid}", token=ada).json() == before
    replay = adopt(s3, ada, anchor["reference"], count=3, key="exported")
    assert (replay.status, replay.json()) == (200, created.json())
    # The hooks keep working on imported series.
    s3.request("POST", f"/reservations/{occ[2]['reference']}/cancel", token=ada)
    after = s3.request("GET", f"/series/{sid}", token=ada).json()
    assert after["revision"] == before["revision"] + 1
    assert_error(adopt(s3, ada, occ[2]["reference"], count=2, key="nested"), 409,
                 "reservation_cancelled")


def test_import_rejects_inconsistent_series(s3, ada):
    anchor = book(s3, ada, local(day(ANCHOR_DAY), "19:00"))
    adopt(s3, ada, anchor["reference"], count=2)
    document = s3.request("GET", "/_test/export").json()
    broken = copy.deepcopy(document)
    broken["state"]["series"][0]["occurrences"][1]["reference"] = "ZZZZZZZZ"
    assert_error(s3.request("POST", "/_test/import", broken), 422, "validation_failed")
    # The live state is untouched by the rejected import.
    assert len(s3.request("GET", "/reservations", token=ada).json()["reservations"]) == 2


def dt_days(n):
    return dt.timedelta(days=n)
