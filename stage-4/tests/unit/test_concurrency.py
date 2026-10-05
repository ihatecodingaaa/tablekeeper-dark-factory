"""Spec §1 and §7: no double booking and one 201 per key under concurrent requests."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from tk_unit import ADA, body
from tablekeeper.errors import ApiError


def run_parallel(n, fn):
    barrier = threading.Barrier(n)

    def task(i):
        barrier.wait()
        try:
            return fn(i)
        except ApiError as exc:
            return (exc.status, exc.code)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(task, range(n)))


def test_50_threads_booking_one_slot_give_exactly_one_success(world):
    users = [world.ada, world.bob]
    results = run_parallel(50, lambda i: world.svc.create_reservation(
        users[i % 2], f"race-{i}", body(table_id="t_2", at="19:00"))[0])
    assert results.count(201) == 1
    assert results.count((409, "table_unavailable")) == 49
    total = (len(world.svc.list_reservations(world.ada)["reservations"])
             + len(world.svc.list_reservations(world.bob)["reservations"]))
    assert total == 1


def test_20_threads_same_key_give_exactly_one_201(world):
    results = run_parallel(20, lambda i: world.svc.create_reservation(world.ada, "same", body()))
    statuses = [r[0] for r in results]
    assert statuses.count(201) == 1 and statuses.count(200) == 19
    assert len({r[1]["reference"] for r in results}) == 1
    assert len(world.svc.list_reservations(world.ada)["reservations"]) == 1


def test_concurrent_moves_and_bookings_never_double_book(world):
    a = world.booked(table_id="t_1", at="19:00", party_size=2)

    def op(i):
        if i % 2:
            return world.svc.move_reservations(world.ada, f"mv-{i}",
                                               {"moves": [{"reference": a["reference"], "table_id": "t_3"}]})[0]
        return world.svc.create_reservation(world.bob, f"bk-{i}",
                                            body(table_id="t_3", at="19:00", party_size=2))[0]

    run_parallel(30, op)
    on_t3 = [r for u in (world.ada, world.bob)
             for r in world.svc.list_reservations(u)["reservations"]
             if r["table_id"] == "t_3" and r["status"] == "confirmed"]
    assert len(on_t3) == 1


def test_50_concurrent_logins_finish_quickly(world):
    started = time.perf_counter()
    results = run_parallel(50, lambda i: world.svc.login({"email": ADA["email"],
                                                          "password": ADA["password"]}))
    elapsed = time.perf_counter() - started
    assert all(isinstance(r, dict) and r["user_id"] == "u_ada" for r in results)
    assert len({r["token"] for r in results}) == 50
    assert elapsed < 5.0, elapsed


def test_concurrent_signups_same_email_one_wins(world):
    results = run_parallel(10, lambda i: world.svc.signup(
        {"email": "race@example.com", "password": "long enough", "display_name": f"R{i}"}))
    wins = [r for r in results if isinstance(r, dict)]
    assert len(wins) == 1
    assert results.count((409, "email_taken")) == 9
