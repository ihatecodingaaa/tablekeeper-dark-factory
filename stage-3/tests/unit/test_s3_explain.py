"""Stage 3 'Availability explanations' and ruling S3-R7."""
import pytest

from s3kit import DATE, make_s3, managed, policy, w3  # noqa: F401
from tk_unit import api_error, assert_error, fixture


def query(**extra):
    out = {"restaurant_id": ["r_anker"], "date": [DATE], "party_size": ["3"]}
    out.update({k: [v] for k, v in extra.items()})
    return out


def test_without_explain_the_shape_is_unchanged(w3):
    for slot in w3.svc.availability(query())["slots"]:
        assert set(slot) == {"starts_at_local", "starts_at", "available_table_ids", "available_options"}


def test_explain_covers_every_table_with_both_rules(w3):
    w3.booked(table_id="t_3", at="19:00", party_size=2)
    out = w3.svc.availability(query(explain="true"))
    assert out["slots"]
    for slot in out["slots"]:
        ex = slot["explain"]
        assert [e["table_id"] for e in ex] == ["t_1", "t_2", "t_3"]
        for e in ex:
            assert set(e) == {"table_id", "policy_version", "available", "rules"}
            assert [r["rule"] for r in e["rules"]] == ["capacity", "no_overlap"]
            assert e["available"] == all(r["holds"] for r in e["rules"])
            assert e["policy_version"] == 0
        assert [e["table_id"] for e in ex if e["available"]] == slot["available_table_ids"]
    t1 = out["slots"][0]["explain"][0]
    assert t1["rules"] == [{"rule": "capacity", "holds": False}, {"rule": "no_overlap", "holds": True}]


def test_table_failing_both_rules_reports_both_false(w3):
    w3.booked(table_id="t_1", at="19:00", party_size=2)
    slot = {s["starts_at_local"][11:]: s for s in w3.svc.availability(query(explain="true"))["slots"]}
    assert slot["19:00"]["explain"][0]["rules"] == [{"rule": "capacity", "holds": False},
                                                     {"rule": "no_overlap", "holds": False}]


def test_slot_with_no_available_table_still_has_full_explain(w3):
    for table in ("t_1", "t_2", "t_3"):
        w3.booked(table_id=table, at="19:00", party_size=2)
    slot = {s["starts_at_local"][11:]: s for s in w3.svc.availability(query(explain="true"))["slots"]}
    assert slot["19:00"]["available_table_ids"] == []
    assert len(slot["19:00"]["explain"]) == 3
    assert not any(e["available"] for e in slot["19:00"]["explain"])


def test_closed_day_is_still_empty(clock):
    w = make_s3(clock, fixture(restaurants=[managed(hours=[{"weekday": "fri", "opens": "18:00",
                                                            "closes": "23:00"}])]))
    assert w.svc.availability(query(explain="true"))["slots"] == []


def test_explain_uses_the_selected_policy(w3):
    w3.published(policy("2026-09-01", capacities={"t_1": 3, "t_2": 1, "t_3": 6}))
    slot = w3.svc.availability(query(explain="true"))["slots"][0]
    assert [e["policy_version"] for e in slot["explain"]] == [1, 1, 1]
    assert [e["available"] for e in slot["explain"]] == [True, False, True]
    assert slot["available_table_ids"] == ["t_1", "t_3"]


@pytest.mark.parametrize("value", ["false", "1", "", "True", "TRUE", "yes", " true"])
def test_any_other_explain_value_is_422(w3, value):
    assert_error(api_error(w3.svc.availability, query(explain=value)), 422, "validation_failed")


def test_explain_check_precedes_unknown_restaurant(w3):
    bad = query(explain="false")
    bad["restaurant_id"] = ["r_nope"]
    assert_error(api_error(w3.svc.availability, bad), 422, "validation_failed")


def test_options_still_present_with_explain(w3):
    slot = w3.svc.availability(query(explain="true"))["slots"][0]
    assert slot["available_options"] == [{"table_ids": ["t_2"], "capacity": 4},
                                         {"table_ids": ["t_3"], "capacity": 6}]
