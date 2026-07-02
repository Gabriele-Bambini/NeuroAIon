# NeuroAIon — Pre-Mortem & Improvement Roadmap

> **Framing (pre-mortem).** Assume it is 12 months from now and NeuroAIon has *failed*
> to autonomously produce a systematic review + meta-analysis that a Stanford
> biostatistics team would sign. This document enumerates **every reason that
> failure happened** — grounded in the current code (`file:function` evidence) —
> and the concrete solutions to prevent it. Findings were produced by a 10-agent
> audit, one agent per dimension.

**Current state:** ~10.5k LOC, 8-agent pipeline, 12 source connectors, a strong
deterministic `stats.py`, matplotlib/ReportLab/LaTeX renderers, RoB engine, and a
compiled document dossier. **117 tests pass** — but they assert *internal
consistency only*, never numerical correctness. The engine can *look* like it did
a review without actually having done a defensible one.

---

## 0. The three failure modes that matter most

1. **It can fabricate a whole review.** `orchestrator.py:35` `self.mock = mock or not config.have_api_key()` — with no API key the run silently uses `MockProvider`, yet still emits `paper.pdf`, PROSPERO, and a SHA-256 *provenance manifest*. A fake review that looks real. → **fail-closed.**
2. **Its numbers are unproven.** No test pins a pooled estimate, tau^2, I^2, Q, or CI to a known value; `DataExtractor` trusts LLM-returned effect sizes without recomputing from raw data. A sign error or hallucinated 2x2 would pass CI and reach the manuscript. → **metafor-equivalence golden tests + recompute-from-raw + runtime self-checks.**
3. **Its citations aren't guaranteed real or traceable.** Only 3 identifiers are captured; dedup discards the losing record's IDs; an included study can be a title-only hash with no resolvable locator; prose carries no `[n]` back-references. → **full-ID capture, union-find dedup, `verify_citations` gate, KG-grounded citations.**

Everything below expands these into a per-dimension pre-mortem.

---

## 1. Autonomy & orchestration
- **Silent mock fabrication** — `orchestrator.py:35`, `llm.MockProvider`. No hard guard.
- **No self-critique / refinement loop** — every agent is single-shot (`extraction.extract`, `screen_ta.screen_one`, `reporter.write_prose`, `synthesis.synthesize`). The "keep improving until extreme quality" requirement is absent.
- **Long full texts hard-truncated** — `extraction.py:49 body[:8000]` while retrieval fetched 40-60k chars; Methods/Results past ~2 pages never read.
- **Errors swallowed into degraded defaults** — `screen_ta.py:42` (MAYBE, conf 0.3), `extraction.py:68`, silent abstract fallback; no failure ledger, so a "complete" run can be silently hollow.
- **Non-deterministic live path** — `llm.py:79` `thinking=adaptive`, no temperature/seed (only OpenAI path pins temperature 0).
- **Coarse resume, no cost cap** — `from_state` resumes only at write-up; no per-record cache, token/$ budget, or global rate-limit.

**Solutions:** fail-closed (`config.require_live()`, opt-in `--allow-mock`); `agents/refine.py::refine_until(fn, validate, max_rounds, threshold)` + `CriticAgent`; token-aware `map_reduce_extract`; `ReviewState.failures` ledger surfaced in the report; `temperature=0`+seed persisted to manifest; content-addressed LLM cache + mid-phase checkpoints; `ratelimit.py` token-bucket + `MAX_USD`.

## 2. PICO formulation (literature-informed refinement)
- **No scoping look at the literature before the PICO is fixed** — `agents/protocol.py:propose_questions/build` are pure LLM calls on the raw topic.
- **Outcomes/effect measure guessed** — `SynthesisConfig.effect_measure` defaults SMD; wizard menu fixed SMD/MD/OR/RR/HR (no AUROC/AUPRC/c-index).
- **Keywords not derived** — `SearchConfig.keywords` defaults `[]`; a topic-only run searches an empty Boolean string.
- Framework auto-selection unprincipled; eligibility/PROSPERO from the un-refined PICO; connectors don't parse `cited_by_count`/`citationCount`.

**Solutions:** `agents/scoping.py::ScopingAgent.scope(topic, k=25)` over OpenAlex/Semantic Scholar/PubMed by citations+recency -> `ScopingBrief{candidate_framework, primary/secondary_outcomes, standard_measure, typical_designs, key_concepts, exemplar_dois}`; `ProtocolArchitect.refine(seed, brief)`; rule-mapped framework (intervention->PICO(S), exposure->PECO, diagnostic->PIRD/QUADAS-2, prevalence->CoCoPop, prediction->PROBAST, ML-benchmark->PICO+AUROC); `derive_keywords(pico, brief)` with MeSH/Emtree/synonyms; parse citation counts.

## 3. Search & retrieval comprehensiveness
- **No live Scopus / Web of Science / Embase / CENTRAL / ICTRP** — `registry.SOURCES` has 10 free APIs; `translate.py` emits Scopus/WoS/IEEE syntax no source can execute. Missing the databases Cochrane requires (Embase/CENTRAL) -> recall not defensible.
- **Date/language limits dropped** for openalex/crossref/semanticscholar/core/doaj/arxiv/biorxiv/clinicaltrials; `languages` never used.
- **Dedup ignores PMID/PMCID/arXiv** — keys on `doi:` then fuzzy title; `Record` lacks `pmcid`/`arxiv_id`; PubMed leaves `pmid=""`.
- No per-record full-text channel/success tracking; arXiv OA PDFs never fetched.
- **No Excel workbook, no affinity 1-10** — explicit deliverable 100% absent.

**Solutions:** add `pmid/pmcid/arxiv_id/s2_id/openalex_id/registry_id` + `found_by`/`retrieval_date` to `Record`; multi-ID union-find dedup + field-level reconciliation; `sources/scopus.py|wos.py|embase.py` (institutional keys via env); route date/language through every `search()`; `export_xlsx.py::write_workbook` (sheet per source: title, DOI, all IDs, affinity 1-10, metadata); PRISMA-S capture on `DatabaseQuery`.

## 4. Screening (abstract + full text)
- **Pseudo-replication** — two "independent" reviewers are the same model with near-identical prompts (`orchestrator._screen`); Cohen's kappa is inflated and never gated/calibrated.
- **`full_text_retrieved` flag bug** — `orchestrator.py:318 = ft.retrieved or bool(ft.text)`; abstract fallback flips it True -> corrupts PRISMA counts and permits **inclusion from abstract only**.
- **Full text truncated to 6000 chars** at eligibility.
- No 1-10 affinity; free-text exclusion reasons (uncountable for PRISMA 16b); PRISMA "other methods" folded into database counts; non-deterministic single-vote decisions.

**Solutions:** reviewer diversity or k-vote self-consistency + vote-entropy; calibrated `affinity:int` (rubric-anchored) + optional Platt/isotonic on a gold subset; **fix `orchestrator.py:318 -> ft.retrieved`** and block abstract-only inclusion; raise the 6000 cap; `ExclusionReason` Enum; dual full-text + adjudication; `screening_metrics.py` (recall/WSS@95, ranking, stopping rule); split databases/registers/other-methods in `compute_flow`/`mermaid_flow`.

## 5. Data & statistics extraction / parsing
- **`body[:8000]` discards the tables & harvested-stats blocks** (appended after prose in `PdfDocument.as_working_text`) -> extraction is effectively abstract-only.
- **No raw-data schema** — `EffectEstimate` has no 2x2 cells, arm means/SDs, medians/IQR, events/total, r, t/F. The deterministic converters are **never invoked from extraction**; numbers are trusted verbatim from the LLM.
- No verification / dual extraction / reconciliation; no median->mean (Wan 2014 / Luo 2018 / Shi 2020 / Hozo) or SD-from-CI/SE/p; fixed-0.5 continuity only; no cluster/crossover/multi-arm handling; **no page/quote traceability**; brittle tables (PyMuPDF only; GROBID ignores tables).

**Solutions:** extend `EffectEstimate` with raw fields + `source_page/source_quote/computed_from`; `extraction_math.py::from_2x2(correction=...)`, `mean_sd_from_median(method=...)`, `sd_from_ci/se/p`, `cluster_adjust`, `crossover_smd`, `shared_control_split` -> **recompute every effect**; dual extraction + `verify(e)` (recompute SE from CI and from N, flag >5% mismatch; range checks); feed the whole `as_working_text` chunked; Camelot/table-transformer + GROBID table/formula parsing; `harmonize_direction`.

## 6. Meta-analysis methodology (the make-or-break)
**Present & correct:** DL + REML tau^2, HKSJ (t), I^2 CI, prediction interval (t_{k-2}), Egger/Begg/trim-and-fill, contour funnel, leave-one-out, categorical subgroup Q, deterministic GRADE.
**Still not Stanford-inattackable:**
- **Pseudoreplication** — `_pool` treats multiple effects per study as independent; **no RVE (Hedges-Tipton-Johnson) / three-level (Van den Noortgate)** — the single biggest inferential threat.
- **HKSJ missing the Rover ad-hoc SE floor** (`se = max(se, se_wald)`).
- **REML not the documented default**; **no Q-profile tau^2 CI**; **no PM/SJ/EB/ML estimators**.
- **Meta-regression declared but unimplemented** (`metareg`/`moderator` fields exist, no function); no permutation test, R^2, omnibus QM.
- **Sparse binary**: fixed-0.5 only — **no Mantel-Haenszel / Peto / Sweeting / GLMM (Stijnen)**.
- No PET-PEESE, excess-significance (Ioannidis-Trikalinos), Copas/Rucker limit-MA, Baujat/GOSH/Cook's-D influence, cumulative MA (declared, no function).
- **GRADE**: indirectness hard-coded "not serious"; imprecision a crude n<400 rule (no OIS/RIS vs MID).
- **Bug**: Egger test is unweighted OLS but the funnel line is weighted.

**Solutions:** `_tau2(method)` dispatcher (PM/SJ/EB/ML); HKSJ SE floor; `tau2_ci` (Q-profile, Viechtbauer 2007); `meta_regression(X, knha=True)` (WLS+REML, QM, R^2, permutation); `rve_pool(cluster, CR2, Satterthwaite)` / `three_level(study_id)`; `mantel_haenszel/peto_or` + Sweeting + GLMM; `pet_peese`, `excess_significance`, `limit_meta`, `influence`(+Baujat), `cumulative`; GRADE OIS-based imprecision + indirectness hook; reconcile Egger weighting; always report df/exact-p/CI-method.

## 7. Knowledge representation / knowledge graph (greenfield)
- **No alphabetical canonicalization or stable numbering** — `included_studies` in assessment order; `report._references` numbers by that order; LaTeX `unsrtnat`. [n] non-deterministic, can't be "cited before used".
- **No notion/claim/entity extraction** — `ExtractionRecord` has only PICO+effects.
- No provenance at claim/quote/page; **no KG store**; **prose carries no `[n]`**; no contradiction/agreement detection.

**Solutions:** `knowledge_graph.py` (networkx + GraphML/JSON, optional SQLite); `canonicalize_corpus(state)` -> `state.corpus_order` + `state.citation_numbers{uid:[n]}` (sort author,year,title); all renderers read `citation_numbers`; `models.Claim{text, quote, page, paper_uid, cite_num, concepts, polarity}` + claim-extraction pass; typed nodes/edges (asserts/about/reports/supports/contradicts); `kg.cite_str(concepts)->"[3, 7]"`; Reporter writes each sentence from claims only; `kg.detect_relations()` feeds discussion; `kg.cluster_concepts()` seeds intro sub-chapters; export `knowledge_graph.graphml` + `claims.csv`.

## 8. Citation reliability, reproducibility & provenance
- **Only 3 IDs captured; external IDs discarded** — `semanticscholar._parse` keeps only DOI; PubMed drops PMCID/PII; non-DOI IDs crammed into `source_id`.
- **Dedup destroys the losing record's IDs/provenance**; no field-level reconciliation -> volume/issue/pages/`journal_abbrev` empty for all API sources.
- No DOI validation; **author names in 5 formats, never normalized**; lossy citation formatting; no CSL engine/CSL-JSON.
- **Manifest not reproducible** — omits executed queries, retrieval dates, LLM model/temperature/seed, PROSPERO id; `created_at` uses `datetime.utcnow()`.
- **Unverifiable-citation risk** — a title-only included uid can have no resolvable DOI/URL.

**Solutions:** `Record.ids: dict` (+ pmcid/arxiv_id/s2_id/openalex_id/isbn/registry_id), `found_by`, `retrieval_date`; extract all `externalIds`; union-find dedup unioning IDs + field-level reconciliation; `sources/validate.py::resolve_doi` (Crossref) back-fill; `parse_author->{family,given}`; `report.export_csl_json()` + real CSL styling + richer `_bib_entry`; manifest records queries/dates/model/seed, freeze `created_at`; **`verify_citations(state)` gate — every included uid must have >=1 resolvable ID or the run fails.**

## 9. Manuscript generation & journal layout
- **No chaptered theoretical introduction** — `introduction` is one flat string.
- **Prose carries no inline citations**; no guard against invented citations.
- **Only included studies are citable** — background `unique_records` never becomes references -> grounded intro impossible.
- **Multi-outcome results text-only** — renderers show only primary `meta_analysis`, never `meta_analyses`.
- Subgroup/sensitivity never rendered; **GRADE SoF table missing from the paper**; no MOOSE; LaTeX single-column; no Excel/affinity; whole manuscript in one 16k-token call.

**Solutions:** `write_introduction(state)->list[IntroChapter{title, subsections[{heading, body, cite_uids}]}]` grounded in KG clusters (cite_uids from allowed UIDs only); bibliography for **all** cited `unique_records`; post-validate every `[n]`/`\cite`; loop `meta_analyses` everywhere; `build_subgroup_forest`/`build_loo_figure` + in-paper SoF longtable + `MOOSE_CHECKLIST`; section-wise generation; `workbook.py` xlsx; LaTeX two-column house style.

## 10. QA, validation & reproducibility harness
- **No gold-standard numeric validation** — tests assert only ranges/labels/`PI superset CI`; a sign error passes CI silently.
- No metafor/RevMan equivalence; conversions & kappa unvalidated; publication-bias math untested.
- **No runtime self-validation** — PRISMA ledger never asserted; pooled effect never recomputed two ways; citations/numbers never checked to resolve.
- **Reproducibility unmet** — floating deps, no lockfile, no seed capture; CI compiles LaTeX only on dispatch, no numeric gate, no figure regression.

**Solutions (exact targets):**
- `tests/test_metafor_golden.py` (`pytest.approx(abs=1e-3)`): on **`dat.bcg`** (Colditz 1994, k=13, RR random DL) assert pooled **logRR ~= -0.7141**, CI ~= **[-1.067, -0.361]**, **tau^2 ~= 0.3088**, **I^2 ~= 92.1%**, **Q(12) ~= 152.23**; REML **tau^2 ~= 0.313**. Add `dat.normand1999` (SMD/MD), `dat.molloy2014` (ZCOR).
- `escalc`-equivalence for `hedges_g/log_or/fisher_z/mean_difference`; kappa vs `sklearn.cohen_kappa_score`; Egger `regtest` + `trimfill` on `dat.bcg`.
- Runtime self-checks: PRISMA count-ledger balance; recompute-pooled-two-ways ~=; `verify_grounding()` (every numeric token & citation key resolves).
- Pin deps (hash-locked lockfile), tests on push/PR, compile LaTeX every run, figure-regression + numeric-determinism test.

---

## Consolidated roadmap

### P0 - blocks a complete, trustworthy review
1. **Fail-closed autonomy** — raise on missing key unless `--allow-mock`.
2. **Citation integrity spine** — `Record.ids` full capture -> union-find multi-ID dedup -> `verify_citations` gate.
3. **Extraction recompute-from-raw** — raw-data fields + `extraction_math.py`; fix `body[:8000]`.
4. **Fix PRISMA/full-text bug** — `orchestrator.py:318 -> ft.retrieved`; block abstract-only inclusion; raise 6000 cap.
5. **Meta-analysis inferential integrity** — RVE/three-level; HKSJ SE floor; REML default; meta-regression; Q-profile tau^2 CI.
6. **metafor-equivalence golden tests + runtime self-checks**.
7. **Corpus canonicalization + numbering** — alphabetical `citation_numbers` used by all renderers.
8. **Scoping-informed PICO** — `ScopingAgent` + `refine()` + `derive_keywords()`.
9. **Excel-per-source workbook + affinity 1-10**.

### P1 - reviewer-grade quality
Self-critique/refinement loop; chunked long-text reading; determinism (temp/seed + provenance); reviewer diversity/self-consistency + calibrated affinity + controlled exclusion vocab + PRISMA other-methods arm; dual extraction + reconciliation + SD imputation + page/quote traceability; PM/SJ, PET-PEESE, excess-significance, influence+Baujat, cumulative MA, MH/Peto+Sweeting, GRADE OIS; `models.Claim` + `knowledge_graph.py` + KG-grounded fully-cited prose; DOI validation + metadata reconciliation + author normalization + manifest reproducibility; chaptered intro + in-paper SoF/subgroup/sensitivity + all-outcome loops; dependency pinning + CI on push/PR + determinism test; live Embase/CENTRAL/Scopus/WoS via institutional keys.

### P2 - depth, polish, completeness
EB/ML estimators, Copas/Rucker limit-MA, Mathur-VanderWeele E-value, GOSH, permutation moderator tests, GLMM; per-record LLM cache + auto-resume; MeSH/Emtree explosion + PRISMA-S table + publisher-TDM/grey-literature; Camelot/table-transformer + GROBID tables/formulae; MOOSE checklist; LaTeX two-column; CSL-JSON export; figure-regression + coverage threshold + always-compile-LaTeX in CI; SQLite KG mirror + uncited-sentence coverage check.
