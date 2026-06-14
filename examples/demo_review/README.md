# Demo review — output sample (ILLUSTRATIVE DATA)

This folder is a **sample of NeuroAIon's real engine output**. The study data are
**illustrative** (authored for demonstration, not a real evidence synthesis) — the
report header is marked accordingly. The **statistics and rendering are real**:
meta-analysis, Egger's test, Cohen's κ, PRISMA flow counts, TikZ figures, and the
LaTeX/PROSPERO documents are all produced by the engine.

| File | What it is |
|------|-----------|
| `report.md` | Full Markdown manuscript (Mermaid PRISMA flow diagram renders on GitHub) |
| `paper.tex` | Self-contained LaTeX paper (`latexmk -pdf paper.tex` → PDF) with TikZ forest + funnel plots and typeset equations |
| `prospero_registration.md` | Ready-to-submit PROSPERO registration form |
| `included_studies.csv` | Final included set |
| `extractions.json` / `prisma_flow.json` / `references.bib` | Structured data + bibliography |

Pooled SMD 0.28 [0.12, 0.44], I²=0%, Egger p=0.44, κ=0.69, 5 studies included (from 10 records).

To reproduce with **real** PubMed/PMC studies, run the pipeline with the literature
MCP servers approved, or headless with an API key.
