"""Start the service: python -m tablekeeper (listens on 0.0.0.0:$PORT, default 8080)."""
import os
import signal
import sys

from .http_app import serve


def main() -> None:
    # As PID 1 in a container, Python ignores SIGTERM unless a handler is set.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    serve(int(os.environ.get("PORT") or 8080))


if __name__ == "__main__":
    main()
