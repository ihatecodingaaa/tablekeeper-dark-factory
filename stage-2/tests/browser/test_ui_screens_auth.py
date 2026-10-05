"""Screens reachable by URL, signup, login, sign-out and the signed-in header (stage 2: routes, auth)."""
import pytest
from playwright.sync_api import expect

from uikit import PASSWORD, sign_in


@pytest.mark.parametrize("path,testids", [
    ("/", ["restaurant-select", "date-input", "party-size-input", "search-button"]),
    ("/signup", ["signup-email", "signup-password", "signup-display-name", "signup-submit"]),
    ("/login", ["login-email", "login-password", "login-submit"]),
    ("/lookup", ["lookup-reference-input", "lookup-submit"]),
])
def test_each_screen_is_html_with_its_controls(page, path, testids):
    response = page.goto(path)
    assert response.status == 200
    assert response.headers["content-type"].startswith("text/html")
    for testid in testids:
        expect(page.get_by_test_id(testid)).to_be_visible()
    # Consistent navigation on every screen.
    expect(page.get_by_role("link", name="Tablekeeper home")).to_be_visible()
    expect(page.get_by_role("navigation", name="Main").get_by_role("link", name="Look up")).to_be_visible()
    expect(page.get_by_test_id("auth-error")).to_have_count(0)
    expect(page.get_by_test_id("current-user")).to_have_count(0)


def test_restaurant_options_use_ids_as_values(page):
    page.goto("/")
    values = page.get_by_test_id("restaurant-select").locator("option").evaluate_all(
        "options => options.map(o => [o.value, o.textContent])")
    assert values == [["r_anker", "Zum Anker"], ["r_hafen", "Hafenblick"],
                      ["r_strict", "Strenge Stube"]]


def test_inputs_have_visible_labels(page):
    page.goto("/signup")
    for label, testid in (("Email", "signup-email"), ("Password", "signup-password"),
                          ("Your name", "signup-display-name")):
        expect(page.get_by_label(label, exact=True)).to_have_attribute("data-testid", testid)
    page.goto("/")
    for label, testid in (("Restaurant", "restaurant-select"), ("Date", "date-input"),
                          ("Guests", "party-size-input")):
        expect(page.get_by_label(label, exact=True)).to_have_attribute("data-testid", testid)


def test_signup_signs_in_and_shows_current_user_everywhere(page, api):
    page.goto("/signup")
    page.get_by_test_id("signup-display-name").fill("Cyrille")
    page.get_by_test_id("signup-email").fill("cyrille@example.com")
    page.get_by_test_id("signup-password").fill(PASSWORD)
    page.get_by_test_id("signup-submit").click()
    expect(page.get_by_test_id("current-user")).to_contain_text("Cyrille")
    for path in ("/", "/lookup", "/login", "/signup"):
        page.goto(path)
        expect(page.get_by_test_id("current-user")).to_contain_text("Cyrille")
        expect(page.get_by_test_id("logout-button")).to_be_visible()
    status, body = api.call("POST", "/auth/login", {"email": "cyrille@example.com", "password": PASSWORD})
    assert status == 200 and body["display_name"] == "Cyrille"


def test_signup_with_taken_email_shows_auth_error(page):
    page.goto("/signup")
    page.get_by_test_id("signup-display-name").fill("Ada Again")
    page.get_by_test_id("signup-email").fill("ada@example.com")
    page.get_by_test_id("signup-password").fill(PASSWORD)
    page.get_by_test_id("signup-submit").click()
    expect(page.get_by_test_id("auth-error")).to_be_visible()
    expect(page.get_by_test_id("current-user")).to_have_count(0)


def test_signup_with_short_password_shows_auth_error(page):
    page.goto("/signup")
    page.get_by_test_id("signup-display-name").fill("Dee")
    page.get_by_test_id("signup-email").fill("dee@example.com")
    page.get_by_test_id("signup-password").fill("short")
    page.get_by_test_id("signup-submit").click()
    expect(page.get_by_test_id("auth-error")).to_be_visible()


def test_wrong_password_shows_auth_error_then_login_succeeds(page):
    page.goto("/login")
    page.get_by_test_id("login-email").fill("ada@example.com")
    page.get_by_test_id("login-password").fill("not the password")
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("auth-error")).to_be_visible()
    expect(page.get_by_test_id("current-user")).to_have_count(0)
    page.get_by_test_id("login-password").fill(PASSWORD)
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("current-user")).to_contain_text("Ada")
    expect(page.get_by_test_id("auth-error")).to_have_count(0)


def test_logout_removes_current_user(page):
    sign_in(page)
    page.get_by_test_id("logout-button").click()
    expect(page.get_by_test_id("current-user")).to_have_count(0)
    expect(page.get_by_test_id("logout-button")).to_have_count(0)
    page.goto("/lookup")
    expect(page.get_by_test_id("current-user")).to_have_count(0)


def test_static_assets_are_served_from_the_image(page, base_url):
    for path, kind in (("/assets/app.css", "text/css"), ("/assets/app.js", "text/javascript"),
                       ("/assets/icon.svg", "image/svg+xml")):
        response = page.request.get(base_url + path)
        assert response.status == 200
        assert response.headers["content-type"].startswith(kind)
    external = []
    page.on("request", lambda req: external.append(req.url)
            if not req.url.startswith(base_url) else None)
    page.goto("/")
    page.wait_for_load_state("networkidle")
    assert external == []
