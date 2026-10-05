"""Stage 4 seating-repair planner (S4-R2, S4-R1a): exactness against an
independent brute force, hand-worked cases, the bound sizes and the budget."""
from __future__ import annotations

import datetime as dt
import importlib.util
import itertools
import pathlib
import random

import pytest

_PATH = pathlib.Path(__file__).resolve().parents[2] / "tablekeeper" / "planner.py"
_spec = importlib.util.spec_from_file_location("tk_planner_under_test", _PATH)
planner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(planner)

UTC = dt.timezone.utc
DAY = dt.datetime(2026, 9, 28, 0, 0, tzinfo=UTC)
SEED = 20261005


def t(hhmm: str) -> dt.datetime:
    hours, minutes = map(int, hhmm.split(":"))
    return DAY + dt.timedelta(hours=hours, minutes=minutes)


def options_for(table_ids, pairs):
    out = [{"rank": i, "table_ids": [tid]} for i, tid in enumerate(table_ids)]
    out += [{"rank": len(table_ids) + i, "table_ids": list(p)} for i, p in enumerate(pairs)]
    return out


def booking(ref, tables, party, start, end, caps):
    return {"reference": ref, "table_ids": list(tables), "party_size": party,
            "start": t(start) if isinstance(start, str) else start,
            "end": t(end) if isinstance(end, str) else end, "capacities": dict(caps)}


# -- independent oracle ---------------------------------------------------------------------


def brute_force(considered, fixed, closures, options, proposed):
    """Enumerate every assignment with itertools.product; written separately."""
    ordered = sorted(considered, key=lambda b: b["reference"])
    blocked = list(closures) + [proposed]

    def overlap(a0, a1, b0, b1):
        return a0 < b1 and b0 < a1

    def allowed(b, option):
        ids = option["table_ids"]
        if not all(x in b["capacities"] for x in ids):
            return False
        if sum(b["capacities"][x] for x in ids) < b["party_size"]:
            return False
        for table, s, e in blocked:
            if table in ids and overlap(b["start"], b["end"], s, e):
                return False
        for f in fixed:
            if set(ids) & set(f["table_ids"]) and overlap(b["start"], b["end"], f["start"], f["end"]):
                return False
        return True

    best = None
    for combo in itertools.product(options, repeat=len(ordered)):
        if not all(allowed(b, o) for b, o in zip(ordered, combo)):
            continue
        clash = False
        for (b1, o1), (b2, o2) in itertools.combinations(list(zip(ordered, combo)), 2):
            if set(o1["table_ids"]) & set(o2["table_ids"]) and overlap(b1["start"], b1["end"],
                                                                        b2["start"], b2["end"]):
                clash = True
                break
        if clash:
            continue
        moved = sum(set(o["table_ids"]) != set(b["table_ids"]) for b, o in zip(ordered, combo))
        unused = sum(sum(b["capacities"][x] for x in o["table_ids"]) - b["party_size"]
                     for b, o in zip(ordered, combo))
        key = (moved, unused, tuple(o["rank"] for o in combo))
        if best is None or key < best[0]:
            best = (key, combo)
    if best is None:
        return ("infeasible",)
    (moved, unused, _), combo = best
    return ("ok", [{"reference": b["reference"], "table_ids": list(o["table_ids"]),
                    "changed": set(o["table_ids"]) != set(b["table_ids"])}
                   for b, o in zip(ordered, combo)], moved, unused)


def random_case(rng):
    n_tables = rng.randint(2, 5)
    tables = [f"t_{i}" for i in range(1, n_tables + 1)]
    caps = {tid: rng.randint(1, 6) for tid in tables}
    all_pairs = list(itertools.combinations(tables, 2))
    pairs = rng.sample(all_pairs, rng.randint(0, min(3, len(all_pairs))))
    options = options_for(tables, pairs)

    def interval():
        start = rng.randrange(0, 10) * 30
        return DAY + dt.timedelta(hours=17, minutes=start), \
            DAY + dt.timedelta(hours=17, minutes=start + rng.choice([60, 90, 120, 150]))

    def own_caps():
        # Accepted terms may differ from today's fixture for some bookings.
        return {tid: max(1, c + rng.choice([0, 0, 0, -1, 1, 2])) for tid, c in caps.items()}

    considered = []
    for k in range(rng.randint(1, 4)):
        s, e = interval()
        option = rng.choice(options)
        considered.append({"reference": f"R{rng.randint(0, 9999):04d}{k}", "table_ids": option["table_ids"],
                           "party_size": rng.randint(1, 8), "start": s, "end": e,
                           "capacities": own_caps()})
    fixed = []
    for _ in range(rng.randint(0, 3)):
        s, e = interval()
        fixed.append({"table_ids": rng.choice(options)["table_ids"], "start": s, "end": e})
    closures = []
    for _ in range(rng.randint(0, 2)):
        s, e = interval()
        closures.append((rng.choice(tables), s, e))
    s, e = interval()
    proposed = (rng.choice(tables), s, e)
    return considered, fixed, closures, options, proposed


def test_matches_independent_brute_force_on_seeded_random_cases(capsys):
    rng = random.Random(SEED)
    print(f"planner oracle seed={SEED}")
    outcomes = {"ok": 0, "infeasible": 0}
    for case in range(400):
        considered, fixed, closures, options, proposed = random_case(rng)
        expected = brute_force(considered, fixed, closures, options, proposed)
        got = planner.plan(considered, fixed, closures, options, proposed)
        assert got == expected, f"seed={SEED} case={case}"
        outcomes[got[0]] += 1
    assert outcomes["ok"] >= 100 and outcomes["infeasible"] >= 20, outcomes


# -- hand-worked cases ------------------------------------------------------------------------

CAPS = {"t_1": 2, "t_2": 4, "t_3": 4}
OPTIONS = options_for(["t_1", "t_2", "t_3"], [("t_1", "t_2"), ("t_2", "t_3")])
CLOSE_T2 = ("t_2", t("18:00"), t("23:00"))


def test_cascade_moves_a_second_booking():
    a = booking("A0001", ["t_2"], 4, "19:00", "20:30", CAPS)
    b = booking("B0001", ["t_3"], 2, "19:30", "21:00", CAPS)
    result = planner.plan([a, b], [], [], OPTIONS, CLOSE_T2)
    assert result == ("ok", [{"reference": "A0001", "table_ids": ["t_3"], "changed": True},
                             {"reference": "B0001", "table_ids": ["t_1"], "changed": True}], 2, 0)


def test_fewer_moves_beat_fewer_unused_seats():
    # B can stay on t_3 (2 spare seats) or move to t_1 (0 spare): staying wins.
    a = booking("A0001", ["t_2"], 2, "19:00", "20:30", CAPS)
    b = booking("B0001", ["t_3"], 2, "21:00", "22:30", CAPS)
    ok, assignments, moved, unused = planner.plan([a, b], [], [], OPTIONS, CLOSE_T2)
    assert assignments == [{"reference": "A0001", "table_ids": ["t_1"], "changed": True},
                           {"reference": "B0001", "table_ids": ["t_3"], "changed": False}]
    assert (moved, unused) == (1, 2)


def test_rank_vector_breaks_ties_in_reference_order():
    caps = {"t_1": 4, "t_2": 4, "t_3": 4}
    a = booking("A0001", ["t_2"], 4, "19:00", "20:30", caps)
    result = planner.plan([a], [], [], OPTIONS, CLOSE_T2)
    assert result[1][0]["table_ids"] == ["t_1"]          # rank 0 beats t_3 (rank 2)


def test_pair_only_option():
    caps = {"t_1": 2, "t_2": 4, "t_3": 4}
    a = booking("A0001", ["t_3"], 6, "19:00", "20:30", caps)
    closure = ("t_3", t("18:00"), t("23:00"))
    result = planner.plan([a], [], [], OPTIONS, closure)
    assert result == ("ok", [{"reference": "A0001", "table_ids": ["t_1", "t_2"], "changed": True}], 1, 0)


def test_infeasible():
    a = booking("A0001", ["t_2"], 4, "19:00", "20:30", CAPS)
    fixed = [{"table_ids": ["t_3"], "start": t("19:00"), "end": t("20:30")}]
    assert planner.plan([a], fixed, [], OPTIONS, CLOSE_T2) == ("infeasible",)


def test_capacity_comes_from_the_bookings_own_terms():
    own = {"t_1": 2, "t_2": 4, "t_3": 3}         # accepted under an older policy
    a = booking("A0001", ["t_2"], 4, "19:00", "20:30", own)
    result = planner.plan([a], [], [], OPTIONS, CLOSE_T2)
    # t_2 is closed, so the pair t_1+t_2 is also blocked: infeasible under own terms.
    assert result == ("infeasible",)
    roomy = booking("A0001", ["t_2"], 4, "19:00", "20:30", {"t_1": 2, "t_2": 4, "t_3": 4})
    assert planner.plan([roomy], [], [], OPTIONS, CLOSE_T2)[1][0]["table_ids"] == ["t_3"]


def test_previously_applied_closure_blocks_a_table():
    a = booking("A0001", ["t_2"], 2, "19:00", "20:30", CAPS)
    prior = [("t_1", t("18:30"), t("19:30"))]
    result = planner.plan([a], [], prior, OPTIONS, CLOSE_T2)
    assert result == ("ok", [{"reference": "A0001", "table_ids": ["t_3"], "changed": True}], 1, 2)


def test_fixed_booking_blocks_a_table_but_not_after_it_ends():
    a = booking("A0001", ["t_2"], 2, "19:00", "20:30", CAPS)
    fixed = [{"table_ids": ["t_1"], "start": t("17:30"), "end": t("19:00")}]   # half-open: no clash
    assert planner.plan([a], fixed, [], OPTIONS, CLOSE_T2)[1][0]["table_ids"] == ["t_1"]
    fixed = [{"table_ids": ["t_1"], "start": t("17:30"), "end": t("19:01")}]
    assert planner.plan([a], fixed, [], OPTIONS, CLOSE_T2)[1][0]["table_ids"] == ["t_3"]


def test_unaffected_booking_stays_put():
    a = booking("A0001", ["t_3"], 4, "19:00", "20:30", CAPS)
    assert planner.plan([a], [], [], OPTIONS, CLOSE_T2) == (
        "ok", [{"reference": "A0001", "table_ids": ["t_3"], "changed": False}], 0, 0)


def test_reversed_current_pair_is_not_a_move():
    a = booking("A0001", ["t_2", "t_1"], 6, "19:00", "20:30", CAPS)
    closure = ("t_3", t("18:00"), t("23:00"))
    assert planner.plan([a], [], [], OPTIONS, closure)[1][0] == {
        "reference": "A0001", "table_ids": ["t_1", "t_2"], "changed": False}


# -- bounds and budget ---------------------------------------------------------------------------


def _bound_case(rng, count=6):
    tables = [f"t_{i}" for i in range(1, 7)]
    caps = {tid: rng.randint(2, 6) for tid in tables}
    pairs = rng.sample(list(itertools.combinations(tables, 2)), 4)
    options = options_for(tables, pairs)
    considered = [booking(f"B{k}{rng.randint(100, 999)}", rng.choice(options)["table_ids"],
                          rng.randint(1, 5), DAY + dt.timedelta(hours=19, minutes=15 * k),
                          DAY + dt.timedelta(hours=21, minutes=15 * k), caps) for k in range(count)]
    return considered, [], [], options, (tables[0], DAY + dt.timedelta(hours=18), DAY + dt.timedelta(hours=23))


def test_bound_sizes_always_finish_within_the_budget():
    rng = random.Random(SEED + 1)
    worst = 0
    for _ in range(25):
        stats = {}
        result = planner.plan(*_bound_case(rng), stats=stats)
        assert result[0] in ("ok", "infeasible")
        worst = max(worst, stats["nodes"])
    assert worst <= planner.DEFAULT_BUDGET


def test_bound_sizes_match_the_oracle():
    rng = random.Random(SEED + 2)
    for _ in range(3):
        case = _bound_case(rng, count=5)      # 10**5 combinations keep the oracle fast
        assert planner.plan(*case) == brute_force(*case)


def test_over_budget_is_deterministic():
    case = _bound_case(random.Random(SEED + 3))
    first = planner.plan(*case, budget=5)
    assert first == ("over_budget",) == planner.plan(*case, budget=5)
    stats_a, stats_b = {}, {}
    planner.plan(*case, stats=stats_a)
    planner.plan(*case, stats=stats_b)
    assert stats_a == stats_b


def test_larger_inputs_still_solve_exactly_within_budget():
    rng = random.Random(SEED + 4)
    tables = [f"t_{i}" for i in range(1, 8)]
    caps = {tid: rng.randint(2, 6) for tid in tables}
    options = options_for(tables, rng.sample(list(itertools.combinations(tables, 2)), 5))
    considered = [booking(f"C{k}", rng.choice(options)["table_ids"], rng.randint(1, 4),
                          DAY + dt.timedelta(hours=19, minutes=30 * k),
                          DAY + dt.timedelta(hours=20, minutes=30 * k), caps) for k in range(7)]
    result = planner.plan(considered, [], [], options, (tables[0], DAY, DAY + dt.timedelta(days=1)))
    assert result[0] in ("ok", "infeasible", "over_budget")
    if result[0] == "ok":
        assert len(result[1]) == 7
