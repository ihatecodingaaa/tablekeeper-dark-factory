"""Vercel demo entrypoint with durable Blob-backed state."""
import os
import signal
import sys

from .vercel_persistence import serve


def main() -> None:
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    serve(int(os.environ.get("PORT") or 8080))


if __name__ == "__main__":
    main()
