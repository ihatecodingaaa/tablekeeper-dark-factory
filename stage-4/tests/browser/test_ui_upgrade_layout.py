"""Export/import mid-session, stage-1 replay bodies (S2-R9) and small-screen layout (stage 2)."""
import pytest
from playwright.sync_api import expect

from uikit import future_date, make_fixture, search, sign_in


def no_horizontal_page_scroll(page):
    """The page is not scrolled sideways and has nothing to scroll sideways to."""
    m = page.evaluate("""() => ({x: window.scrollX, left: document.scrollingElement.scrollLeft,
        width: document.documentElement.scrollWidth, client: document.documentElement.clientWidth})""")
    assert m["x"] == 0 and m["left"] == 0 and m["width"] <= m["client"], m
    return True


def assert_in_grid_view(page, testid):
    """A cell inside the sideways-scrolling grid is within the grid's visible area."""
    inside = page.evaluate("""(testid) => {
        const cell = document.querySelector(`[data-testid="${testid}"]`).getBoundingClientRect();
        const box = document.querySelector('[data-testid="availability-grid"]').getBoundingClientRect();
        return cell.left >= box.left - 1 && cell.right <= box.right + 1;
    }""", testid)
    assert inside, f"{testid} is scrolled out of the grid's view"


def test_upgrade_keeps_the_user_signed_in_and_recovers_a_lost_booking(page, api):
    sign_in(page)
    page.goto("/")
    search(page, future_date(), party_size=2)
    page.get_by_test_id("slot-t_3-19:30").click()
    committed = {}

    def lose_response(route):
        committed.update(route.fetch().json())
        route.abort()

    page.route("**/reservations", lose_response)
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("booking-uncertain")).to_be_visible()
    page.unroute("**/reservations")

    # Server-side upgrade between two browser requests: export, wipe, import.
    status, document = api.call("GET", "/_test/export")
    assert status == 200
    api.reset(make_fixture())
    status, _ = api.call("POST", "/_test/import", document)
    assert status == 204

    expect(page.get_by_test_id("current-user")).to_contain_text("Ada")
    page.get_by_test_id("booking-submit").click()  # same form, same key, no reload
    expect(page.get_by_test_id("confirmation-reference")).to_have_text(committed["reference"])
    expect(page.get_by_test_id("booking-uncertain")).to_have_count(0)

    page.goto("/lookup")
    expect(page.get_by_test_id("current-user")).to_contain_text("Ada")
    page.get_by_test_id("lookup-reference-input").fill(committed["reference"])
    page.get_by_test_id("lookup-submit").click()
    expect(page.get_by_test_id("reservation-status")).to_have_text("confirmed")


def test_confirmation_renders_from_a_stage1_shaped_replay(page):
    """S2-R9: a replayed stage-1 body has table_id but no table_ids."""
    sign_in(page)
    page.goto("/")
    date = future_date()
    search(page, date, party_size=2)
    page.get_by_test_id("slot-t_2-19:00").click()
    stage1_body = ('{"reservation_id":"res_old","reference":"OLDREF01","restaurant_id":"r_anker",'
                   '"table_id":"t_2","party_size":2,"status":"confirmed",'
                   f'"starts_at_local":"{date}T19:00","starts_at":"{date}T19:00:00+02:00",'
                   f'"ends_at":"{date}T20:30:00+02:00","created_at":"2026-09-01T10:00:00+00:00"}}')
    page.route("**/reservations", lambda route: route.fulfill(
        status=200, content_type="application/json; charset=utf-8", body=stage1_body))
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("confirmation-reference")).to_have_text("OLDREF01")
    expect(page.get_by_test_id("confirmation-tables")).to_contain_text("2")
    details = page.get_by_test_id("confirmation-details")
    expect(details).to_contain_text("Zum Anker")
    expect(details).to_contain_text("19:00")


@pytest.mark.parametrize("width", [375, 1280])
@pytest.mark.parametrize("path", ["/", "/signup", "/login", "/lookup"])
def test_screens_fit_the_viewport(page, width, path):
    page.set_viewport_size({"width": width, "height": 812})
    page.goto(path)
    assert no_horizontal_page_scroll(page)


@pytest.mark.parametrize("width", [375, 1280])
def test_booking_flow_fits_the_viewport(page, api, width):
    sign_in(page)
    page.set_viewport_size({"width": width, "height": 812})
    page.goto("/")
    search(page, future_date(), party_size=5)
    expect(page.get_by_test_id("availability-grid")).to_be_visible()
    assert no_horizontal_page_scroll(page)
    page.get_by_test_id("slot-t_1+t_2-19:00").click()
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("confirmation")).to_be_visible()
    assert no_horizontal_page_scroll(page)
    reference = page.get_by_test_id("confirmation-reference").text_content()
    page.goto("/lookup")
    page.get_by_test_id("lookup-reference-input").fill(reference)
    page.get_by_test_id("lookup-submit").click()
    expect(page.get_by_test_id("reservation-detail")).to_be_visible()
    assert no_horizontal_page_scroll(page)


def test_every_booking_state_keeps_the_page_still_at_375(page, api):
    """Rows without a free joined table, a far-right selection and every outcome state."""
    bob = api.login("bob@example.com")["token"]
    api.book(bob, "t_2", "19:00", key="bob-a")          # rows with no free pair
    api.book(bob, "t_garden", "18:00", party_size=4, key="bob-b")
    strict = api.book(api.login()["token"], "s_1", "19:00", restaurant="r_strict", key="ada-strict")
    sign_in(page)
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto("/")
    search(page, future_date(), party_size=2)
    expect(page.get_by_test_id("availability-grid")).to_be_visible()
    assert no_horizontal_page_scroll(page)

    page.get_by_test_id("slot-t_garden-20:00").click()           # the rightmost single table
    expect(page.get_by_test_id("booking-form")).to_be_visible()
    assert no_horizontal_page_scroll(page)
    assert_in_grid_view(page, "slot-t_garden-20:00")

    page.route("**/reservations", lambda route: route.abort())
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("booking-uncertain")).to_be_visible()
    assert no_horizontal_page_scroll(page)
    page.unroute("**/reservations")

    api.book(bob, "t_garden", "20:00", key="bob-c")
    with page.expect_response(lambda r: "/availability" in r.url):
        page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("booking-error")).to_be_visible()
    assert no_horizontal_page_scroll(page)
    # The refreshed grid kept its sideways scroll: the far-right column is still in view.
    expect(page.get_by_test_id("slot-t_garden-20:00")).to_have_attribute("data-available", "false")
    assert_in_grid_view(page, "slot-t_garden-20:00")

    page.get_by_test_id("slot-t_3-20:30").click()
    page.get_by_test_id("booking-submit").click()
    expect(page.get_by_test_id("confirmation")).to_be_visible()
    page.wait_for_timeout(400)  # let the confirmation finish scrolling into view
    assert no_horizontal_page_scroll(page)
    reference = page.get_by_test_id("confirmation-reference").text_content()

    for ref in (reference, "NOPE0000", strict["reference"]):
        page.goto("/lookup")
        page.get_by_test_id("lookup-reference-input").fill(ref)
        page.get_by_test_id("lookup-submit").click()
        if ref == "NOPE0000":
            expect(page.get_by_test_id("reservation-error")).to_be_visible()
            assert no_horizontal_page_scroll(page)
            continue
        expect(page.get_by_test_id("reservation-detail")).to_be_visible()
        assert no_horizontal_page_scroll(page)
        page.get_by_test_id("reservation-cancel-button").click()
        if ref == reference:
            expect(page.get_by_test_id("reservation-status")).to_have_text("cancelled")
        else:
            expect(page.get_by_test_id("reservation-error")).to_be_visible()
        assert no_horizontal_page_scroll(page)


@pytest.mark.parametrize("testid", ["slot-t_3-20:00", "slot-t_2-18:00", "slot-t_garden-20:30",
                                    "slot-t_1+t_2-19:00"])
def test_a_selected_cell_is_fully_in_view_at_375(page, testid):
    sign_in(page)
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto("/")
    search(page, future_date(), party_size=2)
    page.get_by_test_id(testid).click()
    expect(page.get_by_test_id(testid)).to_have_attribute("aria-pressed", "true")
    assert_in_grid_view(page, testid)
    assert no_horizontal_page_scroll(page)


def test_reduced_motion_is_respected(browser, base_url, api):
    context = browser.new_context(base_url=base_url, reduced_motion="reduce")
    try:
        pg = context.new_page()
        pg.goto("/")
        duration = pg.evaluate("""() => {
            const probe = document.createElement('span');
            probe.className = 'spinner';
            document.body.appendChild(probe);
            return getComputedStyle(probe).animationName;
        }""")
        assert duration == "none"
    finally:
        context.close()
