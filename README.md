# NeuroAIon — full-auto PRISMA 2020 systematic-review engine

> Stanzia 10 agenti Claude e produce una *systematic review* completa, conforme a
> **PRISMA 2020**, in modalità **full-auto**: dalla domanda PICO al **paper LaTeX
> redatto** (PDF) con formule, figure (diagramma di flusso + forest plot),
> tabelle, checklist a 27 voci, meta-analisi e bibliografia.

A conductor orchestrates **ten specialised agents** (Claude Opus 4.8) through the
entire systematic-review workflow. Every deterministic computation —
de-duplication, meta-analysis, heterogeneity, **Egger's test**, PRISMA flow
counts, Cohen's κ — is done in Python; the language model is used only for
judgement and narrative, **never** to invent statistics. The engine pulls records
from **nine free / open** literature sources and writes a complete, reproducible
audit trail.

**100% free sources (no paid keys):** PubMed · Europe PMC · Crossref · OpenAlex ·
bioRxiv/medRxiv · **ClinicalTrials.gov** · **DOAJ** · **Semantic Scholar** ·
**arXiv**. Full text is retrieved from PMC open-access + Europe PMC, with an
optional Unpaywall→PDF path (`pip install neuroaion[oa]`). Everything is toggled
from the protocol file — *full optional*.

```
ProtocolArchitect → SearchStrategist → DeduplicationAgent → TitleAbstractScreener
        → DualScreenAdjudicator → FullTextEligibility → DataExtractor
        → RiskOfBiasAssessor → EvidenceSynthesizer → PRISMAReporter
```

## The ten agents (each mapped to PRISMA 2020 items)

| # | Agent | Responsibility | PRISMA |
|---|-------|----------------|--------|
| 1 | **ProtocolArchitect** | Research question, PICO/PECO, eligibility contract | 4–7 |
| 2 | **SearchStrategist** | Per-database Boolean strategies + identification | 6–8 |
| 3 | **DeduplicationAgent** | Cross-source de-duplication (DOI + fuzzy title) | 16a |
| 4 | **TitleAbstractScreener** | Reviewer 1 — title/abstract screening | 8 |
| 5 | **DualScreenAdjudicator** | Reviewer 2 + conflict resolution, Cohen's κ | 8, 16 |
| 6 | **FullTextEligibility** | Full-text assessment + exclusion reasons | 16b |
| 7 | **DataExtractor** | Structured extraction (PICO, designs, effect sizes) | 9–10 |
| 8 | **RiskOfBiasAssessor** | RoB2 / ROBINS-I / Newcastle–Ottawa + GRADE | 11–12, 15 |
| 9 | **EvidenceSynthesizer** | Qualitative synthesis + random-effects meta-analysis (I², τ²) | 13, 20 |
| 10 | **PRISMAReporter** | Flow diagram, 27-item checklist, full manuscript + QA | 14–27 |

## Quickstart

```bash
pip install -r requirements.txt          # or: pip install -e .

# 1) Offline demo — runs the whole pipeline with a synthetic corpus, NO API key:
python scripts/run_review.py --protocol config/protocol.example.yaml --mock

# 2) Real review — set your key, then run for real against live databases:
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/run_review.py --protocol config/protocol.example.yaml

# Inspect the roster:
PYTHONPATH=src python -m neuroaion.cli agents
```

Outputs land in `runs/<timestamp>/`:

| File | Contents |
|------|----------|
| **`paper.tex`** | **Publication-grade LaTeX paper** — self-contained, `latexmk -pdf`-ready: title/abstract, methods with typeset estimator **equations**, **TikZ PRISMA flow diagram** + **TikZ forest plot** (vector figures), booktabs tables, GRADE, 27-item checklist, embedded BibTeX |
| **`paper.pdf`** | The compiled PDF (when a TeX engine is available, or via the GitHub Action) |
| `references.bib` | BibTeX bibliography of included studies |
| `report.md` | The same review as Markdown (Mermaid flow diagram, GitHub-renderable) |
| `state.json` | Complete, resumable run state (every decision, every score) |
| `prisma_flow.json` | PRISMA flow counts |
| `extractions.json` | Structured data-extraction records |
| `included_studies.csv` | Final included set with citations + DOIs |
| `prospero_registration.md` | Ready-to-submit PROSPERO registration form (PRISMA 24) |

### Compile the PDF

```bash
cd runs/<timestamp> && latexmk -pdf paper.tex     # → paper.pdf
```

The engine compiles automatically if `latexmk`/`pdflatex` is on your PATH. The
figures are **pure TikZ** (no external images), so the document compiles anywhere
TeX + TikZ are installed — no missing-figure failures.

## Run it on GitHub (zero local setup)

The repo ships a GitHub Action (`.github/workflows/systematic-review.yml`):

- **Push / PR** → runs the test suite.
- **Actions → Systematic Review → Run workflow** → runs the full pipeline,
  **compiles the PDF**, and uploads `paper.pdf` + `report.md` + data as artifacts.
  Pick the protocol path, toggle mock/live. For a real (model-authored) review,
  add an `ANTHROPIC_API_KEY` repository secret and untick "mock".

## Writing your protocol

Copy `config/protocol.example.yaml` and edit it — it is the contract the whole
pipeline is held to. Specify PICO/PECO, inclusion/exclusion criteria, the
databases to search, the effect measure (`SMD`/`MD`/`OR`/`RR`/`HR`), the
meta-analysis model (`random`/`fixed`), and the risk-of-bias tool. Anything you
leave as `auto` or blank is filled in by the ProtocolArchitect; anything you
specify is honoured verbatim.

## Hybrid model routing — cheap screening, premium redaction

Screening is high-volume and low-stakes; redaction (extraction, synthesis,
manuscript) is low-volume and high-stakes. The engine lets you run each on a
different backend — e.g. a cheap **DeepSeek** model screens *every* record, then
a premium model (or **Claude in cowork**) writes up only the included studies.

Any **OpenAI-compatible** backend works (DeepSeek, OpenAI, Qwen, local
vLLM/Ollama) — you set the model id, so even models newer than this README are
supported.

```bash
# One-shot: DeepSeek for screening, Claude Opus for everything else.
export ANTHROPIC_API_KEY=...   DEEPSEEK_API_KEY=...
python scripts/run_review.py -p config/protocol.example.yaml \
    --provider anthropic --screen-provider deepseek --screen-model <deepseek-model-id>
```

### Two-phase handoff (cowork)

Run screening headless on the cheap model, then redact separately — the included
set is exported to `screening_handoff.json` and the run resumes from the
checkpoint:

```bash
# Phase 1 — cheap model screens all records, then stops.
python scripts/run_review.py -p protocol.yaml \
    --provider deepseek --screen-model <id> --stop-after screen
#   → runs/<ts>/screening_handoff.json  +  state.json

# Phase 2 — redact the included studies (premium model, or Claude in cowork).
python scripts/run_review.py --from-state runs/<ts>/state.json
#   → runs/<ts>-writeup/paper.tex, report.md, prospero_registration.md
```

| Stage | Volume | Suggested backend | Why |
|-------|--------|-------------------|-----|
| Screening | high (every record) | DeepSeek / Haiku | cheap, fast, good enough |
| Redaction | low (included only) | Claude Opus / cowork | judgement & writing quality |

## Full-text retrieval (PRISMA 16b)

Eligibility, data extraction and risk-of-bias are run on the **full text** of each
record sought for retrieval, not just the abstract. The engine resolves a record
(DOI/PMID) to a PubMed Central open-access full text — the same corpus the PMC MCP
server exposes — and reconstructs readable body text from the JATS XML; preprints
are pulled via Europe PMC. When no open-access full text exists, it falls back to
the abstract and marks the report accordingly, so the PRISMA "reports not
retrieved" count is real.

Retrieval is **pluggable** so it works wherever the host can reach the data:

| Channel | When | How |
|---------|------|-----|
| `HttpFullTextRetriever` (default) | Host with open egress (your machine, CI) | Direct HTTPS to NCBI ID-converter + Europe PMC `fullTextXML` |
| `McpFullTextRetriever` | Agent host with the PMC / bioRxiv **MCP servers** | You inject the MCP tool callables; no direct outbound HTTP needed |

```python
from neuroaion.orchestrator import Orchestrator
from neuroaion.sources import McpFullTextRetriever

# Bind your MCP tools (e.g. the PMC server's convert_article_ids / get_full_text_article):
retriever = McpFullTextRetriever(
    convert_ids=lambda ids, idtype: mcp_convert_article_ids(ids, idtype),  # -> [{"pmcid": ...}]
    get_full_text=lambda pmc_ids: mcp_get_full_text_article(pmc_ids),       # -> body text
)
Orchestrator(seed, fulltext_retriever=retriever).run()
```

Disable retrieval (assess from abstracts only) with `--no-fulltext`.

> **Note on restricted environments.** In a sandbox with locked-down egress, direct
> HTTP to NCBI/Europe PMC may be blocked (HTTP 403); there, inject an
> `McpFullTextRetriever` bound to the approved MCP literature servers. The default
> HTTP retriever works on any host with normal internet access.

## How it stays honest

- **No fabricated numbers.** Pooled estimates, heterogeneity (DerSimonian–Laird
  τ², I², Cochran's Q), and κ are computed in `neuroaion/stats.py`. The model
  extracts reported values (and uses `null` when a value isn't reported) and
  writes prose — it never produces the statistics.
- **Two independent screeners + adjudication.** Reviewer 1 (sensitive) and
  Reviewer 2 (specific) screen every record independently; an adjudicator
  resolves conflicts. Inter-rater agreement is reported as Cohen's κ.
- **Full audit trail.** Every record, decision, score, and exclusion reason is
  persisted to `state.json`, checkpointed after each phase (resumable).
- **Mock mode.** With no API key the engine runs a deterministic, fully offline
  pipeline (synthetic corpus + `MockProvider`) so you can exercise and test the
  whole system — used by the test suite and CI.

## Architecture

```
src/neuroaion/
├── orchestrator.py   # the conductor (concurrency, checkpoints, phase wiring)
├── agents/           # the 10 agents (one module each)
├── sources/          # PubMed, Europe PMC, Crossref, OpenAlex, bioRxiv clients
├── llm.py            # Anthropic provider (Opus 4.8, adaptive thinking,
│                     #   structured outputs, prompt caching) + MockProvider
├── dedup.py          # deterministic de-duplication
├── stats.py          # meta-analysis + Cohen's κ
├── prisma.py         # flow counting, Mermaid diagram, 27-item checklist
├── report.py         # manuscript + artefact assembly
└── models.py         # typed, JSON-serialisable pipeline state
```

The LLM layer uses adaptive thinking, JSON-schema structured outputs, prompt
caching of the (large, stable) protocol context across the many per-record
screening/extraction calls, streaming for the long manuscript, and exponential
back-off retries.

## Configuration (`.env`)

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Required for live runs; absent → mock mode |
| `NEUROAION_MODEL` | Model id (default `claude-opus-4-8`) |
| `NCBI_API_KEY` | Optional — raises PubMed rate limit 3→10 req/s |
| `NEUROAION_CONTACT_EMAIL` | Polite-pool contact for NCBI/Crossref/OpenAlex |
| `NEUROAION_MAX_WORKERS` | Screening/extraction concurrency (default 8) |

## Tests

```bash
python -m pytest -q
```

Covers de-duplication, meta-analysis (incl. log-scale ratio measures), Cohen's κ,
PRISMA-flow consistency, and an end-to-end offline pipeline smoke + determinism test.

## Roadmap

- Network / multivariate meta-analysis.
- Subgroup and meta-regression analyses.

## Disclaimer

NeuroAIon automates the mechanics of a PRISMA review and is a powerful
accelerator, **not** a replacement for expert human judgement. A qualified
reviewer should verify the protocol, screening decisions, extracted data, and
risk-of-bias judgements before any review is published or used to inform
decisions.

---

MIT-licensed. Built on the Claude Agent platform.
