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
                     help="Force offline mock run (tests/demos; synthetic placeholder text).")
    run.add_argument("--allow-mock", action="store_true",
                     help="Permit falling back to mock when no real provider is available "
                          "(otherwise the run fails closed instead of fabricating a review).")
    run.add_argument("--live-sources", action="store_true",
                     help="Query real literature APIs even in mock mode.")
    run.add_argument("--no-fulltext", action="store_true",
                     help="Skip full-text retrieval (assess from abstracts only).")
    run.add_argument("--no-latex", action="store_true",
                     help="Skip LaTeX paper generation.")
    run.add_argument("--no-pdf", action="store_true",
                     help="Generate paper.tex but do not attempt local PDF compilation.")
    run.add_argument("--provider",
                     help="LLM backend: anthropic | cowork | deepseek | openai | custom | mock. "
                          "'cowork' = driven by the controlling agent on your subscription (no API key).")
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

    ask = sub.add_parser(
        "ask", help="Question → complete review. Give a plain-English question; the "
                    "tool derives the PICO, searches, screens, extracts, appraises, "
                    "meta-analyses and writes the manuscript.")
    ask.add_argument("question", help='e.g. "Does AI-assisted colonoscopy improve adenoma detection?"')
    ask.add_argument("--out", "-o", default="runs", help="Output root directory.")
    ask.add_argument("--model", default=None, help=f"Model (default {config.DEFAULT_MODEL}).")
    ask.add_argument("--workers", type=int, default=None, help="Concurrent screening workers.")
    ask.add_argument("--provider",
                     help="LLM backend: anthropic | cowork | deepseek | openai | custom | mock. "
                          "'cowork' = driven by the controlling agent on your subscription.")
    ask.add_argument("--allow-mock", action="store_true",
                     help="Permit synthetic placeholder output when no provider is available.")
    ask.add_argument("--mock", action="store_true", help="Force offline mock run (demo).")
    ask.add_argument("--no-latex", action="store_true", help="Skip LaTeX paper generation.")
    ask.add_argument("--no-pdf", action="store_true", help="Skip local PDF compilation.")
    ask.add_argument("--no-bundle", action="store_true", help="Skip the portable zip bundle.")
    ask.add_argument("--save-zip", metavar="PATH", help="Also save the bundle to a local path.")

    sub.add_parser("agents", help="List the eight agents and their PRISMA responsibilities.")

    new = sub.add_parser("new", help="Interactive setup wizard: choose topic, framework "
                                     "(PICO/PECO/SPIDER/…), RoB tool, citation style, etc.")
    new.add_argument("--out", "-o", help="Folder to create for the protocol + outputs.")

    args = parser.parse_args(argv)

    if args.command == "new":
        from . import wizard
        seed, out_path, run_now = wizard.interactive()
        out_path = args.out or out_path
        proto_path = wizard.write_protocol_yaml(seed, Path(out_path) / "protocol.yaml")
        print(f"\n✓ Protocol saved → {proto_path}")
        if run_now:
            orch = Orchestrator(seed)
            if orch.mock:
                print("ℹ  No LLM key configured — running in MOCK mode.", file=sys.stderr)
            orch.run(out_root=out_path)
            print(f"\nDone → {orch.last_out_dir}")
        else:
            print(f"Next:  neuroaion run -p {proto_path} --out {out_path}")
        return 0

    if args.command == "ask":
        if args.provider:
            config.PROVIDER = args.provider.strip().lower()
        seed = {"question": args.question, "search": {"snowball": True}}
        live = None  # live sources when a real provider drives the run
        orch = Orchestrator(
            seed, mock=args.mock, live_sources=live, model=args.model,
            max_workers=args.workers, make_latex=not args.no_latex,
            compile_pdf=not args.no_pdf, make_bundle=not args.no_bundle,
            save_zip=args.save_zip,
        )
        # Fail closed: never pass off placeholder text as a real review.
        if orch.mock and not (args.mock or args.allow_mock):
            ask.error(
                "no LLM provider available — refusing to fabricate a review.\n"
                "  • API mode:    set ANTHROPIC_API_KEY (or a DeepSeek/OpenAI key), or\n"
                "  • Cowork mode: run under an agent on your subscription with "
                "--provider cowork, or\n"
                "  • Demo:        pass --allow-mock to accept synthetic placeholder output.")
        if orch.mock:
            print("ℹ  Running in MOCK mode — synthetic placeholder output, not a real review.",
                  file=sys.stderr)
        print(f"⟳ Formulating the protocol from your question and running the review …",
              file=sys.stderr)
        orch.run(out_root=args.out)
        print(f"\nDone → {orch.last_out_dir}/  (open report.md / paper.pdf / documents/)")
        return 0

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
        # Fail closed: never fabricate a real-looking review with placeholder text.
        if orch.mock and not (args.mock or args.allow_mock):
            run.error(
                "no LLM provider available — refusing to fabricate a review.\n"
                "  • API mode:    set ANTHROPIC_API_KEY (or a DeepSeek/OpenAI key), or\n"
                "  • Cowork mode: run under an agent on your subscription with "
                "--provider cowork (bind llm.set_cowork_handler or set NEUROAION_COWORK_DIR), or\n"
                "  • Testing:     pass --mock / --allow-mock to accept synthetic placeholder output.")
        if orch.mock:
            print("ℹ  Running in MOCK mode — synthetic placeholder output, not a real review.",
                  file=sys.stderr)
        orch.run(out_root=args.out)
        d = orch.last_out_dir
        if args.stop_after == "screen":
            print(f"\nScreening checkpoint → {d}/  "
                  f"(resume the write-up with:  --from-state {d}/state.json)")
        else:
            print(f"\nDone → {d}/  (open report.md / paper.pdf / documents/)")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
