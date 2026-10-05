"""My Evening (/evening/{ref}): summary, guarantee, calendar, share, preferences, amend and cancel."""
import re

import pytest
from playwright.sync_api import expect

from uikit import sign_in
from browserxkit import booked, no_horizontal_page_scroll


def open_evening(page, ref):
    page.goto(f"/evening/{ref}")
    expect(page.get_by_test_id("evening-summary")).to_be_visible()


def test_signed_out_visitors_are_asked_to_sign_in(page, api):
    reservation, _ = booked(api)
    page.goto(f"/evening/{reservation['reference']}")
    expect(page.get_by_test_id("evening-page").get_by_role("link", name="Sign in")).to_have_attribute(
        "href", f"/login?next=%2Fevening%2F{reservation['reference']}")


def test_an_unknown_or_someone_elses_evening_is_not_shown(page, api):
    theirs, _ = booked(api, email="bob@example.com")
    sign_in(page)
    page.goto(f"/evening/{theirs['reference']}")
    expect(page.get_by_text("We couldn't find this evening")).to_be_visible()
    expect(page.get_by_test_id("evening-summary")).to_have_count(0)


def test_the_evening_summary_and_history(page, api):
    reservation, _ = booked(api, party_size=3)
    sign_in(page)
    open_evening(page, reservation["reference"])
    summary = page.get_by_test_id("evening-summary")
    expect(summary).to_contain_text("Zum Anker")
    expect(summary).to_contain_text("19:00")
    expect(summary).to_contain_text("3 guests")
    expect(page.get_by_test_id("evening-reference")).to_have_text(reservation["reference"])
    expect(page.get_by_test_id("evening-tables")).to_contain_text("Table 2")
    expect(page.get_by_test_id("evening-status")).to_contain_text("Confirmed")
    expect(page.get_by_test_id("evening-history")).to_contain_text("Booked")


def test_hold_a_guarantee_and_read_what_happened_to_the_money(page, api):
    reservation, token = booked(api, party_size=2)
    sign_in(page)
    open_evening(page, reservation["reference"])
    expect(page.get_by_test_id("guarantee-state")).to_contain_text("No guarantee")
    page.get_by_test_id("guarantee-hold").click()
    expect(page.get_by_test_id("guarantee-state")).to_contain_text("Held")
    expect(page.get_by_test_id("guarantee-amount")).to_have_text(chr(0x20AC) + "30.00")
    timeline = page.get_by_test_id("guarantee-timeline")
    expect(timeline).to_contain_text("Held")
    expect(timeline).to_contain_text("by you")
    status, view = api.call("GET", f"/x/reservations/{reservation['reference']}/guarantee", token=token)
    assert status == 200 and view["state"] == "HELD" and view["amount_minor"] == 3000


def test_calendar_file_downloads_without_secrets(page, api):
    reservation, token = booked(api)
    sign_in(page)
    open_evening(page, reservation["reference"])
    expect(page.get_by_test_id("calendar-google")).to_have_attribute(
        "href", re.compile(r"^https://calendar\.google\.com/calendar/render\?action=TEMPLATE"))
    with page.expect_download() as info:
        page.get_by_test_id("calendar-ics").click()
    path = info.value.path()
    text = open(path, "rb").read().decode("utf-8")
    assert text.startswith("BEGIN:VCALENDAR") and reservation["reference"] in text
    assert token not in text
    expect(page.get_by_test_id("calendar-downloaded")).to_be_visible()


def test_share_copies_text_without_a_token(page, api):
    reservation, token = booked(api)
    sign_in(page)
    open_evening(page, reservation["reference"])
    page.evaluate("() => { delete Navigator.prototype.share; }")  # force the copy fallback
    page.get_by_test_id("share-button").click()
    expect(page.get_by_test_id("share-copied")).to_be_visible()
    copied = page.evaluate("() => navigator.clipboard.readText()")
    assert reservation["reference"] in copied and token not in copied


def test_preferences_save_through_the_extras_api(page, api):
    reservation, token = booked(api)
    sign_in(page)
    open_evening(page, reservation["reference"])
    form = page.get_by_test_id("evening-preferences")
    form.get_by_label("vegetarian").check()
    form.get_by_test_id("prefs-allergies").fill("Peanuts")
    form.get_by_test_id("prefs-quiet").check()
    form.get_by_test_id("prefs-save").click()
    expect(page.get_by_test_id("prefs-saved")).to_be_visible()
    status, prefs = api.call("GET", f"/x/reservations/{reservation['reference']}/preferences", token=token)
    assert status == 200 and "vegetarian" in prefs["dietary"] and prefs["allergies"] == "Peanuts"
    assert prefs["quiet"] is True
    # The official booking itself is untouched by preferences.
    status, official = api.call("GET", f"/reservations/{reservation['reference']}", token=token)
    assert official["revision"] == reservation["revision"]


def test_amend_and_cancel_use_the_official_endpoints(page, api):
    reservation, token = booked(api, party_size=2)
    sign_in(page)
    open_evening(page, reservation["reference"])
    page.get_by_test_id("manage-party").fill("3")
    page.get_by_test_id("manage-save").click()
    expect(page.get_by_test_id("evening-summary")).to_contain_text("3 guests")
    page.get_by_test_id("manage-cancel").click()
    dialog = page.get_by_test_id("x-dialog")
    expect(dialog).to_be_visible()
    page.get_by_test_id("x-dialog-cancel").click()   # keep it
    expect(dialog).to_have_count(0)
    page.get_by_test_id("manage-cancel").click()
    page.get_by_test_id("x-dialog-confirm").click()
    expect(page.get_by_test_id("evening-status")).to_contain_text("Cancelled")
    status, official = api.call("GET", f"/reservations/{reservation['reference']}", token=token)
    assert official["status"] == "cancelled"


@pytest.mark.parametrize("width", [375, 1280])
def test_the_evening_fits_the_viewport(page, api, width):
    reservation, _ = booked(api)
    sign_in(page)
    page.set_viewport_size({"width": width, "height": 900})
    open_evening(page, reservation["reference"])
    page.get_by_test_id("guarantee-hold").click()
    expect(page.get_by_test_id("guarantee-state")).to_contain_text("Held")
    assert no_horizontal_page_scroll(page)
