# Demo review — full dossier (ILLUSTRATIVE DATA)

A sample of NeuroAIon's complete output. Study data are **illustrative**
(authored for demonstration, not a real evidence synthesis — the report header
says so). The statistics, documents, audit trail and integrity manifest are the
engine's real output.

## Manuscript & figures
- `report.md` — Markdown manuscript (Mermaid PRISMA flow renders on GitHub)
- `paper.pdf` — journal-grade two-column PDF (vector PRISMA / forest / funnel / RoB traffic-light)
- `paper.tex` — self-contained LaTeX (`latexmk -pdf`); `review.html` — browser version

## Formal documents (`documents/`)
| File | Document |
|------|----------|
| `01_protocol.md` | Review protocol (PICO, criteria, plan) |
| `02_search_log.md/.csv` | Per-database queries + hits |
| `03_screening_log.csv` | Per-record dual-reviewer decisions + adjudication |
| `04_excluded_full_text.md/.csv` | Excluded full texts with reasons (PRISMA 16b) |
| `05_data_extraction_form.csv` | Structured extraction table |
| `06_risk_of_bias.md` | Per-study RoB2 with domain rationales |
| `07_summary_of_findings.md` | GRADE Summary-of-Findings table |
| `08_prisma_checklist.md` | PRISMA 2020 27-item checklist |
| `prospero_registration.md` | Ready-to-submit PROSPERO form |

## Auditable process evidence
- `audit_trail.jsonl` / `audit_log.csv` — every screening / eligibility / extraction / RoB decision, with actor and rationale
- `audit_report.md` — human-readable process summary
- `manifest.json` — provenance (engine, model, parameters, software versions) + **SHA-256 checksum of every artefact** (integrity)
- `*_bundle.zip` — the entire dossier in one portable file

Reproduce: `python examples/make_demo.py` (illustrative) — or run the pipeline on real PubMed/PMC data with the literature MCP servers approved / an API key.
