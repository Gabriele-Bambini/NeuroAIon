# NeuroAIon — full-auto PRISMA 2020 systematic-review engine

> Stanzia 10 agenti Claude e produce una *systematic review* completa, conforme a
> **PRISMA 2020**, in modalità **full-auto**: dalla domanda di ricerca al
> manoscritto con diagramma di flusso, checklist a 27 voci e meta-analisi.

A conductor orchestrates **ten specialised agents** (Claude Opus 4.8) through the
entire systematic-review workflow. Every deterministic computation —
de-duplication, meta-analysis, PRISMA flow counts, Cohen's κ — is done in Python;
the language model is used only for judgement and narrative, **never** to invent
statistics. The engine pulls records from real open literature APIs (PubMed,
Europe PMC, Crossref, OpenAlex, bioRxiv/medRxiv) and writes a complete,
reproducible audit trail.

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
| `report.md` | The manuscript: abstract, methods, **Mermaid PRISMA flow diagram**, characteristics / risk-of-bias / forest tables, GRADE, **27-item checklist**, references |
| `state.json` | Complete, resumable run state (every decision, every score) |
| `prisma_flow.json` | PRISMA flow counts |
| `extractions.json` | Structured data-extraction records |
| `included_studies.csv` | Final included set with citations + DOIs |

## Writing your protocol

Copy `config/protocol.example.yaml` and edit it — it is the contract the whole
pipeline is held to. Specify PICO/PECO, inclusion/exclusion criteria, the
databases to search, the effect measure (`SMD`/`MD`/`OR`/`RR`/`HR`), the
meta-analysis model (`random`/`fixed`), and the risk-of-bias tool. Anything you
leave as `auto` or blank is filled in by the ProtocolArchitect; anything you
specify is honoured verbatim.

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

- Plug the live MCP servers (PubMed full-text, bioRxiv/medRxiv) into the source
  layer for full-text eligibility and extraction.
- PROSPERO protocol registration export.
- Funnel-plot / Egger's test for small-study effects (PRISMA 14).
- Optional `matplotlib` forest-plot rendering (`pip install neuroaion[viz]`).

## Disclaimer

NeuroAIon automates the mechanics of a PRISMA review and is a powerful
accelerator, **not** a replacement for expert human judgement. A qualified
reviewer should verify the protocol, screening decisions, extracted data, and
risk-of-bias judgements before any review is published or used to inform
decisions.

---

MIT-licensed. Built on the Claude Agent platform.
