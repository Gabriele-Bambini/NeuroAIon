"""Per-source screening workbooks with a 1–10 PICO-affinity score.

A reviewer auditing the search wants to see, source by source, exactly what each
database returned and how relevant it was — the artefact a human builds by hand
when they export a PubMed / Embase / Scopus result set into a spreadsheet and
grade each hit. This module reproduces that: one worksheet per source, every
record scored 1–10 for affinity to the PICO question, plus an ``All records``
master sheet and a ``Summary`` sheet reconciling per-source yield with the
PRISMA counts.

The affinity score is *derived from the screening decision*, not invented: an
included record with high screener confidence scores near 10, a confident
exclusion near 1, a "maybe" in the middle, with unscreened records graded by a
transparent keyword-overlap heuristic against the protocol's PICO terms. The
rule is documented in ``affinity_score`` so the number is defensible.

If ``openpyxl`` is installed a real multi-sheet ``.xlsx`` is written; otherwise
the same tables are emitted as one CSV per source so the audit trail never
depends on an optional package.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import Decision, Record, ReviewState

_COLUMNS = [
    "citation_no", "affinity_1_10", "screening", "confidence", "reason",
    "authors", "year", "title", "journal", "doi", "pmid", "pmcid",
    "other_ids", "found_by", "url",
]


def _tokens(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) > 2}


def _pico_terms(state: ReviewState) -> set[str]:
    p = state.protocol
    parts = [getattr(p, "title", "")]
    pico = getattr(p, "pico", None)
    if pico is not None:
        for f in ("population", "intervention", "comparator", "outcome"):
            parts.append(str(getattr(pico, f, "") or ""))
    # SearchConfig.keywords is a list of synonym groups (list[list[str]]).
    for group in getattr(getattr(p, "search", None), "keywords", []) or []:
        parts.extend(group if isinstance(group, list) else [group])
    terms: set[str] = set()
    for part in parts:
        terms |= _tokens(str(part))
    return terms


def affinity_score(record: Record, decision: Decision | None, confidence: float,
                   pico_terms: set[str]) -> int:
    """A defensible 1–10 relevance grade for one record.

    Screened records are graded from the decision and the screener's confidence
    (include → 6–10, maybe → 4–7, exclude → 1–4). Unscreened records fall back to
    the Jaccard overlap between the record's title/abstract tokens and the PICO
    terms, mapped onto 1–10. The score is monotone in confidence within each
    decision band, so ordering a sheet by affinity ranks the most-relevant hits
    first.
    """
    conf = max(0.0, min(1.0, confidence if confidence is not None else 0.5))
    if decision == Decision.INCLUDE:
        return int(round(6 + 4 * conf))                     # 6..10
    if decision == Decision.EXCLUDE:
        return int(round(4 - 3 * conf))                     # 4..1
    if decision == Decision.MAYBE:
        return int(round(4 + 3 * conf))                     # 4..7
    # Unscreened: keyword-overlap heuristic.
    rec_terms = _tokens(record.title) | _tokens(record.abstract)
    if not pico_terms or not rec_terms:
        return 3
    jac = len(rec_terms & pico_terms) / len(pico_terms)
    return max(1, min(10, int(round(1 + 9 * min(1.0, jac * 2)))))


def _rows(state: ReviewState) -> list[dict]:
    """One dict per unique record with its affinity and screening columns."""
    pico_terms = _pico_terms(state)
    # Most-confident screening decision per uid.
    best: dict[str, tuple[Decision, float, str]] = {}
    for s in state.screening:
        cur = best.get(s.uid)
        if cur is None or s.confidence > cur[1]:
            best[s.uid] = (s.decision, s.confidence, s.reason)
    rows = []
    for r in state.unique_records:
        dec, conf, reason = best.get(r.uid, (None, 0.5, ""))
        ids = r.all_ids()
        other = {k: v for k, v in ids.items() if k not in ("doi", "pmid", "pmcid")}
        rows.append({
            "citation_no": state.citation_numbers.get(r.uid, ""),
            "affinity_1_10": affinity_score(r, dec, conf, pico_terms),
            "screening": dec.value if dec else "not screened",
            "confidence": round(conf, 2) if dec else "",
            "reason": reason,
            "authors": "; ".join(r.authors[:6]),
            "year": r.year or "",
            "title": r.title,
            "journal": r.journal,
            "doi": ids.get("doi", ""),
            "pmid": ids.get("pmid", ""),
            "pmcid": ids.get("pmcid", ""),
            "other_ids": "; ".join(f"{k}:{v}" for k, v in other.items()),
            "found_by": "; ".join(r.found_by or [r.source]),
            "url": r.url,
            "_sources": r.found_by or [r.source],
        })
    return rows


def write_source_workbooks(out_dir: str | Path, state: ReviewState) -> list[Path]:
    """Write the per-source screening workbook(s). Returns the paths written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _rows(state)
    sources = sorted({s for r in rows for s in r["_sources"]})
    try:
        return [_write_xlsx(out_dir / "screening_workbook.xlsx", rows, sources, state)]
    except ImportError:
        return _write_csvs(out_dir, rows, sources)


def _sorted(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (-int(r["affinity_1_10"]), str(r["authors"])))


def _write_xlsx(path: Path, rows: list[dict], sources: list[str],
                state: ReviewState) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F4E79")

    def sheet(title: str, subset: list[dict]):
        ws = wb.create_sheet(title[:31])
        ws.append(_COLUMNS)
        for c in range(1, len(_COLUMNS) + 1):
            cell = ws.cell(row=1, column=c)
            cell.font, cell.fill = header_font, header_fill
        for r in _sorted(subset):
            ws.append([r[c] for c in _COLUMNS])
            aff = ws.cell(row=ws.max_row, column=2)
            # Green→amber→red affinity shading.
            v = int(r["affinity_1_10"])
            colour = "C6EFCE" if v >= 7 else ("FFEB9C" if v >= 4 else "FFC7CE")
            aff.fill = PatternFill("solid", fgColor=colour)
        ws.freeze_panes = "A2"
        for c in range(1, len(_COLUMNS) + 1):
            ws.column_dimensions[get_column_letter(c)].width = \
                {"title": 60, "reason": 40, "authors": 30}.get(_COLUMNS[c - 1], 14)
        return ws

    # Summary sheet first.
    summ = wb.active
    summ.title = "Summary"
    summ.append(["Source", "Records returned", "Mean affinity", "Included", "Excluded", "Maybe"])
    for c in range(1, 7):
        summ.cell(row=1, column=c).font = header_font
        summ.cell(row=1, column=c).fill = header_fill
    for src in sources:
        sub = [r for r in rows if src in r["_sources"]]
        affs = [int(r["affinity_1_10"]) for r in sub]
        summ.append([
            src, len(sub), round(sum(affs) / len(affs), 1) if affs else 0,
            sum(1 for r in sub if r["screening"] == "include"),
            sum(1 for r in sub if r["screening"] == "exclude"),
            sum(1 for r in sub if r["screening"] == "maybe"),
        ])
    summ.append([])
    summ.append(["TOTAL unique records", len(rows)])
    summ.append(["Duplicates removed", state.prisma.duplicates_removed])
    summ.append(["Studies included", state.prisma.studies_included])

    sheet("All records", rows)
    for src in sources:
        sheet(src, [r for r in rows if src in r["_sources"]])
    wb.save(path)
    return path


def _write_csvs(out_dir: Path, rows: list[dict], sources: list[str]) -> list[Path]:
    written: list[Path] = []
    folder = out_dir / "screening_workbook"
    folder.mkdir(exist_ok=True)
    for name, subset in [("all_records", rows)] + \
            [(s, [r for r in rows if s in r["_sources"]]) for s in sources]:
        p = folder / f"{re.sub(r'[^A-Za-z0-9._-]', '_', name)}.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=_COLUMNS, extrasaction="ignore")
            w.writeheader()
            for r in _sorted(subset):
                w.writerow({c: r[c] for c in _COLUMNS})
        written.append(p)
    return written
