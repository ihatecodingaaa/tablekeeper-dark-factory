"""Notifications, passport, control room, simulator, search extras and the PWA manifest."""
import pytest
from playwright.sync_api import expect

from uikit import future_date, search, sign_in
from browserxkit import booked, instant, no_horizontal_page_scroll


def hold(api, reference, token):
    status, view = api.call("POST", f"/x/reservations/{reference}/guarantee", {}, token=token,
                            key=f"hold-{reference}")
    assert status == 201, view
    return view


# -- notifications and passport ------------------------------------------------------


def test_notification_centre_lists_messages_newest_first(page, api):
    reservation, token = booked(api)
    hold(api, reservation["reference"], token)
    sign_in(page)
    page.goto("/notifications")
    items = page.get_by_test_id("notification")
    expect(items.first).to_be_visible()
    expect(page.get_by_test_id("notification-list")).to_contain_text(reservation["reference"])
    expect(items.first.get_by_role("link")).to_have_attribute("href", f"/evening/{reservation['reference']}")


def test_notification_centre_has_an_empty_state(page, api):
    sign_in(page, "bob@example.com")
    page.goto("/notifications")
    expect(page.get_by_text("No messages yet")).to_be_visible()


def test_passport_lists_evenings_and_saves_default_preferences(page, api):
    reservation, token = booked(api)
    sign_in(page)
    page.goto("/passport")
    upcoming = page.get_by_test_id("passport-upcoming")
    expect(upcoming.first).to_contain_text("Zum Anker")
    expect(upcoming.first.get_by_role("link")).to_have_attribute("href", f"/evening/{reservation['reference']}")
    expect(page.get_by_test_id("passport-counts")).to_contain_text("Bookings made")
    prefs = page.get_by_test_id("passport-preferences")
    prefs.get_by_label("vegan").check()
    prefs.get_by_test_id("prefs-channel").select_option("email")
    prefs.get_by_test_id("prefs-save").click()
    expect(page.get_by_test_id("prefs-saved")).to_be_visible()
    status, saved = api.call("GET", "/x/me/preferences", token=token)
    assert status == 200 and saved["dietary"] == ["vegan"] and saved["channel"] == "email"


# -- control room ----------------------------------------------------------------------


def test_control_room_is_for_managers_only(page, api):
    sign_in(page)
    page.goto("/control-room")
    expect(page.get_by_text("For restaurant managers")).to_be_visible()


def test_control_room_shows_the_day_and_releases_a_guarantee_after_confirming(page, api):
    reservation, token = booked(api)
    hold(api, reservation["reference"], token)
    sign_in(page, "mia@example.com")
    page.goto("/control-room")
    page.get_by_test_id("cr-date").fill(future_date())
    page.get_by_test_id("cr-load").click()
    expect(page.get_by_test_id(f"cr-row-{reservation['reference']}")).to_contain_text("Ada")
    expect(page.get_by_test_id("cr-pressure")).to_contain_text("%")
    expect(page.get_by_test_id("cr-policy")).to_contain_text("Every 30 minutes")
    page.get_by_test_id(f"cr-release-{reservation['reference']}").click()
    page.get_by_test_id("x-dialog-confirm").click()
    expect(page.get_by_test_id(f"cr-guarantee-{reservation['reference']}")).to_contain_text("Released")
    status, view = api.call("GET", f"/x/reservations/{reservation['reference']}/guarantee", token=token)
    assert view["state"] == "RELEASED"


def test_capture_before_the_start_is_refused_in_the_page(page, api):
    reservation, token = booked(api)
    hold(api, reservation["reference"], token)
    sign_in(page, "mia@example.com")
    page.goto("/control-room")
    page.get_by_test_id(f"cr-capture-{reservation['reference']}").click()
    page.get_by_test_id("x-dialog-confirm").click()
    expect(page.get_by_test_id("cr-action-error")).to_be_visible()
    status, view = api.call("GET", f"/x/reservations/{reservation['reference']}/guarantee", token=token)
    assert view["state"] == "HELD"


# -- recovery simulator ------------------------------------------------------------------


def test_simulator_previews_without_side_effects_then_applies(page, api):
    date = future_date()
    reservation, token = booked(api, table_id="t_2", time="19:00")
    sign_in(page, "mia@example.com")
    page.goto("/simulator")
    page.get_by_test_id("sim-date").fill(date)
    page.get_by_test_id("sim-load").click()
    expect(page.get_by_test_id("sim-service")).to_contain_text(reservation["reference"])
    page.get_by_test_id("sim-table").select_option("t_2")
    page.get_by_test_id("sim-from").fill("17:00")
    page.get_by_test_id("sim-to").fill("22:00")
    page.get_by_test_id("sim-preview").click()
    row = page.get_by_test_id(f"sim-assignment-{reservation['reference']}")
    expect(row).to_contain_text("Table 2")
    expect(page.get_by_test_id("sim-messages")).to_contain_text("nothing has been sent")
    # The preview changed nothing.
    status, still = api.call("GET", f"/reservations/{reservation['reference']}", token=token)
    assert still["table_ids"] == ["t_2"] and still["revision"] == reservation["revision"]
    page.get_by_test_id("sim-apply").click()
    page.get_by_test_id("x-dialog-confirm").click()
    expect(page.get_by_test_id("sim-applied")).to_be_visible()
    status, moved = api.call("GET", f"/reservations/{reservation['reference']}", token=token)
    assert moved["table_ids"] != ["t_2"] and moved["starts_at_local"] == reservation["starts_at_local"]


def test_simulator_reports_when_no_repair_is_possible(page, api):
    date = future_date()
    # Without the Garden, a party of 6 needs a pair with Table 2, and Bob's party of 4 needs
    # Table 2 or a pair with it: both are considered, and they cannot both be seated.
    booked(api, table_id="t_garden", time="19:00", party_size=6)
    booked(api, email="bob@example.com", table_id="t_2", time="19:00", party_size=4)
    sign_in(page, "mia@example.com")
    page.goto("/simulator")
    page.get_by_test_id("sim-date").fill(date)
    page.get_by_test_id("sim-load").click()
    page.get_by_test_id("sim-table").select_option("t_garden")
    page.get_by_test_id("sim-from").fill("18:00")
    page.get_by_test_id("sim-to").fill("22:00")
    page.get_by_test_id("sim-preview").click()
    expect(page.get_by_test_id("sim-preview-error")).to_contain_text("No repair is possible")


# -- search extras -----------------------------------------------------------------------


def test_best_times_panel_appears_with_reasons(page, api):
    page.goto("/")
    search(page, future_date(), party_size=2)
    panel = page.get_by_test_id("best-times")
    expect(panel).to_be_visible()
    expect(panel.locator("button").first).to_contain_text(":")


def test_a_taken_table_offers_the_closest_options(page, api):
    sign_in(page)
    page.goto("/")
    search(page, future_date(), party_size=2)
    page.get_by_test_id("slot-t_2-19:00").click()
    booked(api, email="bob@example.com", table_id="t_2", time="19:00", key="bob-takes-it")
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("booking-error")).to_be_visible()
    options = page.get_by_test_id("recovery-options")
    expect(options).to_contain_text("This table just went")
    options.locator("button").first.click()
    expect(page.get_by_test_id("booking-form")).to_be_visible()
    expect(page.get_by_test_id("booking-summary")).not_to_contain_text("Table 2 " + chr(0xB7))


# -- PWA and layout ------------------------------------------------------------------------


def test_manifest_and_icons_are_served(page, base_url):
    response = page.request.get(base_url + "/assets/manifest.webmanifest")
    assert response.status == 200 and response.headers["content-type"].startswith("application/manifest+json")
    manifest = response.json()
    for icon in manifest["icons"]:
        assert page.request.get(base_url + icon["src"]).status == 200
    page.goto("/")
    expect(page.locator('link[rel="manifest"]')).to_have_attribute("href", "/assets/manifest.webmanifest")
    expect(page.locator('meta[name="theme-color"]')).to_have_attribute("content", "#a8462a")


@pytest.mark.parametrize("path,email", [("/notifications", "ada@example.com"), ("/passport", "ada@example.com"),
                                        ("/control-room", "mia@example.com"), ("/simulator", "mia@example.com")])
def test_extras_screens_fit_375(page, api, path, email):
    booked(api)
    sign_in(page, email)
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(path)
    page.wait_for_load_state("networkidle")
    assert no_horizontal_page_scroll(page)
