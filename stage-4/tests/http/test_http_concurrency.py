"""Concurrent writes over real HTTP connections (spec 1, 2 resource limits, 7)."""
import threading

from httpkit import assert_error, booking


def run_parallel(count, call):
    """Start `count` calls together behind a barrier; return their responses in order."""
    barrier = threading.Barrier(count)
    results = [None] * count

    def worker(i):
        barrier.wait()
        try:
            results[i] = call(i)
        except Exception as exc:  # surface transport failures as test failures
            results[i] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, errors
    return results


def test_fifty_parallel_bookings_of_one_table_slot_admit_exactly_one(client, ada):
    body = booking("t_2", "19:00")
    results = run_parallel(50, lambda i: client.request("POST", "/reservations", body,
                                                        token=ada, key=f"race-{i}"))
    statuses = sorted(r.status for r in results)
    assert statuses.count(201) == 1, statuses
    for resp in results:
        if resp.status != 201:
            assert_error(resp, 409, "table_unavailable")
    listed = client.request("GET", "/reservations", token=ada).json()["reservations"]
    assert len(listed) == 1


def test_twenty_parallel_identical_requests_take_effect_once(client, ada):
    body = booking("t_2", "19:00")
    results = run_parallel(20, lambda i: client.request("POST", "/reservations", body,
                                                        token=ada, key="same-key"))
    statuses = [r.status for r in results]
    assert statuses.count(201) == 1 and statuses.count(200) == 19, statuses
    bodies = [r.json() for r in results]
    assert all(b == bodies[0] for b in bodies), bodies
    listed = client.request("GET", "/reservations", token=ada).json()["reservations"]
    assert [r["reference"] for r in listed] == [bodies[0]["reference"]]


def test_fifty_requests_in_flight_never_produce_5xx(client, ada):
    def mixed(i):
        if i % 3 == 0:
            return client.request("GET", "/health")
        if i % 3 == 1:
            return client.request("GET", "/reservations", token=ada)
        return client.request("POST", "/reservations", booking("t_1", "19:00"), token=ada,
                              key=f"mix-{i}")

    results = run_parallel(50, mixed)
    assert all(r.status < 500 for r in results), [r for r in results if r.status >= 500]
