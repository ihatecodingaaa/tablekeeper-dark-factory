"""Spec §10 export and import; ruling R9."""
import copy
import json

import pytest

from tk_unit import ADA, Clock, api_error, assert_error, body, fixture
from tablekeeper.service import Service


def populated(world):
    _, kept = world.svc.create_reservation(world.ada, "k-create", body(table_id="t_2"))
    _, gone = world.svc.create_reservation(world.ada, "k-gone", body(table_id="t_1", party_size=2))
    world.svc.cancel_reservation(world.ada, gone["reference"])
    _, moved = world.svc.move_reservations(world.ada, "k-move",
                                           {"moves": [{"reference": kept["reference"], "table_id": "t_3"}]})
    world.svc.signup({"email": "new@example.com", "password": "long enough", "display_name": "Neo"})
    return kept, gone, moved


def fresh_import(document, clock=None):
    svc = Service(clock=clock or Clock())
    svc.reset(fixture(users=[], restaurants=[]))
    svc.import_state(json.loads(json.dumps(document)))
    return svc


def test_export_shape(world):
    out = world.svc.export_state()
    assert out["track"] == "tablekeeper" and out["format_version"] == 1
    assert isinstance(out["state"], dict) and out["state"]["schema"] == 2
    json.dumps(out)


def test_import_into_fresh_service_preserves_everything(world):
    token = world.svc.login({"email": ADA["email"], "password": ADA["password"]})["token"]
    kept, gone, moved = populated(world)
    document = world.svc.export_state()
    svc = fresh_import(document, world.clock)
    # The export round trip is byte-for-byte stable before any new writes.
    assert svc.export_state() == document
    # Old token still authenticates; hashed-password login still works.
    assert svc.authenticate("Bearer " + token) == "u_ada"
    assert svc.login({"email": "new@example.com", "password": "long enough"})["display_name"] == "Neo"
    # Reservations, references, statuses and timestamps are preserved exactly.
    assert svc.list_reservations("u_ada") == world.svc.list_reservations("u_ada")
    assert svc.get_reservation("u_ada", gone["reference"])["status"] == "cancelled"
    # Completed idempotent requests replay the original responses.
    assert svc.create_reservation("u_ada", "k-create", body(table_id="t_2")) == (200, kept)
    status, again = svc.move_reservations("u_ada", "k-move",
                                          {"moves": [{"reference": kept["reference"], "table_id": "t_3"}]})
    assert (status, again) == (200, moved)
    assert_error(api_error(svc.create_reservation, "u_ada", "k-create", body(table_id="t_1")),
                 409, "idempotency_key_reuse")
    # Occupancy is restored: kept now sits on t_3.
    assert_error(api_error(svc.create_reservation, "u_bob", "x", body(table_id="t_3")),
                 409, "table_unavailable")


def test_failed_key_remains_reusable_after_import(world):
    world.booked(world.bob, table_id="t_2")
    assert_error(api_error(world.svc.create_reservation, world.ada, "k-fail", body(table_id="t_2")),
                 409, "table_unavailable")
    svc = fresh_import(world.svc.export_state(), world.clock)
    status, _ = svc.create_reservation(world.ada, "k-fail", body(table_id="t_3"))
    assert status == 201


def test_new_references_after_import_do_not_collide(world):
    refs = {world.booked(table_id=t, at=a, party_size=2)["reference"]
            for t in ("t_1", "t_2") for a in ("18:00", "20:00")}
    svc = fresh_import(world.svc.export_state(), world.clock)
    for t in ("t_1", "t_2"):
        status, out = svc.create_reservation(world.ada, f"n-{t}", body(table_id=t, at="21:30", party_size=2))
        assert status == 201 and out["reference"] not in refs


def test_import_is_replacement_not_merge(world):
    populated(world)
    document = world.svc.export_state()
    svc = Service(clock=Clock())
    svc.reset(fixture(users=[{"id": "u_zed", "email": "zed@example.com", "password": "pw123456",
                              "display_name": "Zed"}]))
    zed_token = svc.login({"email": "zed@example.com", "password": "pw123456"})["token"]
    svc.import_state(document)
    assert_error(api_error(svc.authenticate, "Bearer " + zed_token), 401, "unauthenticated")
    assert_error(api_error(svc.login, {"email": "zed@example.com", "password": "pw123456"}),
                 401, "unauthenticated")
    svc.import_state(document)
    assert len(svc.list_reservations("u_ada")["reservations"]) == 2
    assert svc.export_state() == document


def test_export_is_a_snapshot(world):
    kept, _, _ = populated(world)
    document = world.svc.export_state()
    frozen = copy.deepcopy(document)
    world.svc.cancel_reservation(world.ada, kept["reference"])
    world.booked(table_id="t_1", at="21:00", party_size=2)
    assert document == frozen


def test_reset_clears_imported_state(world):
    populated(world)
    svc = fresh_import(world.svc.export_state())
    svc.reset(fixture())
    assert svc.list_reservations("u_ada") == {"reservations": []}
    assert_error(api_error(svc.login, {"email": "new@example.com", "password": "long enough"}),
                 401, "unauthenticated")


def _bad_documents(document):
    def with_state(**changes):
        doc = copy.deepcopy(document)
        doc["state"].update(changes)
        return doc

    def drop(key):
        doc = copy.deepcopy(document)
        del doc[key]
        return doc

    bad_reservation = copy.deepcopy(document)
    bad_reservation["state"]["reservations"][0]["starts_at"] = "yesterday"
    dup_user = copy.deepcopy(document)
    dup_user["state"]["users"].append(dup_user["state"]["users"][0])
    bad_hash = copy.deepcopy(document)
    bad_hash["state"]["users"][0]["password_hash"] = "plaintext"
    return [
        [], "x", 1, None, True, {},
        drop("track"), drop("format_version"), drop("state"),
        dict(document, track="pocketful"), dict(document, format_version=2),
        dict(document, format_version=True), dict(document, format_version="1"),
        dict(document, format_version=1.5), dict(document, state=[]), dict(document, state="x"),
        dict(document, state={}), with_state(schema=99), with_state(users="x"),
        with_state(reservations=[{"reference": "X"}]), with_state(idempotency=[1]),
        bad_reservation, dup_user, bad_hash,
    ]


def test_invalid_import_is_422_and_leaves_state_unchanged(world):
    kept, _, _ = populated(world)
    good = world.svc.export_state()
    target = fresh_import(good, world.clock)
    before = target.export_state()
    for bad in _bad_documents(good):
        assert_error(api_error(target.import_state, bad), 422, "validation_failed")
        assert target.export_state() == before
    assert target.get_reservation("u_ada", kept["reference"])["table_id"] == "t_3"


@pytest.mark.parametrize("version", [1])
def test_format_version_integer_one(world, version):
    doc = world.svc.export_state()
    doc["format_version"] = version
    fresh_import(doc)


def test_import_rejects_oversized_scrypt_parameters(world):
    doc = world.svc.export_state()
    salt_digest = doc["state"]["users"][0]["password_hash"].split("$", 4)[4]
    doc["state"]["users"][0]["password_hash"] = "scrypt$65536$16$4$" + salt_digest
    assert_error(api_error(fresh_import, doc), 422, "validation_failed")
