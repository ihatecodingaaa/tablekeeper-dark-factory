"""Put a tablekeeper package with extras on sys.path.

After integration stage-4/tablekeeper is the full service (stage-3 core plus
extras/) and is used directly. Before that, the extras package is overlaid on
a stage-3 core named by TK_CORE_DIR (a folder containing tablekeeper/).
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
STAGE = HERE.parents[1]
DEFAULT_CORE = "/home/user/dark-factory-2026/band-work/final5-wt/x4-core/stage-3"


def _package_root() -> pathlib.Path:
    if (STAGE / "tablekeeper" / "service.py").is_file():
        return STAGE
    core = pathlib.Path(os.environ.get("TK_CORE_DIR", DEFAULT_CORE))
    if not (core / "tablekeeper" / "service.py").is_file():
        raise RuntimeError(f"no stage-3 core at {core}; set TK_CORE_DIR")
    root = pathlib.Path(tempfile.mkdtemp(prefix="tk-extras-"))
    skip = shutil.ignore_patterns("__pycache__", "web", "extras")
    shutil.copytree(core / "tablekeeper", root / "tablekeeper", ignore=skip)
    shutil.copytree(STAGE / "tablekeeper" / "extras", root / "tablekeeper" / "extras",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return root


for path in (str(_package_root()), str(HERE)):
    if path not in sys.path:
        sys.path.insert(0, path)
