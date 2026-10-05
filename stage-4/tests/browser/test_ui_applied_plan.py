"""Stage 4 in the browser: confirmation, lookup and grid reflect an applied seating plan (S4-R7, D4)."""
import datetime as dt
import re
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from uikit import future_date, search, sign_in

REFERENCE = re.compile(r"^[A-Z0-9]{6,12}$")


def instant(date: str, hhmm: str, zone="Europe/Berlin") -> str:
    hour, minute = map(int, hhmm.split(":"))
    moment = dt.datetime.combine(dt.date.fromisoformat(date), dt.time(hour, minute), tzinfo=ZoneInfo(zone))
    return moment.isoformat()


def close_table(api, table_id, date, start="17:00", end="22:00"):
    """A manager previews and applies the official seating repair for a table closure."""
    mia = api.login("mia@example.com")["token"]
    body = {"table_id": table_id, "from": instant(date, start), "to": instant(date, end)}
    status, plan = api.call("POST", "/restaurants/r_anker/replans", body, token=mia, key=f"plan-{table_id}")
    assert status == 201, plan
    status, applied = api.call("POST", f"/restaurants/r_anker/replans/{plan['plan_id']}/apply", {},
                               token=mia, key=f"apply-{table_id}")
    assert status == 201, applied
    return plan


def test_a_replayed_confirmation_shows_the_tables_after_a_repair(page, api):
    date = future_date()
    sign_in(page)
    page.goto("/")
    search(page, date, party_size=2)
    page.get_by_test_id("slot-t_2-19:00").click()
    page.get_by_test_id("booking-submit").click()
    reference = page.get_by_test_id("confirmation-reference")
    expect(reference).to_have_text(REFERENCE)
    ref = reference.text_content()
    expect(page.get_by_test_id("confirmation-tables")).to_have_text("Table 2")

    plan = close_table(api, "t_2", date)
    moved_to = plan["assignments"][0]["table_ids"]
    assert moved_to != ["t_2"]

    # The unchanged form replays the original receipt; the screen shows the booking as it is now.
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("confirmation-reference")).to_have_text(ref)
    expect(page.get_by_test_id("confirmation-tables")).not_to_have_text("Table 2")
    expect(page.get_by_test_id("booking-error")).to_have_count(0)
    # The grid treats the closed table as unavailable.
    expect(page.get_by_test_id("slot-t_2-19:00")).to_have_attribute("data-available", "false")

    page.goto("/lookup")
    page.get_by_test_id("lookup-reference-input").fill(ref)
    page.get_by_test_id("lookup-submit").click()
    expect(page.get_by_test_id("reservation-status")).to_have_text("confirmed")
    expect(page.get_by_test_id("reservation-tables")).not_to_have_text("Table 2")


def test_a_closed_table_is_unavailable_in_a_new_search(page, api):
    date = future_date()
    close_table(api, "t_garden", date)
    page.goto("/")
    search(page, date, party_size=2)
    for time in ("17:00", "19:00", "20:30"):
        expect(page.get_by_test_id(f"slot-t_garden-{time}")).to_have_attribute("data-available", "false")
        expect(page.get_by_test_id(f"slot-t_garden-{time}")).to_contain_text("Booked")
    expect(page.get_by_test_id("slot-t_1-19:00")).to_have_attribute("data-available", "true")


def test_a_confirmation_replayed_after_cancelling_says_so(page, api):
    sign_in(page)
    page.goto("/")
    search(page, future_date(), party_size=2)
    page.get_by_test_id("slot-t_3-18:00").click()
    page.get_by_test_id("booking-submit").click()
    ref = page.get_by_test_id("confirmation-reference").text_content()
    status, _ = api.call("POST", f"/reservations/{ref}/cancel", token=api.login()["token"])
    assert status == 200
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("confirmation-reference")).to_have_text(ref)
    expect(page.get_by_test_id("confirmation")).to_contain_text("Booking since cancelled")
