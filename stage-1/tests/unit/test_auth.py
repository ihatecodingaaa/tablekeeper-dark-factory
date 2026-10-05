"""Spec §6 and ruling R6: signup, login, bearer tokens, password storage."""
import json

import pytest

from tk_unit import ADA, api_error, assert_error


def signup(svc, email="new@example.com", password="long enough", display_name="Neo"):
    return svc.signup({"email": email, "password": password, "display_name": display_name})


def test_signup_returns_user_token_and_display_name(world):
    out = signup(world.svc)
    assert set(out) == {"user_id", "display_name", "token"}
    assert out["display_name"] == "Neo"
    assert isinstance(out["user_id"], str) and 0 < len(out["user_id"]) <= 64
    assert world.svc.authenticate("Bearer " + out["token"]) == out["user_id"]


def test_login_after_signup_returns_same_user_and_a_new_token(world):
    first = signup(world.svc)
    out = world.svc.login({"email": "new@example.com", "password": "long enough"})
    assert set(out) == {"user_id", "display_name", "token"}
    assert out["user_id"] == first["user_id"] and out["display_name"] == "Neo"
    assert out["token"] != first["token"]
    # Tokens do not expire and several sessions are valid at once.
    assert world.svc.authenticate("Bearer " + first["token"]) == first["user_id"]
    assert world.svc.authenticate("Bearer " + out["token"]) == first["user_id"]


def test_seeded_user_logs_in_immediately(world):
    out = world.svc.login({"email": ADA["email"], "password": ADA["password"]})
    assert out["user_id"] == "u_ada" and out["display_name"] == "Ada"


def test_email_is_unique_case_insensitively(world):
    assert_error(api_error(signup, world.svc, email="ADA@example.com"), 409, "email_taken")
    signup(world.svc, email="Mixed@Example.com")
    assert_error(api_error(signup, world.svc, email="mixed@example.com"), 409, "email_taken")


def test_login_email_is_case_insensitive(world):
    out = world.svc.login({"email": "Ada@Example.COM", "password": ADA["password"]})
    assert out["user_id"] == "u_ada"


@pytest.mark.parametrize("password", ["", "short", "1234567"])
def test_signup_password_shorter_than_8_is_422(world, password):
    assert_error(api_error(signup, world.svc, password=password), 422, "validation_failed")


def test_signup_password_of_exactly_8_is_accepted(world):
    assert signup(world.svc, password="12345678")["token"]


@pytest.mark.parametrize("email", ["plain", "@example.com", "ada@", "a@b@c", "a b@example.com",
                                   "ada@exa mple.com", " ada@example.com", ""])
def test_signup_email_must_be_local_at_domain(world, email):
    assert_error(api_error(signup, world.svc, email=email), 422, "validation_failed")


def test_signup_display_name_required_non_empty(world):
    assert_error(api_error(signup, world.svc, display_name=""), 422, "validation_failed")
    err = api_error(world.svc.signup, {"email": "x@example.com", "password": "long enough"})
    assert_error(err, 422, "validation_failed")


@pytest.mark.parametrize("field,value", [("email", 5), ("password", ["x"]), ("display_name", 7),
                                         ("email", None), ("password", True)])
def test_signup_wrong_json_types_are_400(world, field, value):
    data = {"email": "x@example.com", "password": "long enough", "display_name": "X"}
    data[field] = value
    assert_error(api_error(world.svc.signup, data), 400, "malformed_request")


@pytest.mark.parametrize("missing", ["email", "password"])
def test_signup_missing_fields_are_422(world, missing):
    data = {"email": "x@example.com", "password": "long enough", "display_name": "X"}
    del data[missing]
    assert_error(api_error(world.svc.signup, data), 422, "validation_failed")


def test_signup_ignores_unknown_fields(world):
    out = world.svc.signup({"email": "x@example.com", "password": "long enough",
                            "display_name": "X", "role": "admin"})
    assert out["display_name"] == "X"


@pytest.mark.parametrize("email,password", [(ADA["email"], "wrong password"), (ADA["email"], "x"),
                                            ("ghost@example.com", "correct horse")])
def test_login_wrong_password_or_unknown_email_is_401(world, email, password):
    assert_error(api_error(world.svc.login, {"email": email, "password": password}),
                 401, "unauthenticated")


def test_login_wrong_types_400_missing_422(world):
    assert_error(api_error(world.svc.login, {"email": 1, "password": "x"}), 400, "malformed_request")
    assert_error(api_error(world.svc.login, {"email": ADA["email"]}), 422, "validation_failed")


@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer ", "Basic abc", "Token abc",
                                    "Bearer unknown-token", "Bearertoken"])
def test_authenticate_rejects_missing_malformed_unknown(world, header):
    assert_error(api_error(world.svc.authenticate, header), 401, "unauthenticated")


def test_authenticate_scheme_is_case_insensitive(world):
    token = world.svc.login({"email": ADA["email"], "password": ADA["password"]})["token"]
    for scheme in ("Bearer", "bearer", "BEARER"):
        assert world.svc.authenticate(f"{scheme} {token}") == "u_ada"
    assert_error(api_error(world.svc.authenticate, f"Bearer {token} extra"), 401, "unauthenticated")


def test_passwords_and_tokens_not_stored_in_plaintext(world):
    out = signup(world.svc, password="very secret pw")
    dumped = json.dumps(world.svc.export_state())
    assert "very secret pw" not in dumped
    assert "correct horse" not in dumped
    assert out["token"] not in dumped
    assert "scrypt$" in dumped


def test_reset_invalidates_tokens(world):
    token = world.svc.login({"email": ADA["email"], "password": ADA["password"]})["token"]
    from tk_unit import fixture
    world.svc.reset(fixture())
    assert_error(api_error(world.svc.authenticate, "Bearer " + token), 401, "unauthenticated")
