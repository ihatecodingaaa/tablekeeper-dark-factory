"""Export/import mid-session, stage-1 replay bodies (S2-R9) and small-screen layout (stage 2)."""
import pytest
from playwright.sync_api import expect

from uikit import future_date, make_fixture, search, sign_in


def no_horizontal_page_scroll(page):
    return page.evaluate(
        "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth")


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
