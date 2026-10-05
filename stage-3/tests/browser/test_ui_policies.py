"""Stage 3 in the browser: the grid, booking and lookup follow the policy in force for a date."""
import datetime as dt
import re

from playwright.sync_api import expect

from uikit import WEEK, future_date, search, sign_in

POLICY_DATE = dt.date.fromisoformat(future_date())
MIDDOT = chr(0xB7)


def publish(api, effective_from, **changes):
    body = {
        "effective_from": effective_from.isoformat(),
        "slot_minutes": 60,
        "reservation_duration_minutes": 120,
        "cancellation_cutoff_minutes": 60,
        "opening_hours": [{"weekday": d, "opens": "18:00", "closes": "22:00"} for d in WEEK],
        "capacities": {"t_1": 4, "t_2": 6, "t_3": 2, "t_garden": 6},
    }
    body.update(changes)
    token = api.login("mia@example.com")["token"]
    status, data = api.call("POST", "/restaurants/r_anker/policies", body, token=token,
                            key=f"policy-{effective_from}")
    assert status == 201, data
    return data


def grid_times(page):
    return page.get_by_test_id("availability-grid").locator("tbody th").all_text_contents()


def test_grid_follows_the_policy_for_the_searched_date(page, api):
    publish(api, POLICY_DATE)
    sign_in(page)
    page.goto("/")
    search(page, POLICY_DATE.isoformat(), party_size=3)
    expect(page.get_by_test_id("availability-grid")).to_be_visible()
    # Hourly slots from 18:00 whose 120-minute booking ends by 22:00.
    assert grid_times(page) == ["18:00", "19:00", "20:00"]
    expect(page.get_by_test_id("slot-t_1-18:30")).to_have_count(0)
    # Table 1 seats 4 under the policy, so it now fits a party of 3.
    expect(page.get_by_test_id("slot-t_1-19:00")).to_have_attribute("data-available", "true")
    header = page.get_by_test_id("availability-grid").locator("thead")
    expect(header).to_contain_text("Seats 4")
    expect(header).to_contain_text("Seats 6")
    # The day before the policy still uses the restaurant's own half-hour grid.
    search(page, (POLICY_DATE - dt.timedelta(days=1)).isoformat(), party_size=3)
    expect(page.get_by_test_id("slot-t_1-17:30")).to_have_attribute("data-available", "false")
    expect(page.get_by_test_id("slot-t_1-17:30")).to_contain_text("Too small")


def test_booking_under_a_policy_shows_its_seats_and_accepted_cutoff(page, api):
    publish(api, POLICY_DATE)
    sign_in(page)
    page.goto("/")
    search(page, POLICY_DATE.isoformat(), party_size=5)
    page.get_by_test_id("slot-t_2-20:00").click()
    expect(page.get_by_test_id("booking-summary")).to_contain_text(f"Table 2 {MIDDOT} seats 6")
    page.get_by_test_id("booking-submit").click()
    reference = page.get_by_test_id("confirmation-reference")
    expect(reference).to_have_text(re.compile(r"^[A-Z0-9]{6,12}$"))
    ref = reference.text_content()
    status, booked = api.call("GET", f"/reservations/{ref}", token=api.login()["token"])
    assert status == 200 and booked["accepted_terms"]["policy_version"] == 1
    assert booked["ends_at"].startswith(f"{POLICY_DATE.isoformat()}T22:00")
    page.goto("/lookup")
    page.get_by_test_id("lookup-reference-input").fill(ref)
    page.get_by_test_id("lookup-submit").click()
    expect(page.get_by_test_id("reservation-status")).to_have_text("confirmed")
    expect(page.get_by_test_id("reservation-detail")).to_contain_text("Free cancellation until 1 hour")


def test_unavailable_cells_say_why(page, api):
    api.book(api.login("bob@example.com")["token"], "t_2", "19:00", party_size=2)
    sign_in(page)
    page.goto("/")
    search(page, future_date(), party_size=3)
    expect(page.get_by_test_id("slot-t_2-19:00")).to_contain_text("Booked")
    expect(page.get_by_test_id("slot-t_1-19:00")).to_contain_text("Too small")
    expect(page.get_by_test_id("slot-t_garden-19:00")).to_have_attribute("data-available", "true")


def test_lookup_and_cancel_work_with_stage3_fields(page, api):
    booked = api.book(api.login()["token"], "t_3", "18:00")
    assert booked["revision"] == 1 and "accepted_terms" in booked
    sign_in(page)
    page.goto(f"/lookup?reference={booked['reference']}")
    expect(page.get_by_test_id("reservation-status")).to_have_text("confirmed")
    expect(page.get_by_test_id("reservation-detail")).to_contain_text("Free cancellation until 2 hours")
    page.get_by_test_id("reservation-cancel-button").click()
    expect(page.get_by_test_id("reservation-status")).to_have_text("cancelled")
    status, decision = api.call("GET", f"/reservations/{booked['reference']}/decision",
                                token=api.login()["token"])
    assert status == 200 and decision["revision"] == 2
