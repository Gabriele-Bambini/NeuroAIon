"""No output artefact may reveal that the review was produced by software/AI.

The review is authored as human work. This test runs a full mock pipeline and
scans every shipped artefact (manuscript, checklist, manifest, audit trail,
references, documents) for brand names, agent class-names and AI-vendor
fingerprints. It is the regression guard for the de-branding requirement.
"""
import re
from pathlib import Path

from neuroaion.orchestrator import Orchestrator

# Terms that must never appear in a shipped artefact (case-insensitive).
_FORBIDDEN = [
    "neuroaion", "automated pipeline", "automated systematic-review",
    "language model", "anthropic", "openai", "gpt-", "claude",
    # Internal software-component names.
    "dataextractor", "riskofbiasassessor", "evidencesynthesizer",
    "protocolarchitect", "searchstrategist", "eligibilityadjudicator",
    "titleabstractscreener", "dualscreenadjudicator", "scopingagent",
]
# Artefacts intended for internal/debug use, not part of the human deliverable.
_SKIP = {"state.json", "screening_handoff.json"}


def test_no_brand_or_ai_leak_in_output(tmp_path):
    orch = Orchestrator({"title": "AI-assisted colonoscopy and adenoma detection"},
                        mock=True, make_latex=True, compile_pdf=False, make_bundle=False)
    orch.run(out_root=str(tmp_path))
    out = orch.last_out_dir

    scanned = 0
    leaks: list[str] = []
    for f in Path(out).rglob("*"):
        if not f.is_file() or f.name in _SKIP:
            continue
        if f.suffix.lower() not in (".md", ".txt", ".json", ".csv", ".bib",
                                    ".tex", ".html", ".jsonl", ".yaml", ".yml"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:  # noqa: BLE001
            continue
        scanned += 1
        for term in _FORBIDDEN:
            # Allow the mock provider's own honest self-labelling in the log file
            # only (state.json is skipped); everything else must be clean.
            if term in text:
                # Show a small context window to make failures debuggable.
                idx = text.find(term)
                ctx = re.sub(r"\s+", " ", text[max(0, idx - 40):idx + 40])
                leaks.append(f"{f.relative_to(out)} :: '{term}' :: …{ctx}…")

    assert scanned > 5, f"expected to scan several artefacts, only saw {scanned}"
    assert not leaks, "De-branding leak(s) in shipped output:\n" + "\n".join(leaks[:20])


def test_bundle_zip_is_clean(tmp_path):
    """The shareable bundle must contain NO internal/leaky file — not even the
    resume-only state.json (which carries the model id and the run log)."""
    import zipfile

    orch = Orchestrator({"title": "AI-assisted colonoscopy and adenoma detection"},
                        mock=True, make_latex=True, compile_pdf=False, make_bundle=True)
    orch.run(out_root=str(tmp_path))
    zips = list(Path(orch.last_out_dir).glob("*_bundle.zip"))
    assert zips, "no bundle produced"
    leaks: list[str] = []
    with zipfile.ZipFile(zips[0]) as zf:
        names = zf.namelist()
        # Internal resume/state files must be excluded from the deliverable.
        assert "state.json" not in names and "screening_handoff.json" not in names
        for n in names:
            if not n.lower().endswith((".md", ".txt", ".json", ".csv", ".bib",
                                       ".tex", ".html", ".jsonl", ".yaml", ".yml")):
                continue
            text = zf.read(n).decode("utf-8", "ignore").lower()
            for term in _FORBIDDEN:
                if term in text:
                    idx = text.find(term)
                    ctx = re.sub(r"\s+", " ", text[max(0, idx - 40):idx + 40])
                    leaks.append(f"{n} :: '{term}' :: …{ctx}…")
    assert not leaks, "De-branding leak(s) in bundle:\n" + "\n".join(leaks[:20])
