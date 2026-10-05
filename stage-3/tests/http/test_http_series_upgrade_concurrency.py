"""Series on imported stage-2 bookings, and concurrent adoptions (stage 3 'Recurring reservations')."""
import json
import pathlib
import subprocess
import sys
import threading

import pytest

from httpkit import assert_error
from s3httpkit import day, local, s3_fixture, series_body

STAGE_2 = pathlib.Path(__file__).resolve().parents[3] / "stage-2"

# Runs in a separate interpreter: the frozen stage-2 service has the same package name.
_STAGE2_SCRIPT = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from tablekeeper.service import Service
svc = Service()
svc.reset(json.loads(sys.argv[2]))
token = svc.login({"email": "ada@example.com", "password": "correct horse"})["token"]
user_id = svc.authenticate("Bearer " + token)
body = json.loads(sys.argv[3])
status, booking = svc.create_reservation(user_id, "stage2-key", body)
print(json.dumps({"export": svc.export_state(), "token": token, "status": status,
                  "body": body, "booking": booking}))
"""


@pytest.fixture
def s3(client):
    assert client.request("POST", "/_test/reset", s3_fixture()).status == 204
    return client


@pytest.fixture
def stage2_export():
    if not (STAGE_2 / "tablekeeper" / "service.py").is_file():
        pytest.skip("frozen stage-2/ folder not present next to stage-3/")
    fixture = s3_fixture()
    for restaurant in fixture["restaurants"]:
        restaurant.pop("manager_user_ids", None)  # a stage-3 field
    body = {"restaurant_id": "r_anker", "table_id": "t_2", "party_size": 2,
            "starts_at_local": local(day(20), "19:00")}
    out = subprocess.run([sys.executable, "-c", _STAGE2_SCRIPT, str(STAGE_2), json.dumps(fixture),
                          json.dumps(body)], capture_output=True, text=True, check=True,
                         cwd=str(STAGE_2), timeout=120)
    data = json.loads(out.stdout)
    assert data["status"] == 201
    return data


def test_a_booking_imported_from_stage_2_can_anchor_a_series(s3, stage2_export):
    assert s3.request("POST", "/_test/import", stage2_export["export"]).status == 204
    token = stage2_export["token"]  # the stage-2 session still works
    ref = stage2_export["booking"]["reference"]
    current = s3.request("GET", f"/reservations/{ref}", token=token).json()
    assert current["revision"] == 1 and current["accepted_terms"]["policy_version"] == 0
    resp = s3.request("POST", "/series", series_body(ref, count=3), token=token, key="adopt")
    assert resp.status == 201, resp
    series = resp.json()
    assert series["occurrences"][0]["reservation"] == current
    assert [o["reservation"]["starts_at_local"] for o in series["occurrences"]] == [
        local(day(20 + 7 * i), "19:00") for i in range(3)]
    # The original stage-2 booking retry still replays its stage-2 body exactly.
    replay = s3.request("POST", "/reservations", stage2_export["body"], token=token,
                        key="stage2-key")
    assert (replay.status, replay.json()) == (200, stage2_export["booking"])


def run_parallel(count, call):
    barrier = threading.Barrier(count)
    results = [None] * count

    def worker(i):
        barrier.wait()
        try:
            results[i] = call(i)
        except Exception as exc:  # surface transport failures
            results[i] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not [r for r in results if isinstance(r, Exception)], results
    return results


def test_concurrent_adoptions_of_one_anchor_admit_exactly_one(s3):
    ada = s3.login("ada@example.com")
    body = {"restaurant_id": "r_anker", "table_id": "t_2", "party_size": 2,
            "starts_at_local": local(day(20), "19:00")}
    anchor = s3.request("POST", "/reservations", body, token=ada, key="anchor").json()
    results = run_parallel(12, lambda i: s3.request(
        "POST", "/series", series_body(anchor["reference"], count=3), token=ada, key=f"race-{i}"))
    created = [r for r in results if r.status == 201]
    assert len(created) == 1, [r.status for r in results]
    for resp in results:
        if resp.status != 201:
            assert_error(resp, 409, "already_in_series")
    assert len(s3.request("GET", "/reservations", token=ada).json()["reservations"]) == 3


def test_concurrent_identical_adoptions_take_effect_once(s3):
    ada = s3.login("ada@example.com")
    body = {"restaurant_id": "r_anker", "table_id": "t_2", "party_size": 2,
            "starts_at_local": local(day(20), "19:00")}
    anchor = s3.request("POST", "/reservations", body, token=ada, key="anchor").json()
    results = run_parallel(10, lambda i: s3.request(
        "POST", "/series", series_body(anchor["reference"], count=2), token=ada, key="same"))
    statuses = sorted(r.status for r in results)
    assert statuses.count(201) == 1 and statuses.count(200) == 9, statuses
    assert all(r.json() == results[0].json() for r in results)
    assert len(s3.request("GET", "/reservations", token=ada).json()["reservations"]) == 2
