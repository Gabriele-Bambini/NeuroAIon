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
        description="Full-auto, PRISMA 2020-compliant systematic review engine (8 agents).",
    )
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run a full systematic review from a protocol file.")
    run.add_argument("--protocol", "-p",
                     help="Path to a YAML protocol seed file (omit only with --from-state).")
    run.add_argument("--out", "-o", default="runs", help="Output root directory.")
    run.add_argument("--model", default=None, help=f"Model (default {config.DEFAULT_MODEL}).")
    run.add_argument("--workers", type=int, default=None, help="Concurrent screening workers.")
    run.add_argument("--mock", action="store_true",
                     help="Force offline mock run (no API key, synthetic corpus).")
    run.add_argument("--live-sources", action="store_true",
                     help="Query real literature APIs even in mock mode.")
    run.add_argument("--no-fulltext", action="store_true",
                     help="Skip full-text retrieval (assess from abstracts only).")
    run.add_argument("--no-latex", action="store_true",
                     help="Skip LaTeX paper generation.")
    run.add_argument("--no-pdf", action="store_true",
                     help="Generate paper.tex but do not attempt local PDF compilation.")
    run.add_argument("--provider", help="LLM backend: anthropic | deepseek | openai | custom | mock.")
    run.add_argument("--screen-provider",
                     help="Separate backend for the high-volume screening stage (e.g. deepseek).")
    run.add_argument("--screen-model", help="Model id for the screening provider (e.g. DeepSeek V4 Pro).")
    run.add_argument("--stop-after", choices=["screen"],
                     help="Stop after screening and export the included set for write-up.")
    run.add_argument("--from-state",
                     help="Resume the redaction half from a screening checkpoint (state.json).")
    run.add_argument("--save-zip", metavar="PATH",
                     help="Also save the full review bundle to a local path "
                          "(e.g. ~/Desktop/review.zip).")
    run.add_argument("--no-bundle", action="store_true",
                     help="Do not create the portable zip bundle of artefacts.")

    sub.add_parser("agents", help="List the eight agents and their PRISMA responsibilities.")

    args = parser.parse_args(argv)

    if args.command == "agents":
        from .agents import ROSTER
        print("NeuroAIon — the eight-agent PRISMA 2020 roster:\n")
        for num, name, role in ROSTER:
            print(f"  {num:>2}. {name:<24} {role}")
        return 0

    if args.command == "run":
        # Provider routing overrides (mutate config so factories pick them up).
        if args.provider:
            config.PROVIDER = args.provider.strip().lower()
        if args.screen_provider:
            config.SCREEN_PROVIDER = args.screen_provider.strip().lower()
        if args.screen_model:
            config.SCREEN_MODEL = args.screen_model.strip()

        from_state = None
        if args.from_state:
            from .models import ReviewState
            from_state = ReviewState.model_validate_json(Path(args.from_state).read_text())
            seed: dict = {}
        elif args.protocol:
            seed = config.load_protocol_file(args.protocol)
        else:
            run.error("provide --protocol (or --from-state to resume).")

        live = True if args.live_sources else None
        fetch_ft = False if args.no_fulltext else None
        orch = Orchestrator(
            seed, mock=args.mock, live_sources=live,
            model=args.model, max_workers=args.workers, fetch_fulltext=fetch_ft,
            make_latex=not args.no_latex, compile_pdf=not args.no_pdf,
            make_bundle=not args.no_bundle, save_zip=args.save_zip,
            stop_after=args.stop_after, from_state=from_state,
        )
        if orch.mock:
            print("ℹ  Running in MOCK mode (no ANTHROPIC_API_KEY). "
                  "Set the key for a real, model-authored review.", file=sys.stderr)
        state = orch.run(out_root=args.out)
        base = Path(args.out)
        if args.stop_after == "screen":
            d = base / state.run_id
            print(f"\nScreening checkpoint → {d}/  "
                  f"(resume the write-up with:  --from-state {d}/state.json)")
        elif args.from_state:
            print(f"\nDone → {base / (state.run_id + '-writeup') / 'report.md'}")
        else:
            print(f"\nDone → {base / state.run_id / 'report.md'}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
