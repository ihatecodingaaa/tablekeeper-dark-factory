"""Stage 3 import of stage-1/2/3 exports (spec 'Recurring reservations' last paragraph,
S3-R3, S3-R6, S3-R11). Earlier exports are produced at test time by the frozen
stage-1/ and stage-2/ services in subprocesses (same package name)."""
import copy
import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

from s3kit import DATE, POLICY0_TERMS, Clock, managed, policy, terms_of
from tk_unit import api_error, assert_error, fixture, restaurant
from tablekeeper.service import Service

ROOT = pathlib.Path(__file__).resolve().parents[3]

_SCRIPT = textwrap.dedent("""
    import datetime as dt, json, sys
    sys.path.insert(0, sys.argv[1])
    from tablekeeper.service import Service
    svc = Service(clock=lambda: dt.datetime(2026, 9, 20, 10, 0, tzinfo=dt.timezone.utc))
    svc.reset(json.loads(sys.argv[2]))
    token = svc.login({"email": "ada@example.com", "password": "correct horse"})["token"]
    ada = svc.authenticate("Bearer " + token)
    bodies = json.loads(sys.argv[3])
    out = {"token": token, "responses": []}
    for key, body in bodies:
        out["responses"].append(svc.create_reservation(ada, key, body)[1])
    svc.cancel_reservation(ada, out["responses"][-1]["reference"])
    out["export"] = svc.export_state()
    print(json.dumps(out))
""")


def single(at, table="t_2", party=4):
    return {"restaurant_id": "r_anker", "table_id": table, "starts_at_local": f"{DATE}T{at}",
            "party_size": party}


def produce(stage, rest, bodies):
    folder = ROOT / stage
    if not (folder / "tablekeeper" / "service.py").is_file():
        pytest.skip(f"frozen {stage}/ folder not present")
    proc = subprocess.run([sys.executable, "-c", _SCRIPT, str(folder),
                           json.dumps(fixture(restaurants=[rest])), json.dumps(bodies)],
                          capture_output=True, text=True, check=True, cwd=str(folder))
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def stage1():
    return produce("stage-1", restaurant(), [["k1", single("19:00")], ["k2", single("21:00", "t_1", 2)]])


@pytest.fixture(scope="module")
def stage2():
    rest = dict(restaurant(), combinable=[["t_1", "t_2"]])
    pair = {"restaurant_id": "r_anker", "table_ids": ["t_2", "t_1"],
            "starts_at_local": f"{DATE}T19:00", "party_size": 5}
    return produce("stage-2", rest, [["k1", pair], ["k2", single("21:00", "t_3", 2)]])


def imported(data):
    svc = Service(clock=Clock())
    svc.import_state(copy.deepcopy(data["export"]))
    return svc


@pytest.mark.parametrize("stage", ["stage1", "stage2"])
def test_earlier_exports_upgrade_to_revision_1_under_policy_0(request, stage):
    data = request.getfixturevalue(stage)
    svc = imported(data)
    assert svc.authenticate("Bearer " + data["token"]) == "u_ada"
    kept, gone = data["responses"]
    current = svc.get_reservation("u_ada", kept["reference"])
    assert current["revision"] == 1 and current["accepted_terms"] == POLICY0_TERMS
    for field in ("reservation_id", "reference", "created_at", "starts_at", "ends_at", "party_size"):
        assert current[field] == kept[field]
    (created,) = svc.reservation_history("u_ada", kept["reference"])["entries"]
    assert created["event"] == "created" and created["at"] == kept["created_at"]
    assert created["revision"] == 1 and created["accepted_terms"] == POLICY0_TERMS
    gone_entries = svc.reservation_history("u_ada", gone["reference"])["entries"]
    assert [(e["event"], e["revision"]) for e in gone_entries] == [("created", 1), ("cancelled", 1)]
    assert svc.reservation_decision("u_ada", gone["reference"])["revision"] == 1


@pytest.mark.parametrize("stage", ["stage1", "stage2"])
def test_earlier_replays_stay_byte_exact(request, stage):
    data = request.getfixturevalue(stage)
    svc = imported(data)
    first = data["responses"][0]
    body = data["export"]["state"]["idempotency"][0]["body"]
    status, again = svc.create_reservation("u_ada", "k1", json.loads(body))
    assert status == 200 and again == first
    assert "revision" not in again and "accepted_terms" not in again


def test_stage_2_pair_history_uses_table_ids(stage2):
    svc = imported(stage2)
    pair = stage2["responses"][0]
    (created,) = svc.reservation_history("u_ada", pair["reference"])["entries"]
    assert created["changes"][0] == {"field": "table_ids", "from": None, "to": ["t_1", "t_2"]}


def test_imported_bookings_can_be_amended_under_policies(stage1):
    svc = imported(stage1)
    kept = stage1["responses"][0]
    changed = svc.amend_reservation("u_ada", kept["reference"], {"party_size": 3,
                                                                  "expected_revision": 1})
    assert changed["revision"] == 2
    assert [e["event"] for e in svc.reservation_history("u_ada", kept["reference"])["entries"]] == [
        "created", "changed"]


def _stage3_document():
    svc = Service(clock=Clock())
    svc.reset(fixture(restaurants=[dict(managed(), combinable=[["t_1", "t_2"]])]))
    token = svc.login({"email": "ada@example.com", "password": "correct horse"})["token"]
    ada = svc.authenticate("Bearer " + token)
    _, pub = svc.publish_policy(ada, "r_anker", "pk", policy("2020-01-01", reservation_duration_minutes=60))
    _, a = svc.create_reservation(ada, "a", {"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"],
                                             "starts_at_local": f"{DATE}T19:00", "party_size": 5})
    svc.amend_reservation(ada, a["reference"], {"party_size": 4})
    _, b = svc.create_reservation(ada, "b", {"restaurant_id": "r_anker", "table_id": "t_3",
                                             "starts_at_local": f"{DATE}T19:00", "party_size": 5})
    svc.cancel_reservation(ada, b["reference"])
    return svc, token, pub, a, b


def test_stage_3_round_trip_keeps_everything():
    svc, token, pub, a, b = _stage3_document()
    document = svc.export_state()
    assert document["state"]["schema"] == 4
    target = Service(clock=Clock())
    target.import_state(json.loads(json.dumps(document)))
    assert target.export_state() == document
    assert target.authenticate("Bearer " + token) == "u_ada"
    assert target.list_policies("r_anker") == {"policies": [pub]}
    assert target.reservation_history("u_ada", a["reference"]) == svc.reservation_history("u_ada", a["reference"])
    assert target.reservation_decision("u_ada", b["reference"])["revision"] == 2
    assert target.publish_policy("u_ada", "r_anker", "pk",
                                 policy("2020-01-01", reservation_duration_minutes=60)) == (200, pub)
    assert target._state.restaurant_revisions == svc._state.restaurant_revisions
    # The next publication continues the version sequence.
    assert target.publish_policy("u_ada", "r_anker", "pk2", policy(DATE))[1]["policy_version"] == 2
    assert terms_of(pub) == target.get_reservation("u_ada", a["reference"])["accepted_terms"]


def _mutations(document):
    def edit(fn):
        doc = copy.deepcopy(document)
        fn(doc["state"])
        return doc

    def res(state, i=0):
        return state["reservations"][i]

    return [
        edit(lambda s: s.update(schema=5)),
        edit(lambda s: res(s).update(revision=0)),
        edit(lambda s: res(s).update(revision=True)),
        edit(lambda s: res(s).pop("accepted_terms")),
        edit(lambda s: res(s)["accepted_terms"].pop("policy_version")),
        edit(lambda s: res(s)["accepted_terms"].update(cancellation_cutoff_minutes=-5)),
        edit(lambda s: res(s).update(history=[])),
        edit(lambda s: res(s)["history"][0].update(seq=2)),
        edit(lambda s: res(s)["history"][-1].update(revision=99)),
        edit(lambda s: res(s)["history"][0].update(event="moved")),
        edit(lambda s: res(s)["history"][0].update(at="yesterday")),
        edit(lambda s: s["restaurants"][0].update(policies=[dict(s["restaurants"][0]["policies"][0],
                                                                 policy_version=2)])),
        edit(lambda s: s["restaurants"][0]["policies"][0].update(slot_minutes=0)),
        edit(lambda s: s["restaurants"][0].update(manager_user_ids=["u_ghost"])),
        edit(lambda s: s.update(restaurant_revisions={"r_anker": -1})),
        edit(lambda s: s.update(restaurant_revisions={"r_nope": 1})),
        edit(lambda s: s.pop("restaurant_revisions")),
        edit(lambda s: s["idempotency"][0].update(path="/elsewhere")),
    ]


def test_invalid_stage_3_documents_are_422_and_change_nothing():
    svc, *_ = _stage3_document()
    document = svc.export_state()
    target = Service(clock=Clock())
    target.import_state(copy.deepcopy(document))
    before = target.export_state()
    for bad in _mutations(document):
        assert_error(api_error(target.import_state, bad), 422, "validation_failed")
        assert target.export_state() == before
