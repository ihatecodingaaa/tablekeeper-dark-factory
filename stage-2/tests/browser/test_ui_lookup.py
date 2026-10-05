"""Lookup screen: found, not found, cancel, refused cancel, combined tables (stage 2 Lookup)."""
from playwright.sync_api import expect

from uikit import sign_in


def look_up(page, reference):
    page.goto("/lookup")
    page.get_by_test_id("lookup-reference-input").fill(reference)
    page.get_by_test_id("lookup-submit").click()


def test_look_up_then_cancel(page, api):
    booked = api.book(api.login()["token"], "t_2", "19:00", party_size=3)
    sign_in(page)
    look_up(page, booked["reference"])
    detail = page.get_by_test_id("reservation-detail")
    expect(detail).to_be_visible()
    expect(page.get_by_test_id("reservation-status")).to_have_text("confirmed")
    expect(page.get_by_test_id("reservation-tables")).to_contain_text("2")
    expect(detail).to_contain_text("Zum Anker")
    expect(detail).to_contain_text("19:00")
    expect(page.get_by_test_id("reservation-error")).to_have_count(0)
    page.get_by_test_id("reservation-cancel-button").click()
    expect(page.get_by_test_id("reservation-status")).to_have_text("cancelled")
    expect(page.get_by_test_id("reservation-cancel-button")).to_have_count(0)
    expect(page.get_by_test_id("reservation-error")).to_have_count(0)
    status, body = api.call("GET", f"/reservations/{booked['reference']}",
                            token=api.login()["token"])
    assert status == 200 and body["status"] == "cancelled"
    # Looking it up again shows the cancelled state, still without a cancel button.
    look_up(page, booked["reference"])
    expect(page.get_by_test_id("reservation-status")).to_have_text("cancelled")
    expect(page.get_by_test_id("reservation-cancel-button")).to_have_count(0)


def test_unknown_reference_shows_reservation_error(page):
    sign_in(page)
    look_up(page, "NOPE0000")
    expect(page.get_by_test_id("reservation-error")).to_be_visible()
    expect(page.get_by_test_id("reservation-detail")).to_have_count(0)


def test_someone_elses_reference_is_not_found(page, api):
    booked = api.book(api.login("bob@example.com")["token"], "t_1", "18:00")
    sign_in(page)
    look_up(page, booked["reference"])
    expect(page.get_by_test_id("reservation-error")).to_be_visible()
    expect(page.get_by_test_id("reservation-detail")).to_have_count(0)


def test_refused_cancel_shows_error_and_keeps_booking(page, api):
    booked = api.book(api.login()["token"], "s_1", "19:00", restaurant="r_strict", key="strict")
    sign_in(page)
    look_up(page, booked["reference"])
    page.get_by_test_id("reservation-cancel-button").click()
    expect(page.get_by_test_id("reservation-error")).to_be_visible()
    expect(page.get_by_test_id("reservation-status")).to_have_text("confirmed")
    expect(page.get_by_test_id("reservation-detail")).to_be_visible()


def test_combined_booking_lists_every_table(page, api):
    booked = api.book(api.login()["token"], table_ids=["t_2", "t_1"], time="20:00",
                      party_size=5, key="pair")
    assert booked["table_ids"] == ["t_1", "t_2"]
    sign_in(page)
    look_up(page, booked["reference"])
    tables = page.get_by_test_id("reservation-tables")
    expect(tables).to_contain_text("1")
    expect(tables).to_contain_text("2")


def test_signed_out_lookup_asks_to_sign_in(page):
    look_up(page, "ABC123")
    error = page.get_by_test_id("reservation-error")
    expect(error).to_be_visible()
    expect(error.get_by_role("link", name="Sign in")).to_be_visible()


def test_confirmation_link_opens_the_booking_in_lookup(page, api):
    booked = api.book(api.login()["token"], "t_3", "18:30")
    sign_in(page)
    page.goto(f"/lookup?reference={booked['reference']}")
    expect(page.get_by_test_id("reservation-status")).to_have_text("confirmed")
    expect(page.get_by_test_id("lookup-reference-input")).to_have_value(booked["reference"])
