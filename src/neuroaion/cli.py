"""Command-line interface: `neuroaion run --protocol config/protocol.example.yaml`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .orchestrator import Orchestrator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="neuroaion",
        description="Full-auto, PRISMA 2020-compliant systematic review engine (10 agents).",
    )
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run a full systematic review from a protocol file.")
    run.add_argument("--protocol", "-p", required=True,
                     help="Path to a YAML protocol seed file.")
    run.add_argument("--out", "-o", default="runs", help="Output root directory.")
    run.add_argument("--model", default=None, help=f"Model (default {config.DEFAULT_MODEL}).")
    run.add_argument("--workers", type=int, default=None, help="Concurrent screening workers.")
    run.add_argument("--mock", action="store_true",
                     help="Force offline mock run (no API key, synthetic corpus).")
    run.add_argument("--live-sources", action="store_true",
                     help="Query real literature APIs even in mock mode.")

    sub.add_parser("agents", help="List the ten agents and their PRISMA responsibilities.")

    args = parser.parse_args(argv)

    if args.command == "agents":
        from .agents import ROSTER
        print("NeuroAIon — the ten-agent PRISMA 2020 roster:\n")
        for num, name, role in ROSTER:
            print(f"  {num:>2}. {name:<24} {role}")
        return 0

    if args.command == "run":
        seed = config.load_protocol_file(args.protocol)
        live = True if args.live_sources else None
        orch = Orchestrator(
            seed, mock=args.mock, live_sources=live,
            model=args.model, max_workers=args.workers,
        )
        if orch.mock:
            print("ℹ  Running in MOCK mode (no ANTHROPIC_API_KEY). "
                  "Set the key for a real, model-authored review.", file=sys.stderr)
        state = orch.run(out_root=args.out)
        print(f"\nDone → {Path(args.out) / state.run_id / 'report.md'}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
