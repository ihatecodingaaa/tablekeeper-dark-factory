"""Seating-repair planner for a table closure (stage 4, S4-R2, S4-R1a).

Pure: no service state, no clock, no I/O. Given the considered bookings, the
fixed bookings, previously applied closures, the ranked table options and the
proposed closure, it returns the exact lexicographic minimum of

    (moved, unused, rank vector in ascending reference order)

where moved counts bookings whose table SET changes, unused sums
(capacity - party_size) with capacity taken from each booking's OWN accepted
terms, and the rank vector lists each booking's option rank (singles in
fixture order, then pairs in combinable order, from 0).

The search is depth-first branch and bound over bookings in ascending
reference order. Its work is a deterministic count of tried candidates; when
that count exceeds `budget` the answer is ("over_budget",), never a wall-clock
guess. With 6 tables, 4 pairs and 6 considered bookings there are at most 10
candidates per booking, so even an unpruned search tries 1,111,110 nodes,
within the default budget of 2,000,000.
"""
from __future__ import annotations

DEFAULT_BUDGET = 2_000_000


class _OverBudget(Exception):
    pass


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def _candidates(booking, options, fixed, blocked):
    """(changed, unused, rank, table_ids) options a booking may take, best first."""
    current = frozenset(booking["table_ids"])
    caps = booking["capacities"]
    start, end, party = booking["start"], booking["end"], booking["party_size"]
    out = []
    for option in options:
        ids = tuple(option["table_ids"])
        if any(t not in caps for t in ids):
            continue
        capacity = sum(caps[t] for t in ids)
        if capacity < party:
            continue
        if any(t in ids and _overlaps(start, end, s, e) for t, s, e in blocked):
            continue
        if any(set(ids) & set(f["table_ids"]) and _overlaps(start, end, f["start"], f["end"])
               for f in fixed):
            continue
        out.append((int(frozenset(ids) != current), capacity - party, option["rank"], ids))
    out.sort()
    return out


def plan(considered, fixed, closures, options, proposed_closure, budget=DEFAULT_BUDGET,
         stats=None):
    """Exact optimal seating repair.

    considered, fixed: lists of {reference, table_ids, party_size, start, end,
        capacities} (fixed only needs table_ids, start, end); instants are aware.
    closures: previously applied closures as (table_id, start, end).
    options: [{"rank": int, "table_ids": [...]}] - singles in fixture order, then
        declared pairs in combinable order, each with its canonical table_ids.
    proposed_closure: (table_id, start, end).
    stats: optional dict that receives {"nodes": tried candidates}.

    Returns ("ok", assignments, moved, unused) with assignments
    [{reference, table_ids, changed}] in ascending reference order,
    ("infeasible",) or ("over_budget",).
    """
    bookings = sorted(considered, key=lambda b: b["reference"])
    blocked = [tuple(c) for c in closures] + [tuple(proposed_closure)]
    candidates = []
    for booking in bookings:
        options_for = _candidates(booking, options, fixed, blocked)
        if not options_for:
            if stats is not None:
                stats["nodes"] = 0
            return ("infeasible",)
        candidates.append(options_for)

    n = len(bookings)
    overlap = [[i != j and _overlaps(bookings[i]["start"], bookings[i]["end"],
                                     bookings[j]["start"], bookings[j]["end"])
                for j in range(n)] for i in range(n)]
    # Independent per-booking minima of the remaining bookings: a valid lower bound.
    min_moved = [0] * (n + 1)
    min_unused = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        min_moved[i] = min_moved[i + 1] + min(c[0] for c in candidates[i])
        min_unused[i] = min_unused[i + 1] + min(c[1] for c in candidates[i])

    best = {"key": None, "choice": None}
    chosen = [None] * n
    ranks: list[int] = []
    nodes = 0

    def search(i, moved, unused):
        nonlocal nodes
        if i == n:
            key = (moved, unused, tuple(ranks))
            if best["key"] is None or key < best["key"]:
                best["key"], best["choice"] = key, list(chosen)
            return
        for candidate in candidates[i]:
            nodes += 1
            if nodes > budget:
                raise _OverBudget
            changed, spare, rank, ids = candidate
            moved_next, unused_next = moved + changed, unused + spare
            if best["key"] is not None:
                bound = (moved_next + min_moved[i + 1], unused_next + min_unused[i + 1])
                best_mu = best["key"][:2]
                if bound > best_mu:
                    continue
                if bound == best_mu and tuple(ranks) + (rank,) > best["key"][2][:i + 1]:
                    continue
            if any(overlap[i][j] and set(ids) & set(chosen[j][3]) for j in range(i)):
                continue
            chosen[i] = candidate
            ranks.append(rank)
            search(i + 1, moved_next, unused_next)
            ranks.pop()
            chosen[i] = None

    try:
        search(0, 0, 0)
    except _OverBudget:
        if stats is not None:
            stats["nodes"] = nodes
        return ("over_budget",)
    if stats is not None:
        stats["nodes"] = nodes
    if best["key"] is None:
        return ("infeasible",)
    moved, unused, _ = best["key"]
    assignments = [{"reference": booking["reference"], "table_ids": list(choice[3]),
                    "changed": bool(choice[0])}
                   for booking, choice in zip(bookings, best["choice"])]
    return ("ok", assignments, moved, unused)
