"""End-to-end journey over HTTP: reset, login, book, replay, cancel, export, import (spec 3, 7, 8, 10)."""
from httpkit import JSON_TYPE, assert_error, booking, future_date, make_fixture

RESERVATION_FIELDS = {"reservation_id", "reference", "restaurant_id", "table_id", "party_size",
                      "status", "starts_at_local", "starts_at", "ends_at", "created_at"}


def slot_tables(client, date, time, party_size=2):
    resp = client.request(
        "GET", f"/availability?restaurant_id=r_anker&date={date}&party_size={party_size}")
    assert resp.status == 200, resp
    for slot in resp.json()["slots"]:
        if slot["starts_at_local"] == f"{date}T{time}":
            return slot["available_table_ids"]
    raise AssertionError(f"no {time} slot on {date}")


def test_full_journey_survives_export_and_import(client):
    date = future_date()
    token = client.login("ada@example.com")
    assert slot_tables(client, date, "19:00") == ["t_1", "t_2"]

    created = client.request("POST", "/reservations", booking("t_2", "19:00"), token=token,
                             key="journey-1")
    assert created.status == 201, created
    assert created.headers["content-type"] == JSON_TYPE
    original = created.json()
    assert RESERVATION_FIELDS <= set(original)
    assert original["status"] == "confirmed" and original["table_id"] == "t_2"
    ref = original["reference"]
    assert slot_tables(client, date, "19:00") == ["t_1"]

    replay = client.request("POST", "/reservations", booking("t_2", "19:00"), token=token,
                            key="journey-1")
    assert (replay.status, replay.json()) == (200, original)

    assert client.request("GET", f"/reservations/{ref}", token=token).json() == original
    listed = client.request("GET", "/reservations", token=token).json()["reservations"]
    assert [r["reference"] for r in listed] == [ref]

    cancelled = client.request("POST", f"/reservations/{ref}/cancel", token=token)
    assert cancelled.status == 200, cancelled
    assert cancelled.json()["status"] == "cancelled" and cancelled.json()["reference"] == ref
    again = client.request("POST", f"/reservations/{ref}/cancel", token=token)
    assert (again.status, again.json()) == (200, cancelled.json())
    assert slot_tables(client, date, "19:00") == ["t_1", "t_2"]

    # A replay still returns the original (confirmed) response after the cancel.
    replay = client.request("POST", "/reservations", booking("t_2", "19:00"), token=token,
                            key="journey-1")
    assert (replay.status, replay.json()) == (200, original)

    exported = client.request("GET", "/_test/export")
    assert exported.status == 200, exported
    document = exported.json()
    assert document["track"] == "tablekeeper" and document["format_version"] == 1
    assert isinstance(document["state"], dict)

    # Writes after the export do not change the exported document.
    later = client.request("POST", "/reservations", booking("t_1", "20:00"), token=token,
                           key="journey-2")
    assert later.status == 201, later

    # A fresh fixture wipes everything, including the old token.
    assert client.request("POST", "/_test/reset", make_fixture()).status == 204
    assert_error(client.request("GET", "/reservations", token=token), 401, "unauthenticated")

    for _ in range(2):  # importing twice restores, never duplicates
        resp = client.request("POST", "/_test/import", document)
        assert resp.status == 204 and resp.raw == b"", resp

    assert client.request("GET", f"/reservations/{ref}", token=token).json() == cancelled.json()
    listed = client.request("GET", "/reservations", token=token).json()["reservations"]
    assert [r["reference"] for r in listed] == [ref]
    replay = client.request("POST", "/reservations", booking("t_2", "19:00"), token=token,
                            key="journey-1")
    assert (replay.status, replay.json()) == (200, original)
    assert client.login("ada@example.com")


def test_invalid_import_leaves_state_unchanged(client, ada):
    created = client.request("POST", "/reservations", booking(), token=ada, key="keep-1")
    assert created.status == 201
    for document in ({}, {"track": "pocketful", "format_version": 1, "state": {}},
                     {"track": "tablekeeper", "format_version": 2, "state": {}},
                     {"track": "tablekeeper", "format_version": True, "state": {}},
                     {"track": "tablekeeper", "format_version": 1}):
        assert_error(client.request("POST", "/_test/import", document), 422, "validation_failed")
    listed = client.request("GET", "/reservations", token=ada).json()["reservations"]
    assert [r["reference"] for r in listed] == [created.json()["reference"]]


def test_other_users_reservation_is_404(client, ada, bob):
    created = client.request("POST", "/reservations", booking(), token=ada, key="mine")
    ref = created.json()["reference"]
    assert_error(client.request("GET", f"/reservations/{ref}", token=bob), 404, "not_found")
    assert_error(client.request("POST", f"/reservations/{ref}/cancel", token=bob),
                 404, "not_found")
    assert_error(client.request("PATCH", f"/reservations/{ref}", {"party_size": 3}, token=bob),
                 404, "not_found")


def test_amend_and_move_over_http(client, ada):
    first = client.request("POST", "/reservations", booking("t_1", "19:00"), token=ada, key="m1")
    second = client.request("POST", "/reservations", booking("t_2", "19:00"), token=ada, key="m2")
    ref1, ref2 = first.json()["reference"], second.json()["reference"]

    amended = client.request("PATCH", f"/reservations/{ref1}", {"starts_at_local":
                             f"{future_date()}T20:30"}, token=ada)
    assert amended.status == 200, amended
    assert amended.json()["reference"] == ref1
    assert amended.json()["reservation_id"] == first.json()["reservation_id"]

    swap = {"moves": [{"reference": ref1, "table_id": "t_2", "starts_at_local":
                       f"{future_date()}T19:00"},
                      {"reference": ref2, "table_id": "t_1"}]}
    moved = client.request("POST", "/reservation-moves", swap, token=ada, key="swap")
    assert moved.status == 201, moved
    tables = [r["table_id"] for r in moved.json()["reservations"]]
    assert tables == ["t_2", "t_1"]
    replay = client.request("POST", "/reservation-moves", swap, token=ada, key="swap")
    assert (replay.status, replay.json()) == (200, moved.json())
