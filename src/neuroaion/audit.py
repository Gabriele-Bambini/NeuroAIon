"""Auditable process evidence: a per-decision audit trail and a provenance
manifest with SHA-256 integrity checksums.

These artefacts let a third party verify *how* the review was produced: every
screening / eligibility / extraction / risk-of-bias decision is logged with its
actor and rationale, and the manifest records the engine, model, parameters,
software versions and a cryptographic checksum of every output file.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import platform
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .models import ReviewState

_FIELDS = ["seq", "phase", "actor", "uid", "title", "decision", "confidence", "reason"]


def build_events(state: ReviewState) -> list[dict]:
    """Flatten every recorded decision into an ordered, auditable event list."""
    title = {r.uid: r.title for r in state.unique_records}
    events: list[dict] = []

    for d in state.screening:
        events.append({"phase": "screening", "actor": d.reviewer, "uid": d.uid,
                       "title": title.get(d.uid, "")[:120],
                       "decision": d.decision.value, "confidence": d.confidence,
                       "reason": d.reason})
    for e in state.eligibility:
        events.append({"phase": "eligibility", "actor": "EligibilityAdjudicator",
                       "uid": e.uid, "title": title.get(e.uid, "")[:120],
                       "decision": "eligible" if e.eligible else "excluded",
                       "confidence": "",
                       "reason": e.exclusion_reason or e.notes})
    for ex in state.extractions:
        events.append({"phase": "extraction", "actor": "DataExtractor", "uid": ex.uid,
                       "title": ex.study_label, "decision": "extracted", "confidence": "",
                       "reason": f"n={ex.sample_size}; effects={len(ex.effects)}"})
    for a in state.rob:
        events.append({"phase": "risk_of_bias", "actor": "RiskOfBiasAssessor",
                       "uid": a.uid, "title": a.study_label, "decision": a.overall,
                       "confidence": "", "reason": a.rationale})
    for i, e in enumerate(events, 1):
        e["seq"] = i
    return events


def write_audit(out_dir: Path, state: ReviewState) -> list[Path]:
    """Write the audit trail as JSONL, CSV, and a human-readable report."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    events = build_events(state)
    written = []

    jsonl = out_dir / "audit_trail.jsonl"
    jsonl.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events),
                     encoding="utf-8")
    written.append(jsonl)

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_FIELDS)
    w.writeheader()
    for e in events:
        w.writerow({k: e.get(k, "") for k in _FIELDS})
    csvp = out_dir / "audit_log.csv"
    csvp.write_text(buf.getvalue(), encoding="utf-8")
    written.append(csvp)

    # Human-readable summary.
    from collections import Counter
    per_phase = Counter(e["phase"] for e in events)
    rob_dist = Counter(a.overall for a in state.rob)
    excl = Counter(e.exclusion_reason or "Other" for e in state.eligibility
                   if e.full_text_retrieved and not e.eligible)
    md = [f"# Review process log — {state.protocol.title or state.run_id}", "",
          f"Compiled {datetime.utcnow().isoformat()[:10]}. This log records the "
          "study-selection, extraction and appraisal steps for auditability.", "",
          "## Process summary",
          f"- Records identified: **{state.prisma.records_total}** "
          f"(de-duplicated to {state.prisma.records_screened}; "
          f"removed {state.prisma.duplicates_removed}).",
          f"- Dual title/abstract screening: **{len(state.included_after_screening)}** "
          f"retained. Inter-rater agreement Cohen's κ = **{state.cohen_kappa}**.",
          f"- Reports assessed: **{state.prisma.reports_assessed}**; "
          f"excluded with reasons: **{sum(excl.values())}**.",
          f"- Studies included: **{state.prisma.studies_included}**.",
          f"- Risk-of-bias distribution: "
          + (", ".join(f"{k}: {v}" for k, v in rob_dist.items()) or "—") + ".",
          "", "## Decision events logged",
          f"Total auditable decision events: **{len(events)}** "
          + "(" + ", ".join(f"{k}: {v}" for k, v in per_phase.items()) + ").",
          "", "Full per-record trail: `audit_log.csv` / `audit_trail.jsonl`. "
          "Integrity checksums of every artefact: `manifest.json`.",
          "", "## Exclusion reasons (full text)"]
    if excl:
        md += ["| Reason | n |", "|---|---|"] + [f"| {k} | {v} |" for k, v in excl.items()]
    else:
        md.append("_None._")
    rep = out_dir / "audit_report.md"
    rep.write_text("\n".join(md), encoding="utf-8")
    written.append(rep)
    return written


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _package_versions() -> dict:
    from importlib.metadata import PackageNotFoundError, version
    out = {}
    for pkg in ["anthropic", "pydantic", "numpy", "scipy", "rapidfuzz",
                "reportlab", "requests", "PyYAML"]:
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            pass
    return out


def write_manifest(out_dir: Path, state: ReviewState) -> Path:
    """Write a provenance + integrity manifest hashing every output file."""
    out_dir = Path(out_dir)
    checksums = {}
    for f in sorted(out_dir.rglob("*")):
        if (f.is_file() and f.name != "manifest.json"
                and not f.name.endswith("_bundle.zip")):
            checksums[str(f.relative_to(out_dir))] = _sha256(f)

    p = state.protocol
    manifest = {
        "engine": "NeuroAIon", "version": __version__,
        "run_id": state.run_id, "created_at": state.created_at,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "title": p.title, "question": p.question,
        "parameters": {
            "sources": p.search.sources,
            "date_range": [p.search.date_from, p.search.date_to],
            "effect_measure": p.synthesis.effect_measure,
            "model_type": p.synthesis.model,
            "risk_of_bias_tool": p.risk_of_bias.tool,
        },
        "counts": {
            "records_identified": state.prisma.records_total,
            "duplicates_removed": state.prisma.duplicates_removed,
            "records_screened": state.prisma.records_screened,
            "reports_assessed": state.prisma.reports_assessed,
            "studies_included": state.prisma.studies_included,
            "cohen_kappa": state.cohen_kappa,
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "packages": _package_versions(),
        },
        "integrity": {"algorithm": "sha256", "files": checksums},
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
