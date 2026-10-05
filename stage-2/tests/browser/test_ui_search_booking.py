"""Search grid, booking form, confirmation and the competing-client rules (stage 2; S2-R1, S2-R7, S2-R8)."""
import json
import re

from playwright.sync_api import expect

from uikit import closed_date, future_date, open_hafen_date, search, sign_in

REFERENCE = re.compile(r"^[A-Z0-9]{6,12}$")


def availability(api, date, party_size, restaurant="r_anker"):
    status, body = api.call(
        "GET", f"/availability?restaurant_id={restaurant}&date={date}&party_size={party_size}")
    assert status == 200, body
    return body


def watch_bookings(page):
    """Record every POST /reservations the page sends: (idempotency key, parsed body)."""
    sent = []

    def on_request(request):
        if request.method == "POST" and request.url.endswith("/reservations"):
            sent.append((request.headers.get("idempotency-key"), json.loads(request.post_data)))

    page.on("request", on_request)
    return sent


def test_grid_cells_match_the_api_exactly(page, api):
    date = future_date()
    api.book(api.login()["token"], "t_2", "19:00", party_size=2)  # occupies t_2 18:00-20:00 slots
    page.goto("/")
    search(page, date, party_size=2)
    expect(page.get_by_test_id("availability-grid")).to_be_visible()
    body = availability(api, date, 2)
    tables = ["t_1", "t_2", "t_3", "t_garden"]
    for slot in body["slots"]:
        hhmm = slot["starts_at_local"][11:16]
        for table in tables:
            cell = page.get_by_test_id(f"slot-{table}-{hhmm}")
            expected = "true" if table in slot["available_table_ids"] else "false"
            expect(cell).to_have_attribute("data-available", expected)
        offered = [o["table_ids"] for o in slot["available_options"] if len(o["table_ids"]) == 2]
        for pair in (["t_1", "t_2"], ["t_2", "t_3"]):
            pair_cell = page.get_by_test_id(f"slot-{pair[0]}+{pair[1]}-{hhmm}")
            if pair in offered:
                expect(pair_cell).to_have_attribute("data-available", "true")
            else:
                expect(pair_cell).to_have_count(0)
    expect(page.get_by_test_id("slot-t_2-19:00")).to_have_attribute("data-available", "false")
    expect(page.get_by_test_id("slot-t_1-19:00")).to_have_attribute("data-available", "true")


def test_party_too_large_for_a_table_marks_it_unavailable(page, api):
    page.goto("/")
    search(page, future_date(), party_size=5)
    expect(page.get_by_test_id("slot-t_1-19:00")).to_have_attribute("data-available", "false")
    expect(page.get_by_test_id("slot-t_garden-19:00")).to_have_attribute("data-available", "true")
    expect(page.get_by_test_id("slot-t_1+t_2-19:00")).to_have_attribute("data-available", "true")
    expect(page.get_by_test_id("slot-t_2+t_3-19:00")).to_have_attribute("data-available", "true")


def test_closed_day_shows_no_slots_instead_of_grid(page):
    page.goto("/")
    search(page, closed_date(), party_size=2, restaurant="r_hafen")
    expect(page.get_by_test_id("no-slots")).to_be_visible()
    expect(page.get_by_test_id("availability-grid")).to_have_count(0)


def test_signed_out_click_shows_auth_error_and_keeps_search(page):
    page.goto("/")
    search(page, future_date(), party_size=2)
    page.get_by_test_id("slot-t_1-19:00").click()
    error = page.get_by_test_id("auth-error")
    expect(error).to_be_visible()
    expect(error.get_by_role("link", name="Sign in")).to_have_attribute("href", re.compile(r"^/login"))
    expect(page.get_by_test_id("availability-grid")).to_be_visible()
    expect(page.get_by_test_id("booking-form")).to_have_count(0)


def test_clicking_an_unavailable_cell_does_nothing(page, api):
    api.book(api.login("bob@example.com")["token"], "t_2", "19:00")
    sign_in(page)
    page.goto("/")
    search(page, future_date(), party_size=2)
    cell = page.get_by_test_id("slot-t_2-19:00")
    expect(cell).to_have_attribute("data-available", "false")
    cell.click()
    expect(page.get_by_test_id("booking-form")).to_have_count(0)


def test_book_a_table_and_resubmit_returns_the_same_reference(page, api):
    sign_in(page)
    sent = watch_bookings(page)
    page.goto("/")
    search(page, future_date(), party_size=3)
    page.get_by_test_id("slot-t_2-19:00").click()
    form = page.get_by_test_id("booking-form")
    expect(form).to_be_visible()
    summary = page.get_by_test_id("booking-summary")
    expect(summary).to_contain_text("Table 2")
    expect(summary).to_contain_text("19:00")
    expect(page.get_by_test_id("booking-party-size")).to_have_value("3")
    page.get_by_test_id("booking-submit").click()

    reference = page.get_by_test_id("confirmation-reference")
    expect(reference).to_have_text(REFERENCE)
    first = reference.text_content()
    details = page.get_by_test_id("confirmation-details")
    expect(details).to_contain_text("Zum Anker")
    expect(details).to_contain_text("19:00")
    expect(page.get_by_test_id("confirmation-tables")).to_contain_text("2")
    expect(page.get_by_test_id("booking-error")).to_have_count(0)
    expect(form).to_be_visible()  # the form stays after success

    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("confirmation-reference")).to_have_text(first)
    expect(page.get_by_test_id("booking-error")).to_have_count(0)
    expect(page.get_by_test_id("booking-uncertain")).to_have_count(0)
    assert len(sent) == 2 and sent[0] == sent[1]  # same key, same body
    token = api.login()["token"]
    assert [r["reference"] for r in api.reservations(token)] == [first]
    # The grid now shows the booking as the diner's own.
    expect(page.get_by_test_id("slot-t_2-19:00")).to_have_attribute("data-available", "false")


def test_changing_a_field_makes_a_new_booking_request(page, api):
    sign_in(page)
    sent = watch_bookings(page)
    page.goto("/")
    search(page, future_date(), party_size=2)
    page.get_by_test_id("slot-t_garden-19:00").click()
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("confirmation-reference")).to_have_text(REFERENCE)
    page.get_by_test_id("booking-party-size").fill("4")
    page.get_by_test_id("booking-submit").click()
    # Same table and time, so the new request collides with the first booking.
    expect(page.get_by_test_id("booking-error")).to_be_visible()
    expect(page.get_by_test_id("confirmation")).to_have_count(0)
    assert len(sent) == 2
    assert sent[0][0] != sent[1][0]
    assert sent[1][1]["party_size"] == 4


def test_table_taken_by_another_client_shows_error_refreshes_and_keeps_form(page, api):
    sign_in(page)
    page.goto("/")
    search(page, future_date(), party_size=2)
    page.get_by_test_id("slot-t_2-19:00").click()
    page.get_by_test_id("booking-party-size").fill("3")
    api.book(api.login("bob@example.com")["token"], "t_2", "19:00", key="bob-race")
    with page.expect_response(lambda r: "/availability" in r.url):
        page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("booking-error")).to_be_visible()
    expect(page.get_by_test_id("confirmation")).to_have_count(0)
    expect(page.get_by_test_id("booking-form")).to_be_visible()
    expect(page.get_by_test_id("booking-party-size")).to_have_value("3")
    expect(page.get_by_test_id("booking-summary")).to_contain_text("Table 2")
    expect(page.get_by_test_id("slot-t_2-19:00")).to_have_attribute("data-available", "false")
    # The diner changes their choice and books another table with the kept inputs.
    page.get_by_test_id("slot-t_garden-19:00").click()
    expect(page.get_by_test_id("booking-party-size")).to_have_value("3")
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("confirmation-tables")).to_contain_text("Garden")
    expect(page.get_by_test_id("booking-error")).to_have_count(0)


def test_lost_response_after_commit_is_uncertain_then_retry_recovers_original(page, api):
    sign_in(page)
    sent = watch_bookings(page)
    page.goto("/")
    search(page, future_date(), party_size=2)
    page.get_by_test_id("slot-t_1-19:00").click()
    committed = {}

    def lose_response(route):
        response = route.fetch()  # the booking really commits on the server
        committed.update(response.json())
        route.abort()             # ...but the browser never hears back

    page.route("**/reservations", lose_response)
    page.get_by_test_id("booking-submit").click()
    uncertain = page.get_by_test_id("booking-uncertain")
    expect(uncertain).to_be_visible()
    assert uncertain.text_content().strip()
    expect(page.get_by_test_id("booking-error")).to_have_count(0)
    expect(page.get_by_test_id("confirmation")).to_have_count(0)
    assert committed["reference"]

    page.unroute("**/reservations")
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("confirmation-reference")).to_have_text(committed["reference"])
    expect(page.get_by_test_id("booking-uncertain")).to_have_count(0)
    expect(page.get_by_test_id("booking-error")).to_have_count(0)
    assert len(sent) == 2 and sent[0] == sent[1]
    assert len(api.reservations(api.login()["token"])) == 1


def test_server_error_is_uncertain_not_a_refusal(page):
    sign_in(page)
    page.goto("/")
    search(page, future_date(), party_size=2)
    page.get_by_test_id("slot-t_1-19:00").click()
    page.route("**/reservations", lambda route: route.fulfill(
        status=503, content_type="application/json",
        body='{"error":{"code":"unavailable","message":"busy"}}'))
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("booking-uncertain")).to_be_visible()
    expect(page.get_by_test_id("booking-error")).to_have_count(0)
    page.unroute("**/reservations")
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("confirmation-reference")).to_have_text(REFERENCE)
    expect(page.get_by_test_id("booking-uncertain")).to_have_count(0)


def test_late_answer_from_an_earlier_search_never_replaces_the_newer_one(page):
    sign_in(page)
    page.goto("/")
    held = []

    def hold_first(route):
        if not held:
            held.append(route)  # answered later, after the newer search has rendered
        else:
            route.continue_()

    page.route(lambda url: "/availability?" in url, hold_first)
    search(page, future_date(), party_size=2, restaurant="r_anker")     # search A
    page.wait_for_timeout(100)
    search(page, open_hafen_date(), party_size=2, restaurant="r_hafen")  # search B
    grid = page.get_by_test_id("availability-grid")
    expect(grid).to_contain_text("Window")
    assert len(held) == 1
    with page.expect_response(lambda r: "restaurant_id=r_anker" in r.url):
        held[0].continue_()
    page.wait_for_timeout(300)
    expect(grid).to_contain_text("Window")
    expect(page.get_by_test_id("slot-h_window-19:00")).to_be_visible()
    expect(page.get_by_test_id("slot-t_1-19:00")).to_have_count(0)
    expect(page.get_by_role("heading", name="Hafenblick")).to_be_visible()
    page.get_by_test_id("slot-h_window-19:00").click()
    expect(page.get_by_test_id("booking-summary")).to_contain_text("Window")
    expect(page.get_by_test_id("booking-summary")).to_contain_text("Hafenblick")


def test_a_new_search_closes_the_previous_booking_form(page):
    sign_in(page)
    page.goto("/")
    search(page, future_date(), party_size=2)
    page.get_by_test_id("slot-t_1-19:00").click()
    expect(page.get_by_test_id("booking-form")).to_be_visible()
    search(page, future_date(), party_size=4, restaurant="r_anker")
    expect(page.get_by_test_id("availability-grid")).to_be_visible()
    expect(page.get_by_test_id("booking-form")).to_have_count(0)


def test_book_a_combined_pair(page, api):
    sign_in(page)
    page.goto("/")
    search(page, future_date(), party_size=6)
    pair = page.get_by_test_id("slot-t_1+t_2-19:00")
    expect(pair).to_have_attribute("data-available", "true")
    pair.click()
    summary = page.get_by_test_id("booking-summary")
    expect(summary).to_contain_text("Tables 1 + 2")
    expect(summary).to_contain_text("seats 6")
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("confirmation-reference")).to_have_text(REFERENCE)
    tables = page.get_by_test_id("confirmation-tables")
    expect(tables).to_contain_text("1")
    expect(tables).to_contain_text("2")
    booked = api.reservations(api.login()["token"])
    assert len(booked) == 1 and booked[0]["table_ids"] == ["t_1", "t_2"]
    # Both member tables, and the overlapping pair, are now taken.
    expect(page.get_by_test_id("slot-t_2+t_3-19:00")).to_have_count(0)


def test_keyboard_can_choose_a_table(page):
    sign_in(page)
    page.goto("/")
    search(page, future_date(), party_size=2)
    cell = page.get_by_test_id("slot-t_3-20:00")
    cell.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("booking-summary")).to_contain_text("Table 3")
    expect(page.get_by_test_id("slot-t_3-20:00")).to_have_attribute("aria-pressed", "true")
