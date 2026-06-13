#!/usr/bin/env python3
"""Zero-install launcher: `python scripts/run_review.py --protocol config/protocol.example.yaml`.

Adds ``src`` to the path so the engine runs without `pip install -e .`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neuroaion.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["run", *sys.argv[1:]]))
