"""Stage 2 'Existing clients after an upgrade' and rulings S2-R4/S2-R5.

The stage-1 export is produced at test time by the frozen stage-1 service in a
subprocess (both stages use the package name `tablekeeper`), so no recorded
credentials are committed.
"""
import copy
import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

from tk_unit import Clock, DATE, api_error, assert_error, fixture, restaurant
from tablekeeper.service import Service

STAGE_1 = pathlib.Path(__file__).resolve().parents[3] / "stage-1"

_SCRIPT = textwrap.dedent("""
    import datetime as dt, json, sys
    sys.path.insert(0, sys.argv[1])
    from tablekeeper.service import Service
    clock = lambda: dt.datetime(2026, 9, 20, 10, 0, tzinfo=dt.timezone.utc)
    svc = Service(clock=clock)
    fx = json.loads(sys.argv[2])
    svc.reset(fx)
    token = svc.login({"email": "ada@example.com", "password": "correct horse"})["token"]
    ada = svc.authenticate("Bearer " + token)
    create_body = {"restaurant_id": "r_anker", "table_id": "t_2",
                   "starts_at_local": "%(date)sT19:00", "party_size": 4}
    _, created = svc.create_reservation(ada, "k-create", create_body)
    gone_body = {"restaurant_id": "r_anker", "table_id": "t_1",
                 "starts_at_local": "%(date)sT21:00", "party_size": 2}
    _, gone = svc.create_reservation(ada, "k-gone", gone_body)
    svc.cancel_reservation(ada, gone["reference"])
    move_body = {"moves": [{"reference": created["reference"], "table_id": "t_3"}]}
    _, moved = svc.move_reservations(ada, "k-move", move_body)
    print(json.dumps({"export": svc.export_state(), "token": token,
                      "create_body": create_body, "created": created,
                      "gone": gone, "move_body": move_body, "moved": moved}))
""") % {"date": DATE}


@pytest.fixture(scope="module")
def stage1():
    if not (STAGE_1 / "tablekeeper" / "service.py").is_file():
        pytest.skip("frozen stage-1/ folder not present next to stage-2/")
    out = subprocess.run([sys.executable, "-c", _SCRIPT, str(STAGE_1), json.dumps(fixture())],
                         capture_output=True, text=True, check=True, cwd=str(STAGE_1))
    data = json.loads(out.stdout)
    assert data["export"]["state"]["schema"] == 1
    return data


def upgraded(stage1, clock=None):
    svc = Service(clock=clock or Clock())
    svc.import_state(copy.deepcopy(stage1["export"]))
    return svc


def test_stage_1_export_imports(stage1):
    svc = upgraded(stage1)
    assert svc.list_restaurants()["restaurants"][0]["id"] == "r_anker"
    assert svc.get_restaurant("r_anker")["combinable"] == []


def test_token_issued_by_stage_1_still_authenticates(stage1):
    svc = upgraded(stage1)
    assert svc.authenticate("Bearer " + stage1["token"]) == "u_ada"
    assert svc.login({"email": "ada@example.com", "password": "correct horse"})["user_id"] == "u_ada"


def test_stage_1_replays_are_byte_exact(stage1):
    svc = upgraded(stage1)
    status, body = svc.create_reservation("u_ada", "k-create", stage1["create_body"])
    assert status == 200 and body == stage1["created"]
    assert "table_ids" not in body and body["table_id"] == "t_2"
    assert json.dumps(body, sort_keys=True) == json.dumps(stage1["created"], sort_keys=True)
    status, body = svc.move_reservations("u_ada", "k-move", stage1["move_body"])
    assert status == 200 and body == stage1["moved"]
    assert "table_ids" not in body["reservations"][0]
    assert_error(api_error(svc.create_reservation, "u_ada", "k-create",
                           dict(stage1["create_body"], party_size=3)), 409, "idempotency_key_reuse")


def test_current_state_reads_use_stage_2_shape(stage1):
    svc = upgraded(stage1)
    ref = stage1["created"]["reference"]
    current = svc.get_reservation("u_ada", ref)
    assert current["table_ids"] == ["t_3"] and current["table_id"] == "t_3"
    for field in ("reservation_id", "reference", "created_at", "starts_at", "ends_at", "status"):
        assert current[field] == stage1["moved"]["reservations"][0][field]
    gone = svc.get_reservation("u_ada", stage1["gone"]["reference"])
    assert gone["status"] == "cancelled" and gone["table_ids"] == ["t_1"]
    listed = svc.list_reservations("u_ada")["reservations"]
    assert all("table_ids" in r for r in listed) and len(listed) == 2


def test_imported_bookings_keep_occupancy_and_can_be_adopted(stage1):
    svc = upgraded(stage1)
    slot = next(s for s in svc.availability({"restaurant_id": ["r_anker"], "date": [DATE],
                                             "party_size": ["2"]})["slots"]
                if s["starts_at_local"].endswith("19:00"))
    assert slot["available_table_ids"] == ["t_1", "t_2"]          # t_3 holds the moved booking
    assert {"table_ids": ["t_3"], "capacity": 6} not in slot["available_options"]
    ref = stage1["created"]["reference"]
    amended = svc.amend_reservation("u_ada", ref, {"table_ids": ["t_2"], "party_size": 3})
    assert amended["table_ids"] == ["t_2"] and amended["party_size"] == 3
    assert svc.cancel_reservation("u_ada", ref)["status"] == "cancelled"
    # The original replay is still the stage-1 body even after adoption.
    assert svc.create_reservation("u_ada", "k-create", stage1["create_body"]) == (200, stage1["created"])


def test_failed_stage_1_key_is_free_and_new_keys_work(stage1):
    svc = upgraded(stage1)
    status, out = svc.create_reservation("u_ada", "k-new", {
        "restaurant_id": "r_anker", "table_ids": ["t_1"], "starts_at_local": f"{DATE}T18:00",
        "party_size": 2})
    assert status == 201 and out["table_ids"] == ["t_1"]
    assert out["reference"] not in {stage1["created"]["reference"], stage1["gone"]["reference"]}


def test_stage_2_export_round_trip(stage1):
    svc = upgraded(stage1)
    document = svc.export_state()
    assert document["format_version"] == 1 and document["track"] == "tablekeeper"
    assert document["state"]["schema"] == 2
    again = Service(clock=Clock())
    again.import_state(json.loads(json.dumps(document)))
    assert again.export_state() == document
    assert again.create_reservation("u_ada", "k-create", stage1["create_body"]) == (200, stage1["created"])
    assert again.authenticate("Bearer " + stage1["token"]) == "u_ada"


def test_stage_2_export_with_pairs_round_trips(clock):
    rest = dict(restaurant(), combinable=[["t_2", "t_1"]])
    svc = Service(clock=clock)
    svc.reset(fixture(restaurants=[rest]))
    token = svc.login({"email": "ada@example.com", "password": "correct horse"})["token"]
    ada = svc.authenticate("Bearer " + token)
    data = {"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"],
            "starts_at_local": f"{DATE}T19:00", "party_size": 5}
    _, first = svc.create_reservation(ada, "pk", data)
    document = svc.export_state()
    target = Service(clock=clock)
    target.import_state(json.loads(json.dumps(document)))
    assert target.export_state() == document
    assert target.create_reservation(ada, "pk", data) == (200, first)
    assert target.get_reservation(ada, first["reference"])["table_ids"] == ["t_2", "t_1"]


def _stage2_document(clock):
    rest = dict(restaurant(), combinable=[["t_1", "t_2"]])
    svc = Service(clock=clock)
    svc.reset(fixture(restaurants=[rest]))
    ada = svc.authenticate("Bearer " + svc.login({"email": "ada@example.com",
                                                   "password": "correct horse"})["token"])
    svc.create_reservation(ada, "a", {"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"],
                                      "starts_at_local": f"{DATE}T19:00", "party_size": 5})
    svc.create_reservation(ada, "b", {"restaurant_id": "r_anker", "table_id": "t_3",
                                      "starts_at_local": f"{DATE}T19:00", "party_size": 5})
    return svc.export_state()


def _mutations(document):
    def edit(fn):
        doc = copy.deepcopy(document)
        fn(doc["state"])
        return doc

    def pair_res(state):
        return next(r for r in state["reservations"] if len(r["table_ids"]) == 2)

    def single_res(state):
        return next(r for r in state["reservations"] if len(r["table_ids"]) == 1)

    return [
        edit(lambda s: s.update(schema=3)),
        edit(lambda s: s.update(schema="2")),
        edit(lambda s: pair_res(s).update(table_ids=["t_1", "t_3"])),        # undeclared pair
        edit(lambda s: pair_res(s).update(table_ids=["t_1", "t_2", "t_3"])),
        edit(lambda s: pair_res(s).update(table_id="t_1")),                  # table_id on a pair
        edit(lambda s: single_res(s).pop("table_id")),                       # single without table_id
        edit(lambda s: single_res(s).update(table_id="t_1")),                # mismatch
        edit(lambda s: single_res(s).pop("table_ids")),                      # stage-2 needs table_ids
        edit(lambda s: s["restaurants"][0].update(combinable=[["t_1", "t_9"]])),
    ]


def test_invalid_stage_2_imports_are_422_and_change_nothing(clock):
    document = _stage2_document(clock)
    target = Service(clock=clock)
    target.import_state(copy.deepcopy(document))
    before = target.export_state()
    for bad in _mutations(document):
        assert_error(api_error(target.import_state, bad), 422, "validation_failed")
        assert target.export_state() == before


def test_stage_1_schema_document_with_table_ids_is_rejected(stage1):
    doc = copy.deepcopy(stage1["export"])
    doc["state"]["reservations"][0]["table_ids"] = ["t_1", "t_2"]
    doc["state"]["reservations"][0].pop("table_id")
    svc = Service(clock=Clock())
    assert_error(api_error(svc.import_state, doc), 422, "validation_failed")
