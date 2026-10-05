"""HTTP boundary: routing, bearer auth, JSON bodies and the error envelope.

All domain behaviour lives in Service. This module maps HTTP onto it in a fixed
order: route match (404, 405), authentication for protected routes (401), body
parsing (400), then the service call. Every 4xx/5xx carries the envelope
{"error": {"code": ..., "message": ...}}; 204 responses carry no body.

The browser screens (/, /signup, /login, /lookup, and the extras /evening/{ref},
/passport, /notifications, /control-room, /simulator) are HTML pages composed from
tablekeeper/web/; their scripts and styles are served from /assets/. Any /x/... path
that no official route claims is handed to the extras dispatcher.
"""
from __future__ import annotations

import html
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .errors import ApiError, malformed, not_found
from .extras import routes as extras_routes
from .service import Service

JSON_TYPE = "application/json; charset=utf-8"
HTML_TYPE = "text/html; charset=utf-8"
WEB_DIR = Path(__file__).resolve().parent / "web"
ASSET_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webmanifest": "application/manifest+json",
}
NON_JSON_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
}


class Raw:
    """A response body that is not JSON: an HTML page or a static asset."""

    __slots__ = ("content_type", "data")

    def __init__(self, content_type: str, data: bytes):
        self.content_type = content_type
        self.data = data


def _load_assets() -> dict:
    assets = {}
    for path in sorted((WEB_DIR / "assets").iterdir()):
        content_type = ASSET_TYPES.get(path.suffix)
        if content_type and path.is_file():
            assets[path.name] = Raw(content_type, path.read_bytes())
    return assets


ASSETS = _load_assets()
LAYOUT = (WEB_DIR / "layout.html").read_text(encoding="utf-8")
TITLES = {"search": "Find a table", "signup": "Create an account", "login": "Sign in",
          "lookup": "Look up a reservation", "evening": "My evening", "passport": "My evenings",
          "notifications": "Messages", "control-room": "Control room", "simulator": "Recovery simulator"}
SCREENS = {name: (WEB_DIR / "screens" / f"{name}.html").read_text(encoding="utf-8") for name in TITLES}
_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def render_page(screen: str, values: dict | None = None) -> Raw:
    """Fill the layout with one screen. `values` must already be escaped HTML."""
    fills = dict(values or {})
    content = _PLACEHOLDER.sub(lambda m: fills.get(m.group(1), ""), SCREENS[screen])
    layout = {"TITLE": html.escape(TITLES[screen]), "SCREEN": screen, "CONTENT": content}
    page = _PLACEHOLDER.sub(lambda m: layout.get(m.group(1), ""), LAYOUT)
    return Raw(HTML_TYPE, page.encode("utf-8"))


def _search_page(svc, rq):
    # Restaurant options are rendered on the server, so the selector is usable
    # before any script runs and the page itself makes no API call on load.
    restaurants = svc.list_restaurants().get("restaurants", [])
    options = "".join(
        f'<option value="{html.escape(r["id"])}">{html.escape(r["name"])}</option>'
        for r in restaurants)
    return 200, render_page("search", {"RESTAURANT_OPTIONS": options})


def _asset(svc, rq):
    asset = ASSETS.get(rq.params[0])
    if asset is None:
        raise not_found("no such asset")
    return 200, asset


def _screen(name):
    """A route handler that serves one static screen; its script loads the data."""
    return lambda svc, rq: (200, render_page(name))

# Body handling per endpoint.
NO_BODY = None   # any request body is ignored
ANY_JSON = "any"   # any JSON value; the service validates its shape
OBJECT = "object"  # must be a JSON object, otherwise 400

# Authentication per endpoint: True requires a bearer token (401 otherwise),
# False is public, OPTIONAL_AUTH passes the caller's user id or None to the
# service, which answers 404 for anyone but the owner (never 401).
OPTIONAL_AUTH = "optional"


class Request:
    """What an endpoint needs from one HTTP request."""

    __slots__ = ("params", "query", "body", "user_id", "idempotency_key")

    def __init__(self, params, query, idempotency_key):
        self.params = params
        self.query = query
        self.idempotency_key = idempotency_key
        self.body = None
        self.user_id = None


def _health(svc, rq):
    if not svc.health():
        raise ApiError(503, "service_unavailable", "service is not ready")
    return 200, {"status": "ok"}


def _reset(svc, rq):
    svc.reset(rq.body)
    return 204, None


def _import(svc, rq):
    svc.import_state(rq.body)
    return 204, None


# Path templates: a literal segment matches itself, None matches one non-empty
# segment (passed to the endpoint, percent-decoded). Each method maps to
# (endpoint, authentication, body handling).
ROUTES = [
    (("",), {"GET": (_search_page, False, NO_BODY)}),
    (("signup",), {"GET": (lambda s, r: (200, render_page("signup")), False, NO_BODY)}),
    (("login",), {"GET": (lambda s, r: (200, render_page("login")), False, NO_BODY)}),
    (("lookup",), {"GET": (lambda s, r: (200, render_page("lookup")), False, NO_BODY)}),
    (("evening", None), {"GET": (_screen("evening"), False, NO_BODY)}),
    (("passport",), {"GET": (_screen("passport"), False, NO_BODY)}),
    (("notifications",), {"GET": (_screen("notifications"), False, NO_BODY)}),
    (("control-room",), {"GET": (_screen("control-room"), False, NO_BODY)}),
    (("simulator",), {"GET": (_screen("simulator"), False, NO_BODY)}),
    (("assets", None), {"GET": (_asset, False, NO_BODY)}),
    (("health",), {"GET": (_health, False, NO_BODY)}),
    (("_test", "reset"), {"POST": (_reset, False, ANY_JSON)}),
    (("_test", "export"), {"GET": (lambda s, r: (200, s.export_state()), False, NO_BODY)}),
    (("_test", "import"), {"POST": (_import, False, ANY_JSON)}),
    (("auth", "signup"), {"POST": (lambda s, r: (201, s.signup(r.body)), False, OBJECT)}),
    (("auth", "login"), {"POST": (lambda s, r: (200, s.login(r.body)), False, OBJECT)}),
    (("restaurants",), {"GET": (lambda s, r: (200, s.list_restaurants()), False, NO_BODY)}),
    (("restaurants", None), {
        "GET": (lambda s, r: (200, s.get_restaurant(r.params[0])), False, NO_BODY)}),
    (("restaurants", None, "policies"), {
        "GET": (lambda s, r: (200, s.list_policies(r.params[0])), False, NO_BODY),
        "POST": (lambda s, r: s.publish_policy(r.user_id, r.params[0], r.idempotency_key, r.body),
                 True, OBJECT),
    }),
    (("restaurants", None, "replans"), {
        "POST": (lambda s, r: s.replan_preview(r.user_id, r.params[0], r.idempotency_key, r.body),
                 True, OBJECT)}),
    (("restaurants", None, "replans", None, "apply"), {
        "POST": (lambda s, r: s.replan_apply(r.user_id, r.params[0], r.params[1], r.idempotency_key,
                                             r.body), True, OBJECT)}),
    (("availability",), {"GET": (lambda s, r: (200, s.availability(r.query)), False, NO_BODY)}),
    (("reservations",), {
        "GET": (lambda s, r: (200, s.list_reservations(r.user_id)), True, NO_BODY),
        "POST": (lambda s, r: s.create_reservation(r.user_id, r.idempotency_key, r.body),
                 True, OBJECT),
    }),
    (("reservations", None), {
        "GET": (lambda s, r: (200, s.get_reservation(r.user_id, r.params[0])), True, NO_BODY),
        "PATCH": (lambda s, r: (200, s.amend_reservation(r.user_id, r.params[0], r.body)),
                  True, OBJECT),
    }),
    (("reservations", None, "cancel"), {
        "POST": (lambda s, r: (200, s.cancel_reservation(r.user_id, r.params[0])),
                 True, NO_BODY)}),
    (("reservations", None, "history"), {
        "GET": (lambda s, r: (200, s.reservation_history(r.user_id, r.params[0])),
                OPTIONAL_AUTH, NO_BODY)}),
    (("reservations", None, "decision"), {
        "GET": (lambda s, r: (200, s.reservation_decision(r.user_id, r.params[0])),
                OPTIONAL_AUTH, NO_BODY)}),
    (("reservation-moves",), {
        "POST": (lambda s, r: s.move_reservations(r.user_id, r.idempotency_key, r.body),
                 True, OBJECT)}),
    (("series",), {
        "POST": (lambda s, r: s.create_series(r.user_id, r.idempotency_key, r.body),
                 True, OBJECT)}),
    (("series", None), {
        "GET": (lambda s, r: (200, s.get_series(r.user_id, r.params[0])), OPTIONAL_AUTH, NO_BODY)}),
    (("series", None, "amend"), {
        "POST": (lambda s, r: s.amend_series(r.user_id, r.params[0], r.idempotency_key, r.body),
                 True, OBJECT)}),
]


def match_route(path: str):
    """Return (methods, params) for a request path, or None when no route matches."""
    if not path.startswith("/"):
        return None
    segments = path[1:].split("/")
    for template, methods in ROUTES:
        if len(template) != len(segments):
            continue
        params = []
        for literal, segment in zip(template, segments):
            if literal is None:
                if not segment:
                    break
                params.append(unquote(segment))
            elif literal != segment:
                break
        else:
            return methods, params
    return None


def _reject_constant(name):
    raise ValueError(f"{name} is not valid JSON")


def parse_json(raw: bytes):
    """Parse a request body strictly: UTF-8, no NaN/Infinity, empty is an error."""
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise malformed("request body is not valid JSON") from None


def _header_text(value):
    """Header values arrive as latin-1; recover UTF-8 text where the bytes allow."""
    if value is None:
        return None
    try:
        return value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return value


def _envelope(status, code, message):
    return status, {"error": {"code": code, "message": message}}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "tablekeeper"
    timeout = 30  # seconds an idle keep-alive connection may hold a thread

    def __getattr__(self, name):
        # http.server looks up do_<METHOD>; route every method through one
        # dispatcher so unknown methods get 405/404 envelopes instead of 501 HTML.
        if name.startswith("do_"):
            return self._dispatch
        raise AttributeError(name)

    def _dispatch(self):
        self._extra_headers = {}
        try:
            raw = self._read_body()
        except (ValueError, OSError):
            self.close_connection = True
            self._respond(*_envelope(400, "malformed_request", "unreadable request body"))
            return
        try:
            status, body = self._handle(raw)
        except ApiError as exc:
            status, body = exc.status, exc.to_body()
        except Exception as exc:  # never let one request take down the thread
            self._log_failure(exc)
            status, body = _envelope(500, "internal_error", "internal error")
        self._respond(status, body)

    def _handle(self, raw: bytes):
        parts = urlsplit(self.path)
        route = match_route(parts.path)
        if route is None:
            if parts.path.startswith("/x/"):
                return self._extras(parts, raw)
            raise not_found("no such resource")
        methods, params = route
        endpoint = methods.get(self.command)
        if endpoint is None:
            self._extra_headers["Allow"] = ", ".join(methods)
            raise ApiError(405, "method_not_allowed", "method not allowed on this resource")
        handler, needs_auth, body_mode = endpoint
        service = self.server.service
        rq = Request(params, parse_qs(parts.query, keep_blank_values=True),
                     _header_text(self.headers.get("Idempotency-Key")))
        if needs_auth == OPTIONAL_AUTH:
            rq.user_id = service.try_authenticate(self.headers.get("Authorization"))
        elif needs_auth:
            rq.user_id = service.authenticate(self.headers.get("Authorization"))
        if body_mode is not NO_BODY:
            rq.body = parse_json(raw)
            if body_mode == OBJECT and not isinstance(rq.body, dict):
                raise malformed("request body must be a JSON object")
        return handler(service, rq)

    def _extras(self, parts, raw: bytes):
        """The additive /x API: reached only when no official route matched the path."""
        result = extras_routes.handle(self.server.service, self.command, parts.path,
                                      parse_qs(parts.query, keep_blank_values=True), self.headers, raw)
        if result is None:
            raise not_found("no such resource")
        status, body, content_type = result
        if isinstance(body, (bytes, bytearray)):
            return status, Raw(content_type, bytes(body))  # e.g. the calendar file
        return status, body

    def _read_body(self) -> bytes:
        # Always consume the whole body, even for requests that fail before
        # parsing, so the next request on a keep-alive connection stays framed.
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            return self._read_chunked()
        length = self.headers.get("Content-Length")
        if length is None:
            return b""
        size = int(length)
        if size < 0:
            raise ValueError("negative Content-Length")
        data = self.rfile.read(size)
        if len(data) != size:
            raise ValueError("truncated body")
        return data

    def _read_chunked(self) -> bytes:
        chunks = []
        while True:
            size = int(self.rfile.readline(65537).split(b";", 1)[0].strip(), 16)
            if size == 0:
                while self.rfile.readline(65537) not in (b"\r\n", b"\n", b""):
                    pass  # discard trailers
                return b"".join(chunks)
            chunks.append(self.rfile.read(size))
            self.rfile.readline(65537)  # CRLF after each chunk

    def _respond(self, status, body):
        data = None
        content_type = JSON_TYPE
        if isinstance(body, Raw):
            data, content_type = body.data, body.content_type
            self._extra_headers.update(NON_JSON_HEADERS)
        elif status != 204 and body is not None:
            try:
                data = json.dumps(body, ensure_ascii=False, allow_nan=False,
                                  separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError) as exc:
                self._log_failure(exc)
                status, body = _envelope(500, "internal_error", "internal error")
                data = json.dumps(body).encode("utf-8")
        try:
            self.send_response(status)
            for name, value in self._extra_headers.items():
                self.send_header(name, value)
            if data is not None:
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            if data is not None and self.command != "HEAD":
                self.wfile.write(data)
        except OSError:
            self.close_connection = True  # client went away

    def send_error(self, code, message=None, explain=None):
        # Protocol-level failures raised inside http.server itself (bad request
        # line, oversized headers): answer with the envelope, then close.
        self.close_connection = True
        self._extra_headers = {}
        error_code = "malformed_request" if code < 500 else "internal_error"
        self._respond(*_envelope(code, error_code, message or "bad request"))

    def log_request(self, code="-", size="-"):
        # Method, path and status only: never query values, headers or bodies.
        path = urlsplit(self.path).path if getattr(self, "path", None) else "-"
        self.log_message("%s %s %s", self.command, path, code)

    def _log_failure(self, exc):
        tb = exc.__traceback__
        while tb is not None and tb.tb_next is not None:
            tb = tb.tb_next
        where = f"{tb.tb_frame.f_code.co_filename}:{tb.tb_lineno}" if tb else "?"
        self.log_message("unhandled %s at %s", type(exc).__name__, where)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = True

    def __init__(self, address, service: Service):
        self.service = service
        super().__init__(address, Handler)

    def handle_error(self, request, client_address):
        # Errors that escape a handler (e.g. a reset connection): one line, no
        # traceback, so request data never reaches the log.
        exc = sys.exc_info()[1]
        sys.stderr.write(f"connection error: {type(exc).__name__}\n")


def make_server(host: str, port: int, service: Service | None = None) -> Server:
    return Server((host, port), service if service is not None else Service())


def serve(port: int, host: str = "0.0.0.0") -> None:
    server = make_server(host, port)
    sys.stderr.write(f"tablekeeper listening on {host}:{server.server_address[1]}\n")
    try:
        server.serve_forever()
    finally:
        server.server_close()
