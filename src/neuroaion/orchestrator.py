"""The conductor: drives the ten agents through the full PRISMA 2020 pipeline."""
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
from .llm import get_provider
from .models import Decision, Record, ReviewState
from .prisma import compute_flow
from .report import write_artifacts
from .sources import search_source, synthetic_records
from .stats import cohen_kappa


class Orchestrator:
    def __init__(self, seed: dict, *, mock: bool = False, live_sources: Optional[bool] = None,
                 model: str | None = None, max_workers: int | None = None,
                 logger: Optional[Callable[[str], None]] = None):
        self.seed = seed
        self.mock = mock or not config.have_api_key()
        # By default, offline mock runs use synthetic sources; live runs hit real APIs.
        self.live_sources = (not self.mock) if live_sources is None else live_sources
        self.model = model or config.DEFAULT_MODEL
        self.max_workers = max_workers or config.MAX_WORKERS
        self.provider = get_provider(self.mock, self.model)
        self._log_fn = logger or (lambda m: print(m, file=sys.stderr, flush=True))

    def log(self, msg: str, state: ReviewState | None = None) -> None:
        self._log_fn(msg)
        if state is not None:
            state.log.append(msg)

    # ── Pipeline ─────────────────────────────────────────────────────────────
    def run(self, out_root: str | Path = "runs") -> ReviewState:
        run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        out_dir = Path(out_root) / run_id

        # Agent 1 — protocol
        self._log_fn(f"[1/10] ProtocolArchitect · building protocol …")
        protocol = ProtocolArchitect(self.provider, self.seed_protocol_stub()).build(self.seed)
        state = ReviewState(run_id=run_id, mock=self.mock,
                            model=("mock" if self.mock else self.model), protocol=protocol)
        self.log(f"Protocol: “{protocol.title}”. Question: {protocol.question}", state)

        # Agent 2 — search strategy + identification
        self.log("[2/10] SearchStrategist · designing queries & searching …", state)
        strategist = SearchStrategist(self.provider, protocol)
        state.strategy = strategist.design()
        state.records = self._identify(state)
        self.log(f"Identified {len(state.records)} records across "
                 f"{len(protocol.search.sources)} sources.", state)
        self._checkpoint(out_dir, state)

        # Agent 3 — deduplication
        self.log("[3/10] DeduplicationAgent · removing duplicates …", state)
        state.unique_records, removed = DeduplicationAgent(self.provider, protocol).run(state.records)
        self.log(f"{removed} duplicates removed → {len(state.unique_records)} unique records.", state)

        # Agents 4 & 5 — dual screening + adjudication
        self.log("[4-5/10] Dual screening (Reviewer 1 + Reviewer 2) & adjudication …", state)
        self._screen(state)
        self.log(f"Cohen's κ = {state.cohen_kappa}. "
                 f"{len(state.included_after_screening)} records retained for full text.", state)
        self._checkpoint(out_dir, state)

        # Agent 6 — full-text eligibility
        self.log("[6/10] FullTextEligibility · assessing full texts …", state)
        self._eligibility(state)
        self.log(f"{len(state.included_studies)} studies eligible for inclusion.", state)

        # Agents 7 & 8 — extraction + risk of bias
        self.log("[7-8/10] DataExtractor & RiskOfBiasAssessor · on included studies …", state)
        self._extract_and_appraise(state)
        self._checkpoint(out_dir, state)

        # Agent 9 — synthesis
        self.log("[9/10] EvidenceSynthesizer · qualitative + quantitative synthesis …", state)
        state.synthesis = EvidenceSynthesizer(self.provider, protocol).synthesize(
            state.extractions, state.rob)
        if state.synthesis.meta_analysis:
            m = state.synthesis.meta_analysis
            self.log(f"Meta-analysis: pooled {m.measure}={m.pooled_estimate} "
                     f"[{m.ci_lower},{m.ci_upper}], I²={m.i_squared}%, k={m.k_studies}.", state)

        # PRISMA flow + Agent 10 — reporting
        state.prisma = compute_flow(state)
        self.log("[10/10] PRISMAReporter · writing manuscript, flow diagram & checklist …", state)
        prose = PRISMAReporter(self.provider, protocol).write_prose(state)
        report_path = write_artifacts(out_dir, state, prose)
        self.log(f"✓ Review complete. Report: {report_path}", state)
        # Final checkpoint with the populated log.
        (out_dir / "state.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")
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
        screener = TitleAbstractScreener(self.provider, state.protocol)
        adjudicator = DualScreenAdjudicator(self.provider, state.protocol)
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

    def _eligibility(self, state: ReviewState) -> None:
        fulltext = FullTextEligibility(self.provider, state.protocol)
        by_uid = {r.uid: r for r in state.unique_records}
        targets = [by_uid[u] for u in state.included_after_screening if u in by_uid]

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(fulltext.assess, rec): rec for rec in targets}
            for fut in as_completed(futures):
                decision = fut.result()
                state.eligibility.append(decision)
                if decision.eligible:
                    state.included_studies.append(decision.uid)

    def _extract_and_appraise(self, state: ReviewState) -> None:
        extractor = DataExtractor(self.provider, state.protocol)
        appraiser = RiskOfBiasAssessor(self.provider, state.protocol)
        by_uid = {r.uid: r for r in state.unique_records}
        targets = [by_uid[u] for u in state.included_studies if u in by_uid]

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            extractions = list(ex.map(lambda rec: extractor.extract(rec), targets))
        state.extractions = extractions
        ex_by_uid = {e.uid: e for e in extractions}

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            robs = list(ex.map(
                lambda rec: appraiser.assess(rec, ex_by_uid[rec.uid]), targets))
        state.rob = robs

    def _checkpoint(self, out_dir: Path, state: ReviewState) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "state.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")
