"""Seed the Vercel demo exactly once, when durable state does not exist yet."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from urllib import error, request

from tablekeeper.vercel_persistence import BlobStateStore

PORT = int(os.environ.get("PORT") or 8080)
BASE = f"http://127.0.0.1:{PORT}"


def wait_for_health() -> None:
    for _ in range(80):
        try:
            with request.urlopen(f"{BASE}/health", timeout=1) as resp:
                if resp.status == 200:
                    return
        except (error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.25)
    raise RuntimeError("Tablekeeper did not become healthy")


def main() -> None:
    wait_for_health()
    document, _ = BlobStateStore().load()
    if document is not None:
        return
    subprocess.check_call([sys.executable, "vercel_seed.py", "--base", BASE])


if __name__ == "__main__":
    main()
