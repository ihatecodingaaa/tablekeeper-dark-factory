"""X1 guarantee ledger: state machine, idempotency, money rules, authorization."""
import datetime as dt

import pytest

from xkit import UTC, XWorld, fixture, restaurant


@pytest.fixture
def w():
    return XWorld()


def g_path(ref):
    return f"/x/reservations/{ref}/guarantee"


def m_path(ref, action, rid="r_anker"):
    return f"/x/restaurants/{rid}/guarantees/{ref}/{action}"


def test_hold_is_party_times_per_guest_and_replays(w):
    b = w.book(party=4)
    status, first, ctype = w.call("POST", g_path(b["reference"]), "u_ada", {}, idem="h1")
    assert status == 201 and ctype.startswith("application/json")
    assert (first["state"], first["amount_minor"], first["currency"]) == ("HELD", 6000, "EUR")
    assert [e["type"] for e in first["events"]] == ["held"]
    event = first["events"][0]
    assert set(event) == {"seq", "at", "type", "amount_minor", "currency", "reason", "actor"}
    assert event["seq"] == 1 and isinstance(event["amount_minor"], int)
    assert "€60.00" in first["explanation"] and "Nothing has been charged" in first["explanation"]
    assert first["next_expected"]
    assert w.call("POST", g_path(b["reference"]), "u_ada", {}, idem="h1")[:2] == (200, first)
    assert w.call("GET", g_path(b["reference"]), "u_ada")[1] == first


def test_second_hold_is_invalid_transition(w):
    b = w.book()
    w.ok("POST", g_path(b["reference"]), "u_ada", idem="h1")
    status, out, _ = w.call("POST", g_path(b["reference"]), "u_ada", idem="h2")
    assert (status, out["error"]["code"]) == (409, "invalid_transition")
    status, out, _ = w.call("POST", g_path(b["reference"]), "u_ada", {"x": 1}, idem="h1")
    assert (status, out["error"]["code"]) == (409, "idempotency_key_reuse")


def test_hold_requires_key_owner_and_confirmed_booking(w):
    b = w.book()
    assert w.call("POST", g_path(b["reference"]), "u_ada")[1]["error"]["code"] == "missing_idempotency_key"
    assert w.call("POST", g_path(b["reference"]), "u_bob", idem="k")[0] == 404
    assert w.call("POST", g_path(b["reference"]), None, idem="k")[0] == 401
    assert w.call("GET", g_path(b["reference"]), "u_bob")[0] == 404
    w.cancel(b["reference"])
    status, out, _ = w.call("POST", g_path(b["reference"]), "u_ada", idem="k")
    assert (status, out["error"]["code"]) == (409, "reservation_cancelled")


def test_no_guarantee_view_offers_the_amount(w):
    b = w.book(party=2)
    out = w.ok("GET", g_path(b["reference"]), "u_ada")
    assert out["state"] == "NO_GUARANTEE" and out["amount_minor"] == 0 and out["events"] == []
    assert "€30.00" in out["next_expected"]


def test_manager_sets_the_policy(w):
    path = "/x/restaurants/r_anker/guarantee-policy"
    assert w.ok("GET", path, "u_mia") == {"per_guest_minor": 1500, "currency": "EUR"}
    assert w.ok("PUT", path, "u_mia", {"per_guest_minor": 2000, "currency": "EUR", "x": 1}) == {
        "per_guest_minor": 2000, "currency": "EUR"}
    b = w.book(party=3)
    assert w.ok("POST", g_path(b["reference"]), "u_ada", idem="h")["amount_minor"] == 6000
    assert w.call("PUT", path, "u_ada", {"per_guest_minor": 1, "currency": "EUR"})[0] == 403
    assert w.call("PUT", "/x/restaurants/r_nope/guarantee-policy", "u_mia",
                  {"per_guest_minor": 1, "currency": "EUR"})[0] == 404


@pytest.mark.parametrize("body", [{"per_guest_minor": -1, "currency": "EUR"},
                                  {"per_guest_minor": 10.5, "currency": "EUR"},
                                  {"per_guest_minor": 1000.0, "currency": "EUR"},
                                  {"per_guest_minor": True, "currency": "EUR"},
                                  {"per_guest_minor": "100", "currency": "EUR"},
                                  {"per_guest_minor": 100}, {"per_guest_minor": 100, "currency": "USD"},
                                  {"per_guest_minor": 10_000_001, "currency": "EUR"}])
def test_invalid_money_is_422(w, body):
    status, out, _ = w.call("PUT", "/x/restaurants/r_anker/guarantee-policy", "u_mia", body)
    assert (status, out["error"]["code"]) == (422, "validation_failed")


def test_zero_rate_means_no_guarantee_to_hold(w):
    w.ok("PUT", "/x/restaurants/r_anker/guarantee-policy", "u_mia", {"per_guest_minor": 0, "currency": "EUR"})
    b = w.book()
    assert w.call("POST", g_path(b["reference"]), "u_ada", idem="h")[1]["error"]["code"] == "invalid_transition"


def test_capture_only_at_or_after_start_then_refund(w):
    b = w.book(at="19:00")                                   # 17:00 UTC
    w.ok("POST", g_path(b["reference"]), "u_ada", idem="h")
    status, out, _ = w.call("POST", m_path(b["reference"], "capture"), "u_mia", idem="c1")
    assert (status, out["error"]["code"]) == (409, "invalid_transition")
    w.clock.now = dt.datetime(2026, 9, 24, 17, 0, tzinfo=UTC)
    status, captured, _ = w.call("POST", m_path(b["reference"], "capture"), "u_mia", idem="c2")
    assert status == 201 and captured["state"] == "CAPTURED" and captured["amount_minor"] == 6000
    assert w.call("POST", m_path(b["reference"], "capture"), "u_mia", idem="c2")[:2] == (200, captured)
    assert w.call("POST", m_path(b["reference"], "capture"), "u_mia", idem="c3")[1]["error"]["code"] == \
        "invalid_transition"
    assert w.call("POST", m_path(b["reference"], "release"), "u_mia", idem="r1")[1]["error"]["code"] == \
        "invalid_transition"
    refunded = w.ok("POST", m_path(b["reference"], "refund"), "u_mia", idem="f1")
    assert refunded["state"] == "REFUNDED" and refunded["events"][-1]["amount_minor"] == 6000
    assert w.call("POST", m_path(b["reference"], "refund"), "u_mia", idem="f2")[1]["error"]["code"] == \
        "invalid_transition"
    assert [e["type"] for e in refunded["events"]] == ["held", "captured", "refunded"]
    assert [e["seq"] for e in refunded["events"]] == [1, 2, 3]


def test_release_when_the_guest_arrives(w):
    b = w.book()
    w.ok("POST", g_path(b["reference"]), "u_ada", idem="h")
    out = w.ok("POST", m_path(b["reference"], "release"), "u_mia", idem="r")
    assert out["state"] == "RELEASED" and out["events"][-1]["reason"] == "guest arrived"
    assert w.call("POST", m_path(b["reference"], "capture"), "u_mia", idem="c")[1]["error"]["code"] == \
        "invalid_transition"


def test_manager_actions_need_a_manager_of_that_restaurant(clock=None):
    w = XWorld(fx=fixture([restaurant(), restaurant("r_b", managers=("u_bob",))]))
    b = w.book()
    w.ok("POST", g_path(b["reference"]), "u_ada", idem="h")
    assert w.call("POST", m_path(b["reference"], "release"), "u_ada", idem="x")[0] == 403
    assert w.call("POST", m_path(b["reference"], "release", "r_b"), "u_bob", idem="x")[0] == 404
    assert w.call("POST", m_path(b["reference"], "release"), None, idem="x")[0] == 401
    assert w.call("POST", m_path("NOPE0000", "release"), "u_mia", idem="x")[0] == 404


def test_cancel_releases_a_held_guarantee(w):
    b = w.book()
    w.ok("POST", g_path(b["reference"]), "u_ada", idem="h")
    w.cancel(b["reference"])
    out = w.ok("GET", g_path(b["reference"]), "u_ada")
    assert out["state"] == "RELEASED"
    assert out["events"][-1] == dict(out["events"][-1], type="released", reason="cancelled before cutoff",
                                     actor="system", amount_minor=6000)


def test_party_change_adjusts_the_hold_with_the_delta(w):
    b = w.book(party=4)
    w.ok("POST", g_path(b["reference"]), "u_ada", idem="h")
    w.amend(b["reference"], {"party_size": 2})
    out = w.ok("GET", g_path(b["reference"]), "u_ada")
    assert out["amount_minor"] == 3000 and out["events"][-1]["type"] == "hold_adjusted"
    assert out["events"][-1]["amount_minor"] == -3000
    w.amend(b["reference"], {"starts_at_local": "2026-09-24T20:00"})
    assert len(w.ok("GET", g_path(b["reference"]), "u_ada")["events"]) == 2


def test_settlement_totals_and_rows(w):
    a, b, c = w.book(at="18:00", table="t_1", party=2), w.book(at="19:00", party=4), w.book(at="21:00", table="t_3", party=6)
    for ref in (a, b, c):
        w.ok("POST", g_path(ref["reference"]), "u_ada", idem=f"h-{ref['reference']}")
    w.ok("POST", m_path(a["reference"], "release"), "u_mia", idem="r")
    w.clock.now = dt.datetime(2026, 9, 24, 23, 0, tzinfo=UTC)
    w.ok("POST", m_path(b["reference"], "capture"), "u_mia", idem="c")
    out = w.ok("GET", "/x/restaurants/r_anker/guarantees", "u_mia")
    assert out["totals"] == {"held_minor": 9000, "captured_minor": 6000, "released_minor": 3000,
                             "refunded_minor": 0}
    assert [r["reference"] for r in out["rows"]] == [a["reference"], b["reference"], c["reference"]]
    assert out["rows"][0]["guest"] == "Ada"
    assert w.call("GET", "/x/restaurants/r_anker/guarantees", "u_ada")[0] == 403
