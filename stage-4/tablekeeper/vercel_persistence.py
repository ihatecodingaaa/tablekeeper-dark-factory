"""Vercel-only durable state adapter for the demo-hosting branch.

The judged application intentionally stores state in memory. Vercel may route
requests to different container instances, so the hosted demo snapshots the
complete Tablekeeper export document into a private Vercel Blob.

Every dynamic request refreshes from origin storage. Successful mutating
requests use an ETag conditional write. If another instance wins the race, the
request is replayed against the newer snapshot before any response is sent.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from urllib import error, parse, request

from .errors import ApiError
from . import http_app


class StateConflict(Exception):
    pass


class StateUnavailable(Exception):
    pass


class BlobStateStore:
    PATH = "tablekeeper/demo-state-v1.json"
    API_VERSION = "12"

    def __init__(self) -> None:
        token = os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()
        if not token:
            raise StateUnavailable("BLOB_READ_WRITE_TOKEN is not configured")
        parts = token.split("_")
        if len(parts) < 5 or parts[:3] != ["vercel", "blob", "rw"]:
            raise StateUnavailable("BLOB_READ_WRITE_TOKEN has an unexpected format")
        self._token = token
        self._store_id = parts[3]

    def _blob_url(self) -> str:
        pathname = parse.quote(self.PATH, safe="/")
        return (
            f"https://{self._store_id}.private.blob.vercel-storage.com/"
            f"{pathname}?cache=0"
        )

    def load(self) -> tuple[dict | None, str | None]:
        req = request.Request(
            self._blob_url(),
            method="GET",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=8) as resp:
                raw = resp.read()
                etag = resp.headers.get("ETag")
        except error.HTTPError as exc:
            if exc.code == 404:
                return None, None
            raise StateUnavailable(f"state read failed with HTTP {exc.code}") from None
        except (error.URLError, TimeoutError, OSError) as exc:
            raise StateUnavailable(f"state read failed: {type(exc).__name__}") from None

        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise StateUnavailable("state blob is not valid JSON") from None
        if not isinstance(document, dict) or not etag:
            raise StateUnavailable("state blob is missing required metadata")
        return document, etag

    def save(self, document: dict, previous_etag: str | None) -> str:
        data = json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        query = parse.urlencode({"pathname": self.PATH})
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "x-content-type": "application/json",
            "x-vercel-blob-store-id": self._store_id,
            "x-vercel-blob-access": "private",
            "x-api-version": self.API_VERSION,
            "x-api-blob-request-id": (
                f"{self._store_id}:{int(time.time() * 1000)}:{uuid.uuid4().hex}"
            ),
            "x-api-blob-request-attempt": "0",
            "x-add-random-suffix": "0",
        }
        if previous_etag:
            headers["x-allow-overwrite"] = "1"
            headers["x-if-match"] = previous_etag
        else:
            headers["x-allow-overwrite"] = "0"

        req = request.Request(
            f"https://vercel.com/api/blob/?{query}",
            data=data,
            method="PUT",
            headers=headers,
        )
        try:
            with request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            # Existing-path and ETag mismatch responses are both concurrency
            # conflicts: reload the winner and replay the request.
            if exc.code in (409, 412):
                raise StateConflict() from None
            try:
                body = json.loads(exc.read().decode("utf-8"))
                code = body.get("error", {}).get("code")
            except Exception:
                code = None
            if code in {"precondition_failed", "blob_already_exists"}:
                raise StateConflict() from None
            raise StateUnavailable(f"state write failed with HTTP {exc.code}") from None
        except (error.URLError, TimeoutError, OSError) as exc:
            raise StateUnavailable(f"state write failed: {type(exc).__name__}") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise StateUnavailable("state write returned invalid JSON") from None

        etag = payload.get("etag") if isinstance(payload, dict) else None
        if not isinstance(etag, str) or not etag:
            raise StateUnavailable("state write returned no ETag")
        return etag


class PersistentHandler(http_app.Handler):
    """Handler that makes the in-memory service safe across Vercel instances."""

    MAX_WRITE_ATTEMPTS = 6

    def _dispatch(self):
        # Static assets and health are state-independent and should not spend a
        # Blob operation or wait on the state transaction lock.
        path = self.path.split("?", 1)[0]
        if path == "/health" or path.startswith("/assets/"):
            return super()._dispatch()

        self._extra_headers = {}
        try:
            raw = self._read_body()
        except (ValueError, OSError):
            self.close_connection = True
            self._respond(
                *http_app._envelope(400, "malformed_request", "unreadable request body")
            )
            return

        mutating = self.command not in {"GET", "HEAD", "OPTIONS"}
        attempts = self.MAX_WRITE_ATTEMPTS if mutating else 1

        with self.server.persistence_lock:
            for attempt in range(attempts):
                try:
                    snapshot, etag = self.server.state_store.load()
                    if snapshot is not None:
                        self.server.service.import_state(snapshot)
                except Exception as exc:
                    self._log_failure(exc)
                    self._respond(
                        *http_app._envelope(
                            503,
                            "service_unavailable",
                            "hosted demo state is temporarily unavailable",
                        )
                    )
                    return

                try:
                    status, body = self._handle(raw)
                except ApiError as exc:
                    status, body = exc.status, exc.to_body()
                except Exception as exc:
                    self._log_failure(exc)
                    status, body = http_app._envelope(
                        500, "internal_error", "internal error"
                    )

                should_write = mutating and 200 <= status < 400
                if should_write:
                    try:
                        document = self.server.service.export_state()
                        self.server.state_store.save(document, etag)
                    except StateConflict:
                        # Another instance committed first. Reload and replay
                        # from the same raw request before the client sees a
                        # response. The final response therefore always matches
                        # the state that actually became durable.
                        continue
                    except Exception as exc:
                        self._log_failure(exc)
                        self._respond(
                            *http_app._envelope(
                                503,
                                "service_unavailable",
                                "hosted demo state could not be saved",
                            )
                        )
                        return

                self._respond(status, body)
                return

        self._respond(
            *http_app._envelope(
                503,
                "service_unavailable",
                "hosted demo is busy; retry the request",
            )
        )


def serve(port: int, host: str = "0.0.0.0") -> None:
    server = http_app.make_server(host, port)
    server.RequestHandlerClass = PersistentHandler
    server.state_store = BlobStateStore()
    server.persistence_lock = threading.RLock()
    http_app.sys.stderr.write(
        f"tablekeeper Vercel demo listening on {host}:{server.server_address[1]}\n"
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
