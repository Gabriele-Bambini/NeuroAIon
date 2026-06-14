"""The conductor: drives the eight agents through the full PRISMA 2020 pipeline."""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import config
from .agents import (DataExtractor, DeduplicationAgent, DualScreenAdjudicator,
                     EvidenceSynthesizer, FullTextEligibility, PRISMAReporter,
                     ProtocolArchitect, RiskOfBiasAssessor, SearchStrategist,
                     TitleAbstractScreener)
from .llm import build_provider, get_provider
from .models import Decision, Record, ReviewState
from .prisma import compute_flow
from .report import compile_pdf as _compile_pdf
from .report import write_artifacts, write_latex
from .sources import (FullText, FullTextRetriever, HttpFullTextRetriever,
                      search_source, synthetic_records)
from .stats import cohen_kappa


class Orchestrator:
    def __init__(self, seed: dict, *, mock: bool = False, live_sources: Optional[bool] = None,
                 model: str | None = None, max_workers: int | None = None,
                 fulltext_retriever: Optional[FullTextRetriever] = None,
                 fetch_fulltext: Optional[bool] = None,
                 make_latex: bool = True, compile_pdf: bool = True,
                 make_bundle: bool = True, save_zip: Optional[str] = None,
                 stop_after: Optional[str] = None, from_state: Optional[ReviewState] = None,
                 logger: Optional[Callable[[str], None]] = None):
        self.seed = seed
        self.mock = mock or not config.have_api_key()
        # By default, offline mock runs use synthetic sources; live runs hit real APIs.
        self.live_sources = (not self.mock) if live_sources is None else live_sources
        self.model = model or config.DEFAULT_MODEL
        self.max_workers = max_workers or config.MAX_WORKERS
        self.provider = get_provider(self.mock, self.model)
        # A cheaper, high-throughput provider can drive screening (e.g. DeepSeek)
        # while the default provider handles redaction.
        self.screen_provider = self.provider
        if not self.mock and config.SCREEN_PROVIDER:
            self.screen_provider = build_provider(config.SCREEN_PROVIDER,
                                                  config.SCREEN_MODEL or None)
        self.stop_after = stop_after
        self.from_state = from_state
        self._log_fn = logger or (lambda m: print(m, file=sys.stderr, flush=True))

        # Full-text retrieval (PRISMA "reports sought / retrieved"). On a host with
        # open egress this hits PMC/Europe PMC directly; an MCP host can inject an
        # McpFullTextRetriever. Skipped for offline/mock runs (synthetic corpus).
        self.fetch_fulltext = self.live_sources if fetch_fulltext is None else fetch_fulltext
        if fulltext_retriever is not None:
            self.retriever: Optional[FullTextRetriever] = fulltext_retriever
        elif self.fetch_fulltext:
            self.retriever = HttpFullTextRetriever()
        else:
            self.retriever = None
        self._fulltext: dict[str, FullText] = {}

        # LaTeX paper generation + optional local PDF compilation.
        self.make_latex = make_latex
        self.want_pdf = compile_pdf
        # Local-save: bundle every artefact into a zip, optionally copied to a path.
        self.make_bundle = make_bundle
        self.save_zip = save_zip

    def log(self, msg: str, state: ReviewState | None = None) -> None:
        self._log_fn(msg)
        if state is not None:
            state.log.append(msg)

    # ── Pipeline ─────────────────────────────────────────────────────────────
    def run(self, out_root: str | Path = "runs") -> ReviewState:
        # Resume mode: a prior screening checkpoint was supplied — pick up at
        # eligibility (the "redaction" half), typically with a premium provider.
        if self.from_state is not None:
            state = self.from_state
            out_dir = Path(out_root) / (state.run_id + "-writeup")
            self.log(f"Resuming from checkpoint: {len(state.included_after_screening)} "
                     f"screened-in records → write-up.", state)
            return self._finish(state, out_dir, state.protocol)

        run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        out_dir = Path(out_root) / run_id

        # Agent 1 — protocol
        self._log_fn(f"[1/8] ProtocolArchitect · building protocol …")
        protocol = ProtocolArchitect(self.provider, self.seed_protocol_stub()).build(self.seed)
        state = ReviewState(run_id=run_id, mock=self.mock,
                            model=("mock" if self.mock else self.model), protocol=protocol)
        self.log(f"Protocol: “{protocol.title}”. Question: {protocol.question}", state)

        # Agent 2 — search strategy + identification
        self.log("[2/8] SearchStrategist · search, identify & de-duplicate …", state)
        strategist = SearchStrategist(self.provider, protocol)
        state.strategy = strategist.design()
        state.records = self._identify(state)
        self.log(f"Identified {len(state.records)} records across "
                 f"{len(protocol.search.sources)} sources.", state)
        self._checkpoint(out_dir, state)

        # Agent 3 — deduplication
        self.log("      · de-duplication …", state)
        state.unique_records, removed = DeduplicationAgent(self.provider, protocol).run(state.records)
        self.log(f"{removed} duplicates removed → {len(state.unique_records)} unique records.", state)

        # Agents 4 & 5 — dual screening + adjudication
        self.log("[3/8] TitleAbstractScreener · dual independent screening + κ …", state)
        self._screen(state)
        self.log(f"Cohen's κ = {state.cohen_kappa}. "
                 f"{len(state.included_after_screening)} records retained for full text.", state)
        self._checkpoint(out_dir, state)

        # Handoff: stop after screening so a different "brain" (premium model, or
        # Claude in cowork) performs the redaction half from this checkpoint.
        if self.stop_after == "screen":
            self._write_handoff(out_dir, state)
            self.log(f"⏸ Stopped after screening. {len(state.included_after_screening)} "
                     f"records exported → {out_dir / 'screening_handoff.json'} "
                     f"(resume with --from-state).", state)
            return state

        return self._finish(state, out_dir, protocol)

    def _finish(self, state: ReviewState, out_dir: Path, protocol) -> ReviewState:
        out_dir.mkdir(parents=True, exist_ok=True)
        # Agent 6 — full-text retrieval + eligibility
        if self.retriever is not None:
            self.log("[4/8] EligibilityAdjudicator · retrieving reports (PMC / Europe PMC) …", state)
            self._retrieve_fulltexts(state)
            got = sum(1 for ft in self._fulltext.values() if ft.retrieved)
            self.log(f"Full text retrieved for {got}/{len(self._fulltext)} reports "
                     f"(remainder assessed from abstract).", state)
        else:
            self.log("[4/8] EligibilityAdjudicator · adjudicating & assessing reports …", state)
        self._eligibility(state)
        self.log(f"{len(state.included_studies)} studies eligible for inclusion.", state)

        # Agents 7 & 8 — extraction + risk of bias
        self.log("[5-6/8] DataExtractor & RiskOfBiasAssessor · on included studies …", state)
        self._extract_and_appraise(state)
        self._checkpoint(out_dir, state)

        # Agent 9 — synthesis
        self.log("[7/8] EvidenceSynthesizer · synthesis, meta-analysis & publication bias …", state)
        state.synthesis = EvidenceSynthesizer(self.provider, protocol).synthesize(
            state.extractions, state.rob)
        if state.synthesis.meta_analysis:
            m = state.synthesis.meta_analysis
            self.log(f"Meta-analysis: pooled {m.measure}={m.pooled_estimate} "
                     f"[{m.ci_lower},{m.ci_upper}], I²={m.i_squared}%, k={m.k_studies}.", state)

        # PRISMA flow + Agent 10 — reporting
        state.prisma = compute_flow(state)
        self.log("[8/8] PRISMAReporter · manuscript, figures, PDF/LaTeX/PROSPERO …", state)
        prose = PRISMAReporter(self.provider, protocol).write_prose(state)
        report_path = write_artifacts(out_dir, state, prose)

        if self.make_latex:
            tex_path = write_latex(out_dir, state, prose)
            self.log(f"LaTeX paper written: {tex_path}", state)
            if self.want_pdf:
                pdf = _compile_pdf(tex_path)
                if pdf:
                    self.log(f"✓ Compiled PDF: {pdf}", state)
                else:
                    self.log("PDF not compiled locally (no TeX engine); "
                             "compile paper.tex with `latexmk -pdf` or use the CI workflow.",
                             state)

        self.log(f"✓ Review complete. Report: {report_path}", state)
        # Final checkpoint with the populated log.
        (out_dir / "state.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")

        # Provenance + integrity manifest (SHA-256 of every artefact) — written
        # last so it hashes the full dossier, then the bundle.
        from . import audit
        manifest = audit.write_manifest(out_dir, state)
        self.log(f"🔏 Provenance manifest (sha256): {manifest}", state)

        # Local-save: portable zip bundle of every artefact.
        if self.make_bundle:
            from .report import bundle_run, save_locally
            z = bundle_run(out_dir)
            self.log(f"📦 Bundle saved: {z}", state)
            if self.save_zip:
                dest = save_locally(out_dir, self.save_zip)
                self.log(f"💾 Saved locally to: {dest}", state)
        return state

    # ── Phase helpers ────────────────────────────────────────────────────────
    def seed_protocol_stub(self):
        from .models import ReviewProtocol
        return ReviewProtocol(title=self.seed.get("title", ""))

    def _identify(self, state: ReviewState) -> list[Record]:
        records: list[Record] = []
        cap = state.protocol.search.max_records_per_source
        for q in state.strategy.queries:
            if self.live_sources:
                got = search_source(q.source, q.query, retmax=cap)
            else:
                got = synthetic_records(q.source, q.query, n=min(cap, 30))
            self._log_fn(f"   · {q.source}: {len(got)} records")
            records.extend(got[:cap])
        return records

    def _screen(self, state: ReviewState) -> None:
        screener = TitleAbstractScreener(self.screen_provider, state.protocol)
        adjudicator = DualScreenAdjudicator(self.screen_provider, state.protocol)
        records = state.unique_records

        def dual(rec: Record):
            d1 = screener.screen_one(rec, "reviewer_1")
            d2 = screener.screen_one(rec, "reviewer_2")
            final = adjudicator.resolve(rec, d1, d2)
            return rec.uid, d1, d2, final

        r1_seq, r2_seq = [], []
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            for uid, d1, d2, final in ex.map(dual, records):
                state.screening.extend([d1, d2, final])
                r1_seq.append(d1.decision.value)
                r2_seq.append(d2.decision.value)
                if final.decision == Decision.INCLUDE:
                    state.included_after_screening.append(uid)
        state.cohen_kappa = cohen_kappa(r1_seq, r2_seq)

    def _retrieve_fulltexts(self, state: ReviewState) -> None:
        by_uid = {r.uid: r for r in state.unique_records}
        targets = [by_uid[u] for u in state.included_after_screening if u in by_uid]

        def fetch(rec: Record):
            try:
                return rec.uid, self.retriever.retrieve(rec)
            except Exception:  # noqa: BLE001
                return rec.uid, FullText(text=rec.abstract, retrieved=False, source="abstract")

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            for uid, ft in ex.map(fetch, targets):
                self._fulltext[uid] = ft

    def _text_for(self, uid: str, fallback: str = "") -> str:
        ft = self._fulltext.get(uid)
        return ft.text if ft and ft.text else fallback

    def _eligibility(self, state: ReviewState) -> None:
        fulltext = FullTextEligibility(self.provider, state.protocol)
        by_uid = {r.uid: r for r in state.unique_records}
        targets = [by_uid[u] for u in state.included_after_screening if u in by_uid]

        def assess(rec: Record):
            decision = fulltext.assess(rec, full_text=self._text_for(rec.uid))
            ft = self._fulltext.get(rec.uid)
            if ft is not None:
                # Record the provenance/quality of the report we assessed.
                decision.full_text_retrieved = ft.retrieved or bool(ft.text)
                if ft.source and ft.source != "none":
                    decision.notes = (decision.notes + f" [source: {ft.source}"
                                      + (f"/{ft.pmcid}" if ft.pmcid else "") + "]").strip()
            return decision

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            for decision in ex.map(assess, targets):
                state.eligibility.append(decision)
                if decision.eligible:
                    state.included_studies.append(decision.uid)

    def _extract_and_appraise(self, state: ReviewState) -> None:
        extractor = DataExtractor(self.provider, state.protocol)
        appraiser = RiskOfBiasAssessor(self.provider, state.protocol)
        by_uid = {r.uid: r for r in state.unique_records}
        targets = [by_uid[u] for u in state.included_studies if u in by_uid]

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            extractions = list(ex.map(
                lambda rec: extractor.extract(rec, full_text=self._text_for(rec.uid)), targets))
        state.extractions = extractions
        ex_by_uid = {e.uid: e for e in extractions}

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            robs = list(ex.map(
                lambda rec: appraiser.assess(rec, ex_by_uid[rec.uid],
                                             full_text=self._text_for(rec.uid)), targets))
        state.rob = robs

    def _checkpoint(self, out_dir: Path, state: ReviewState) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "state.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")

    def _write_handoff(self, out_dir: Path, state: ReviewState) -> None:
        """Export the screened-in records for the redaction half (cowork or resume)."""
        import json
        out_dir.mkdir(parents=True, exist_ok=True)
        by_uid = {r.uid: r for r in state.unique_records}
        payload = [
            {"uid": u, "title": by_uid[u].title, "abstract": by_uid[u].abstract,
             "doi": by_uid[u].doi, "url": by_uid[u].url, "source": by_uid[u].source,
             "source_id": by_uid[u].source_id, "year": by_uid[u].year}
            for u in state.included_after_screening if u in by_uid
        ]
        (out_dir / "screening_handoff.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8")
        self._checkpoint(out_dir, state)
