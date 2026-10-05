"""Routing, status mapping, content type and connection framing (spec 3, 5; R10)."""
import http.client
import json

import pytest

from httpkit import JSON_TYPE, assert_error, make_fixture, read_response


def test_health_is_ok_json(client):
    resp = client.request("GET", "/health")
    assert resp.status == 200
    assert resp.headers["content-type"] == JSON_TYPE
    assert resp.json() == {"status": "ok"}


def test_reset_returns_204_without_body(client):
    resp = client.request("POST", "/_test/reset", make_fixture())
    assert resp.status == 204
    assert resp.raw == b""


@pytest.mark.parametrize("path", [
    "/", "/nope", "/health/", "/restaurants/", "/reservations/", "/reservations//cancel",
    "/reservations/ABC/cancel/extra", "/auth", "/_test", "/RESTAURANTS",
])
def test_unknown_path_is_404_envelope(client, path):
    assert_error(client.request("GET", path), 404, "not_found")


@pytest.mark.parametrize("method,path,allowed", [
    ("DELETE", "/health", "GET"),
    ("POST", "/health", "GET"),
    ("GET", "/_test/reset", "POST"),
    ("PUT", "/reservations", "GET"),
    ("GET", "/reservation-moves", "POST"),
    ("POST", "/restaurants", "GET"),
    ("DELETE", "/reservations/ABC123", "PATCH"),
    ("GET", "/reservations/ABC123/cancel", "POST"),
    ("GET", "/auth/login", "POST"),
])
def test_known_path_wrong_method_is_405(client, method, path, allowed):
    resp = client.request(method, path)
    assert_error(resp, 405, "method_not_allowed")
    assert allowed in resp.headers.get("allow", "")


def test_unknown_method_is_405_not_501(client):
    assert_error(client.request("FROB", "/health"), 405, "method_not_allowed")


def test_405_precedes_authentication(client):
    # No bearer token, but the method is wrong: the route decides first.
    assert_error(client.request("DELETE", "/reservations/ABC123"), 405, "method_not_allowed")


def test_unknown_path_precedes_authentication(client):
    assert_error(client.request("GET", "/reservations/ABC/history"), 404, "not_found")


def test_trailing_query_string_is_ignored(client, ada):
    assert client.request("GET", "/health?probe=1").status == 200
    assert client.request("GET", "/restaurants?page=2").status == 200
    assert client.request("GET", "/reservations?sort=asc", token=ada).status == 200


def test_public_restaurant_endpoints_need_no_token(client):
    resp = client.request("GET", "/restaurants")
    assert resp.status == 200 and resp.headers["content-type"] == JSON_TYPE
    assert [r["id"] for r in resp.json()["restaurants"]] == ["r_anker"]
    assert client.request("GET", "/restaurants/r_anker").status == 200
    assert_error(client.request("GET", "/restaurants/r_missing"), 404, "not_found")


def test_percent_encoded_path_segment_is_decoded(client):
    # "r_anker" spelled with an escaped underscore still names the same restaurant.
    resp = client.request("GET", "/restaurants/r%5Fanker")
    assert resp.status == 200 and resp.json()["id"] == "r_anker"


def test_keep_alive_connection_survives_errors_with_bodies(server):
    """An early error must still consume the request body, keeping the stream framed."""
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    try:
        body = json.dumps({"filler": "x" * 5000}).encode()
        conn.request("POST", "/no-such-route", body=body,
                     headers={"Content-Type": "application/json"})
        assert_error(read_response(conn), 404, "not_found")
        conn.request("POST", "/reservations", body=body,
                     headers={"Content-Type": "application/json"})
        assert_error(read_response(conn), 401, "unauthenticated")
        conn.request("GET", "/health")
        resp = read_response(conn)
        assert resp.status == 200 and resp.json() == {"status": "ok"}
    finally:
        conn.close()


def test_invalid_content_length_is_400_envelope(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    try:
        conn.putrequest("POST", "/auth/login")
        conn.putheader("Content-Length", "not-a-number")
        conn.endheaders()
        assert_error(read_response(conn), 400, "malformed_request")
    finally:
        conn.close()
