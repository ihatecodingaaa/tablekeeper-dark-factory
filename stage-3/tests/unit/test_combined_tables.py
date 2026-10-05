"""Stage 2: combined tables (spec 'Combined tables', 'Model', 'API') and rulings S2-R2/R3/R6."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from tk_unit import (DATE, api_error, assert_error, body, fixture, make_world, restaurant)
from tablekeeper.errors import ApiError

PAIRS = [["t_1", "t_2"], ["t_2", "t_3"]]   # capacities 2, 4, 6 -> pairs 6 and 10


def combo_restaurant(rid="r_anker", combinable=PAIRS, **kw):
    out = restaurant(rid, **kw)
    out["combinable"] = combinable
    return out


@pytest.fixture
def cw(clock):
    return make_world(clock, fixture(restaurants=[combo_restaurant()]))


def pair_body(table_ids=("t_1", "t_2"), at="19:00", party_size=6, **extra):
    out = body(at=at, party_size=party_size, **extra)
    del out["table_id"]
    out["table_ids"] = list(table_ids)
    return out


def create(w, data, user=None, key=None):
    return w.svc.create_reservation(user or w.ada, key or w.key(), data)


def create_error(w, data, user=None):
    return api_error(w.svc.create_reservation, user or w.ada, w.key(), data)


def options(w, party_size="2", at="19:00", date=DATE):
    out = w.svc.availability({"restaurant_id": ["r_anker"], "date": [date],
                              "party_size": [party_size]})
    for slot in out["slots"]:
        if slot["starts_at_local"].endswith(at):
            return slot
    raise AssertionError(at)


# -- fixture and restaurant shape ------------------------------------------------------


def test_get_restaurant_returns_combinable(cw):
    assert cw.svc.get_restaurant("r_anker")["combinable"] == PAIRS


def test_combinable_defaults_to_empty_list(world):
    assert world.svc.get_restaurant("r_anker")["combinable"] == []


def test_combinable_pair_order_is_kept_as_declared(clock):
    w = make_world(clock, fixture(restaurants=[combo_restaurant(combinable=[["t_2", "t_1"]])]))
    assert w.svc.get_restaurant("r_anker")["combinable"] == [["t_2", "t_1"]]


@pytest.mark.parametrize("combinable", [
    "t_1,t_2", {"t_1": "t_2"}, [["t_1"]], [["t_1", "t_2", "t_3"]], [["t_1", "t_1"]],
    [["t_1", "t_9"]], [["t_1", 2]], [["t_1", "t_2"], ["t_1", "t_2"]],
    [["t_1", "t_2"], ["t_2", "t_1"]], ["t_1"], [[]],
])
def test_invalid_combinable_is_422(world, combinable):
    bad = fixture(restaurants=[combo_restaurant(combinable=combinable)])
    assert_error(api_error(world.svc.reset, bad), 422, "validation_failed")


def test_combinable_tables_must_belong_to_that_restaurant(world):
    other = restaurant("r_other", tables=[{"id": "t_9", "label": "9", "capacity": 4}])
    bad = fixture(restaurants=[combo_restaurant(combinable=[["t_1", "t_9"]]), other])
    assert_error(api_error(world.svc.reset, bad), 422, "validation_failed")


# -- availability options ----------------------------------------------------------------


def test_options_singles_then_pairs_with_summed_capacity(cw):
    slot = options(cw, "2")
    assert slot["available_table_ids"] == ["t_1", "t_2", "t_3"]
    assert slot["available_options"] == [
        {"table_ids": ["t_1"], "capacity": 2},
        {"table_ids": ["t_2"], "capacity": 4},
        {"table_ids": ["t_3"], "capacity": 6},
        {"table_ids": ["t_1", "t_2"], "capacity": 6},
        {"table_ids": ["t_2", "t_3"], "capacity": 10},
    ]


@pytest.mark.parametrize("party,singles,opts", [
    ("5", ["t_3"], [["t_3"], ["t_1", "t_2"], ["t_2", "t_3"]]),
    ("6", ["t_3"], [["t_3"], ["t_1", "t_2"], ["t_2", "t_3"]]),
    ("7", [], [["t_2", "t_3"]]),
    ("10", [], [["t_2", "t_3"]]),
    ("11", [], []),
])
def test_options_filter_by_capacity(cw, party, singles, opts):
    slot = options(cw, party)
    assert slot["available_table_ids"] == singles
    assert [o["table_ids"] for o in slot["available_options"]] == opts


def test_pair_option_uses_combinable_order(clock):
    w = make_world(clock, fixture(restaurants=[combo_restaurant(combinable=[["t_3", "t_1"]])]))
    assert options(w, "7")["available_options"] == [{"table_ids": ["t_3", "t_1"], "capacity": 8}]


def test_restaurant_without_pairs_lists_only_singles(world):
    slot = options(world, "4")
    assert slot["available_options"] == [{"table_ids": ["t_2"], "capacity": 4},
                                         {"table_ids": ["t_3"], "capacity": 6}]


def test_booking_on_one_member_blocks_every_pair_with_it(cw):
    cw.booked(table_id="t_2", at="19:00", party_size=2)
    slot = options(cw, "2")
    assert slot["available_table_ids"] == ["t_1", "t_3"]
    assert [o["table_ids"] for o in slot["available_options"]] == [["t_1"], ["t_3"]]


def test_pair_booking_blocks_both_members(cw):
    status, _ = create(cw, pair_body())
    assert status == 201
    slot = options(cw, "2")
    assert slot["available_table_ids"] == ["t_3"]
    assert [o["table_ids"] for o in slot["available_options"]] == [["t_3"]]
    # Half-open: free again at 20:30.
    assert [o["table_ids"] for o in options(cw, "2", at="20:30")["available_options"]] == [
        ["t_1"], ["t_2"], ["t_3"], ["t_1", "t_2"], ["t_2", "t_3"]]


# -- create with table_ids ----------------------------------------------------------------


def test_create_pair_response_has_table_ids_and_no_table_id(cw):
    status, out = create(cw, pair_body())
    assert status == 201
    assert out["table_ids"] == ["t_1", "t_2"] and "table_id" not in out
    assert out["party_size"] == 6 and out["status"] == "confirmed"
    assert cw.svc.get_reservation(cw.ada, out["reference"]) == out


def test_create_pair_is_canonicalised_to_combinable_order(cw):
    _, out = create(cw, pair_body(("t_2", "t_1")))
    assert out["table_ids"] == ["t_1", "t_2"]


@pytest.mark.parametrize("data", [body(table_id="t_2"), pair_body(("t_2",), party_size=4)])
def test_single_table_responses_carry_table_id_and_table_ids(cw, data):
    _, out = create(cw, data)
    assert out["table_id"] == "t_2" and out["table_ids"] == ["t_2"]


def test_party_exceeds_summed_capacity(cw):
    assert_error(create_error(cw, pair_body(party_size=7)), 422, "party_exceeds_capacity")
    assert create(cw, pair_body(("t_2", "t_3"), party_size=10))[0] == 201


def test_combining_is_not_transitive(cw):
    assert_error(create_error(cw, pair_body(("t_1", "t_3"), party_size=2)), 422,
                 "combination_not_allowed")


def test_undeclared_pair_rejected_whatever_the_sizes(world):
    assert_error(create_error(world, pair_body(("t_1", "t_2"), party_size=2)), 422,
                 "combination_not_allowed")


def test_more_than_two_tables(cw):
    assert_error(create_error(cw, pair_body(("t_1", "t_2", "t_3"), party_size=2)), 422,
                 "combination_not_allowed")


@pytest.mark.parametrize("table_ids,status,code", [
    ("t_1", 400, "malformed_request"),
    (None, 400, "malformed_request"),
    ({"a": "t_1"}, 400, "malformed_request"),
    (["t_1", 2], 400, "malformed_request"),
    ([["t_1"]], 400, "malformed_request"),
    ([], 422, "validation_failed"),
    (["t_1", "t_1"], 422, "validation_failed"),
    (["t_1", "t_1", "t_2"], 422, "validation_failed"),
    (["t" * 65, "t_1"], 422, "validation_failed"),
    (["t_1", "t_2", "t_nope"], 422, "combination_not_allowed"),   # step 3 before 404
    (["t_1", "t_nope"], 404, "not_found"),                         # step 4 before 5
    (["t_nope"], 404, "not_found"),
])
def test_table_set_validation_precedence(cw, table_ids, status, code):
    data = pair_body(party_size=2)
    data["table_ids"] = table_ids
    assert_error(create_error(cw, data), status, code)


def test_both_or_neither_table_field_is_422(cw):
    both = pair_body(party_size=2)
    both["table_id"] = "t_1"
    assert_error(create_error(cw, both), 422, "validation_failed")
    neither = pair_body(party_size=2)
    del neither["table_ids"]
    assert_error(create_error(cw, neither), 422, "validation_failed")


def test_type_error_precedes_both_present(cw):
    data = pair_body(party_size=2)
    data["table_id"] = 5
    assert_error(create_error(cw, data), 400, "malformed_request")


def test_field_validation_precedes_combination_checks(cw):
    data = pair_body(("t_1", "t_2", "t_3"), party_size=0)
    assert_error(create_error(cw, data), 422, "validation_failed")


def test_unknown_restaurant_404_precedes_undeclared_pair(cw):
    assert_error(create_error(cw, pair_body(("t_1", "t_3"), restaurant_id="r_nope")), 404, "not_found")


def test_pair_rule_errors_follow_stage_1_order(cw):
    assert_error(create_error(cw, pair_body(at="19:15")), 422, "not_on_slot_grid")
    assert_error(create_error(cw, pair_body(at="22:00")), 422, "outside_opening_hours")
    assert_error(create_error(cw, pair_body(date="2026-03-29", at="02:30")), 422, "invalid_local_time")


def test_pair_blocked_when_one_member_taken(cw):
    cw.booked(cw.bob, table_id="t_2", at="19:30", party_size=2)
    assert_error(create_error(cw, pair_body()), 409, "table_unavailable")
    assert_error(create_error(cw, pair_body(("t_2", "t_3"))), 409, "table_unavailable")
    assert create(cw, body(table_id="t_1", party_size=2))[0] == 201


def test_single_blocked_by_pair_booking(cw):
    create(cw, pair_body())
    assert_error(create_error(cw, body(table_id="t_1", at="20:00", party_size=2), cw.bob),
                 409, "table_unavailable")
    assert_error(create_error(cw, body(table_id="t_2", at="18:00", party_size=2), cw.bob),
                 409, "table_unavailable")


def test_cancel_pair_frees_both_tables(cw):
    _, out = create(cw, pair_body())
    cancelled = cw.svc.cancel_reservation(cw.ada, out["reference"])
    assert cancelled["status"] == "cancelled" and cancelled["table_ids"] == ["t_1", "t_2"]
    assert options(cw, "2")["available_table_ids"] == ["t_1", "t_2", "t_3"]


def test_pair_replay_returns_identical_body(cw):
    data = pair_body(("t_2", "t_1"))
    _, first = cw.svc.create_reservation(cw.ada, "pk", data)
    assert cw.svc.create_reservation(cw.ada, "pk", data) == (200, first)
    reordered = dict(data, table_ids=["t_1", "t_2"])
    assert_error(api_error(cw.svc.create_reservation, cw.ada, "pk", reordered),
                 409, "idempotency_key_reuse")


def test_list_reservations_uses_stage_2_shape(cw):
    create(cw, pair_body())
    cw.booked(table_id="t_3", party_size=2)
    shapes = {tuple(r["table_ids"]): ("table_id" in r)
              for r in cw.svc.list_reservations(cw.ada)["reservations"]}
    assert shapes == {("t_1", "t_2"): False, ("t_3",): True}


# -- PATCH -------------------------------------------------------------------------------


def test_patch_single_to_pair_and_back(cw):
    out = cw.booked(table_id="t_2", party_size=4)
    paired = cw.svc.amend_reservation(cw.ada, out["reference"], {"table_ids": ["t_3", "t_2"]})
    assert paired["table_ids"] == ["t_2", "t_3"] and "table_id" not in paired
    assert paired["reference"] == out["reference"]
    assert options(cw, "2")["available_table_ids"] == ["t_1"]
    single = cw.svc.amend_reservation(cw.ada, out["reference"], {"table_id": "t_3"})
    assert single["table_id"] == "t_3" and single["table_ids"] == ["t_3"]
    assert options(cw, "2")["available_table_ids"] == ["t_1", "t_2"]


def test_patch_reversed_pair_is_a_no_op(cw):
    _, out = create(cw, pair_body())
    assert cw.svc.amend_reservation(cw.ada, out["reference"], {"table_ids": ["t_2", "t_1"]}) == out


def test_patch_pair_may_overlap_its_own_occupancy(cw):
    _, out = create(cw, pair_body())
    moved = cw.svc.amend_reservation(cw.ada, out["reference"],
                                     {"table_ids": ["t_2", "t_3"], "starts_at_local": f"{DATE}T19:30"})
    assert moved["table_ids"] == ["t_2", "t_3"]


@pytest.mark.parametrize("patch,status,code", [
    ({"table_ids": "t_1"}, 400, "malformed_request"),
    ({"table_ids": [1]}, 400, "malformed_request"),
    ({"table_id": "t_1", "table_ids": ["t_1"]}, 422, "validation_failed"),
    ({"table_ids": []}, 422, "validation_failed"),
    ({"table_ids": ["t_1", "t_1"]}, 422, "validation_failed"),
    ({"table_ids": ["t_1", "t_2", "t_3"]}, 422, "combination_not_allowed"),
    ({"table_ids": ["t_1", "t_x"]}, 404, "not_found"),
    ({"table_ids": ["t_1", "t_3"]}, 422, "combination_not_allowed"),
    ({"table_ids": ["t_1", "t_2"], "party_size": 7}, 422, "party_exceeds_capacity"),
    ({"table_ids": ["t_2", "t_3"]}, 409, "table_unavailable"),
])
def test_patch_table_set_rules(cw, patch, status, code):
    out = cw.booked(table_id="t_1", party_size=2)
    cw.booked(cw.bob, table_id="t_3", at="20:00", party_size=2)
    assert_error(api_error(cw.svc.amend_reservation, cw.ada, out["reference"], patch), status, code)
    assert cw.svc.get_reservation(cw.ada, out["reference"]) == out


def test_patch_type_error_precedes_404(cw):
    out = cw.booked(table_id="t_1", party_size=2)
    assert_error(api_error(cw.svc.amend_reservation, cw.bob, out["reference"], {"table_ids": "x"}),
                 400, "malformed_request")


# -- moves -------------------------------------------------------------------------------


def test_moves_accept_table_ids(cw):
    a = cw.booked(table_id="t_1", party_size=2)
    b = cw.booked(table_id="t_3", party_size=2)
    status, out = cw.svc.move_reservations(cw.ada, "m1", {"moves": [
        {"reference": a["reference"], "table_ids": ["t_2", "t_1"], "party_size": 5},
        {"reference": b["reference"], "table_ids": ["t_3"]}]})
    assert status == 201
    assert out["reservations"][0]["table_ids"] == ["t_1", "t_2"]
    assert "table_id" not in out["reservations"][0]
    assert out["reservations"][1] == b


def test_moves_no_table_in_overlapping_resulting_bookings(cw):
    a = cw.booked(table_id="t_1", party_size=2)
    b = cw.booked(table_id="t_3", party_size=2)
    err = api_error(cw.svc.move_reservations, cw.ada, "m1", {"moves": [
        {"reference": a["reference"], "table_ids": ["t_1", "t_2"]},
        {"reference": b["reference"], "table_ids": ["t_2", "t_3"]}]})
    assert_error(err, 409, "table_unavailable")
    assert cw.svc.get_reservation(cw.ada, a["reference"]) == a


def test_moves_pair_conflicts_with_unlisted_booking(cw):
    a = cw.booked(table_id="t_1", party_size=2)
    cw.booked(cw.bob, table_id="t_2", at="20:00", party_size=2)
    err = api_error(cw.svc.move_reservations, cw.ada, "m1",
                    {"moves": [{"reference": a["reference"], "table_ids": ["t_1", "t_2"]}]})
    assert_error(err, 409, "table_unavailable")


def test_moves_pair_split_into_two_singles(cw):
    _, pair = create(cw, pair_body(party_size=3))
    other = cw.booked(table_id="t_3", party_size=2)
    status, out = cw.svc.move_reservations(cw.ada, "m1", {"moves": [
        {"reference": pair["reference"], "table_id": "t_2"},
        {"reference": other["reference"], "table_ids": ["t_1"]}]})
    assert status == 201
    assert [r["table_ids"] for r in out["reservations"]] == [["t_2"], ["t_1"]]


@pytest.mark.parametrize("item,status,code", [
    ({"table_ids": "t_1"}, 400, "malformed_request"),
    ({"table_id": "t_1", "table_ids": ["t_1"]}, 422, "validation_failed"),
    ({"table_ids": ["t_1", "t_2", "t_3"]}, 422, "combination_not_allowed"),
    ({"table_ids": ["t_1", "t_3"]}, 422, "combination_not_allowed"),
])
def test_move_item_table_set_errors(cw, item, status, code):
    a = cw.booked(table_id="t_1", party_size=2)
    err = api_error(cw.svc.move_reservations, cw.ada, "m1", {"moves": [dict(item, reference=a["reference"])]})
    assert_error(err, status, code)


# -- seeds -------------------------------------------------------------------------------


def seed(**extra):
    out = {"id": "res_seed", "reference": "SEED01", "user_id": "u_ada", "restaurant_id": "r_anker",
           "table_id": "t_2", "starts_at_local": f"{DATE}T19:00", "party_size": 4}
    out.update(extra)
    return out


def seed_pair(**extra):
    out = seed(**extra)
    del out["table_id"]
    out.setdefault("table_ids", ["t_1", "t_2"])
    return out


def test_seeded_cancelled_reservation_does_not_occupy(clock):
    w = make_world(clock, fixture(restaurants=[combo_restaurant()], reservations=[seed(status="cancelled")]))
    assert w.svc.get_reservation("u_ada", "SEED01")["status"] == "cancelled"
    assert "t_2" in options(w, "2")["available_table_ids"]


def test_seeded_status_defaults_to_confirmed(clock):
    w = make_world(clock, fixture(restaurants=[combo_restaurant()],
                                  reservations=[seed(status="confirmed"),
                                                seed(id="r2", reference="SEED02", table_id="t_3")]))
    assert {r["status"] for r in w.svc.list_reservations("u_ada")["reservations"]} == {"confirmed"}


def test_seeded_pair_occupies_both(clock):
    w = make_world(clock, fixture(restaurants=[combo_restaurant()], reservations=[seed_pair(table_ids=["t_2", "t_1"])]))
    out = w.svc.get_reservation("u_ada", "SEED01")
    assert out["table_ids"] == ["t_1", "t_2"] and "table_id" not in out
    assert options(w, "2")["available_table_ids"] == ["t_3"]


@pytest.mark.parametrize("raw", [
    seed(status="pending"), seed(status=None), seed(status="CANCELLED"),
    seed_pair(table_ids=["t_1", "t_3"]),            # undeclared pair
    seed_pair(table_ids=["t_1", "t_2", "t_3"]),
    seed_pair(table_ids=["t_1", "t_1"]),
    seed_pair(table_ids=[]),
    seed_pair(table_ids="t_1"),
    seed_pair(table_ids=["t_1", "t_9"]),
    dict(seed(), table_ids=["t_2"]),                 # both fields
])
def test_invalid_seeds_are_422(world, raw):
    bad = fixture(restaurants=[combo_restaurant()], reservations=[raw])
    assert_error(api_error(world.svc.reset, bad), 422, "validation_failed")


def test_seed_without_any_table_field_is_422(world):
    raw = seed()
    del raw["table_id"]
    bad = fixture(restaurants=[combo_restaurant()], reservations=[raw])
    assert_error(api_error(world.svc.reset, bad), 422, "validation_failed")


# -- concurrency -------------------------------------------------------------------------


def test_concurrent_pair_and_single_sharing_a_member_one_wins(cw):
    n = 30
    barrier = threading.Barrier(n)

    def attempt(i):
        data = pair_body(party_size=2) if i % 3 == 0 else (
            body(table_id="t_2", party_size=2) if i % 3 == 1 else pair_body(("t_2", "t_3"), party_size=2))
        barrier.wait()
        try:
            return cw.svc.create_reservation(cw.ada if i % 2 else cw.bob, f"c-{i}", data)[0]
        except ApiError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(attempt, range(n)))
    assert results.count(201) == 1
    assert results.count("table_unavailable") == n - 1
    booked = [r for u in (cw.ada, cw.bob) for r in cw.svc.list_reservations(u)["reservations"]]
    assert len(booked) == 1 and "t_2" in booked[0]["table_ids"]
