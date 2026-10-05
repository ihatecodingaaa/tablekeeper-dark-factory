"""Request bodies: malformed JSON, non-object bodies and wrong field types (spec 5; R1, R2, R6, R9)."""
import pytest

from httpkit import assert_error, booking

MALFORMED = [
    pytest.param(b"{not json", id="garbage"),
    pytest.param(b"", id="empty"),
    pytest.param(b'{"a": NaN}', id="nan"),
    pytest.param(b'{"a": Infinity}', id="infinity"),
    pytest.param(b'{"email": "\xff\xfe"}', id="invalid-utf8"),
    pytest.param(b'{"a": 1', id="truncated"),
]
NOT_AN_OBJECT = [
    pytest.param(b"[1, 2]", id="array"),
    pytest.param(b'"text"', id="string"),
    pytest.param(b"42", id="number"),
    pytest.param(b"null", id="null"),
]


@pytest.mark.parametrize("raw", MALFORMED + NOT_AN_OBJECT)
@pytest.mark.parametrize("path", ["/auth/signup", "/auth/login"])
def test_auth_bodies_must_be_json_objects(client, path, raw):
    assert_error(client.request("POST", path, raw=raw), 400, "malformed_request")


@pytest.mark.parametrize("raw", MALFORMED + NOT_AN_OBJECT)
def test_create_reservation_body_must_be_json_object(client, ada, raw):
    resp = client.request("POST", "/reservations", raw=raw, token=ada, key="k-body")
    assert_error(resp, 400, "malformed_request")


@pytest.mark.parametrize("raw", MALFORMED + NOT_AN_OBJECT)
def test_moves_body_must_be_json_object(client, ada, raw):
    resp = client.request("POST", "/reservation-moves", raw=raw, token=ada, key="k-body")
    assert_error(resp, 400, "malformed_request")


@pytest.mark.parametrize("raw", MALFORMED + NOT_AN_OBJECT)
def test_amend_body_must_be_json_object(client, ada, raw):
    created = client.request("POST", "/reservations", booking(), token=ada, key="k-made")
    assert created.status == 201, created
    ref = created.json()["reference"]
    resp = client.request("PATCH", f"/reservations/{ref}", raw=raw, token=ada)
    assert_error(resp, 400, "malformed_request")


def test_malformed_body_is_400_before_missing_key(client, ada):
    # R1: an unparseable body is reported before the missing Idempotency-Key.
    resp = client.request("POST", "/reservations", raw=b"{oops", token=ada)
    assert_error(resp, 400, "malformed_request")


def test_authentication_precedes_body_parsing(client):
    resp = client.request("POST", "/reservations", raw=b"{oops", key="k-1")
    assert_error(resp, 401, "unauthenticated")
    resp = client.request("PATCH", "/reservations/ABC123", raw=b"[]")
    assert_error(resp, 401, "unauthenticated")


@pytest.mark.parametrize("field,value", [
    ("restaurant_id", 123), ("table_id", ["t_2"]), ("starts_at_local", 1900),
])
def test_wrong_json_type_in_reservation_is_400(client, ada, field, value):
    body = booking()
    body[field] = value
    resp = client.request("POST", "/reservations", body, token=ada, key=f"k-type-{field}")
    assert_error(resp, 400, "malformed_request")


@pytest.mark.parametrize("party_size", ["4", True, 4.5, 0, -1])
def test_invalid_party_size_is_422(client, ada, party_size):
    body = booking()
    body["party_size"] = party_size
    resp = client.request("POST", "/reservations", body, token=ada, key="k-party")
    assert_error(resp, 422, "validation_failed")


def test_wrong_json_type_in_signup_is_400(client):
    resp = client.request("POST", "/auth/signup",
                          {"email": "new@example.com", "password": 12345678,
                           "display_name": "New"})
    assert_error(resp, 400, "malformed_request")


def test_unknown_fields_are_ignored(client, ada):
    body = booking()
    body["note"] = "window seat please"
    resp = client.request("POST", "/reservations", body, token=ada, key="k-extra")
    assert resp.status == 201, resp


def test_cancel_ignores_any_request_body(client, ada):
    created = client.request("POST", "/reservations", booking(), token=ada, key="k-c")
    ref = created.json()["reference"]
    resp = client.request("POST", f"/reservations/{ref}/cancel", raw=b"{not json", token=ada)
    assert resp.status == 200, resp
    assert resp.json()["status"] == "cancelled"


@pytest.mark.parametrize("raw", MALFORMED)
@pytest.mark.parametrize("path", ["/_test/reset", "/_test/import"])
def test_test_control_bodies_reject_invalid_json(client, path, raw):
    assert_error(client.request("POST", path, raw=raw), 400, "malformed_request")


@pytest.mark.parametrize("raw", NOT_AN_OBJECT)
def test_import_of_valid_json_non_object_is_422(client, raw):
    assert_error(client.request("POST", "/_test/import", raw=raw), 422, "validation_failed")
