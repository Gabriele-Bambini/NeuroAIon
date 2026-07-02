"""Runtime self-audit: PRISMA ledger balance, grounding, corpus numbering."""
from neuroaion.checks import (
    assign_citation_numbers,
    check_grounding,
    check_prisma_ledger,
    run_integrity,
)
from neuroaion.models import (
    EffectEstimate,
    EligibilityDecision,
    ExtractionRecord,
    MetaAnalysisResult,
    PrismaFlow,
    Record,
    ReviewProtocol,
    ReviewState,
    ScreeningDecision,
    Synthesis,
)
from neuroaion.prisma import compute_flow


def _consistent_state():
    """A fully-consistent state whose PRISMA flow is derived from its own lists.

    100 identified (20 duplicates) → 80 unique/screened → 20 screened-in → 18
    reports assessed (2 not retrieved) → 8 excluded with reasons → 10 included.
    """
    records = [Record(source="pubmed", doi=f"10/a{i}", title=f"Study {i}") for i in range(100)]
    # 20 of them are exact duplicates (share a DOI) so dedup removes 20.
    for i in range(80, 100):
        records[i].doi = records[i - 80].doi
    st = ReviewState(run_id="t", protocol=ReviewProtocol(title="T"))
    st.records = records
    from neuroaion.dedup import deduplicate
    st.unique_records, _ = deduplicate(records)
    uids = [r.uid for r in st.unique_records]           # 80 unique
    st.included_after_screening = uids[:20]
    # 18 assessed (full text), 2 not retrieved; of the 18, 8 excluded, 10 included.
    st.eligibility = []
    for j, u in enumerate(uids[:20]):
        retrieved = j < 18
        eligible = 8 <= j < 18            # 10 eligible, 8 assessed-and-excluded
        st.eligibility.append(EligibilityDecision(
            uid=u, eligible=eligible, full_text_retrieved=retrieved,
            exclusion_reason="" if eligible else "Wrong population"))
    st.included_studies = [e.uid for e in st.eligibility if e.eligible]
    st.prisma = compute_flow(st)
    return st


def test_ledger_balances_when_consistent():
    st = _consistent_state()
    checks = check_prisma_ledger(st)
    assert all(c["ok"] for c in checks), [c for c in checks if not c["ok"]]
    # The independent cross-checks actually ran (not just the tautological ones).
    names = {c["check"] for c in checks}
    assert "included_matches_included_studies" in names


def test_ledger_independent_check_catches_flow_divergence():
    st = _consistent_state()
    st.prisma.studies_included += 1        # flow diagram claims one extra study
    checks = {c["check"]: c for c in check_prisma_ledger(st)}
    # The independent cross-check against the actual included list fails.
    assert not checks["included_matches_included_studies"]["ok"]


def test_citation_numbering_is_alphabetical_and_stable():
    a = Record(source="s", doi="10/a", title="Zeta study", authors=["Young B"], year=2020)
    b = Record(source="s", doi="10/b", title="Alpha study", authors=["Adams C"], year=2019)
    c = Record(source="s", doi="10/c", title="Mid study", authors=["Adams C"], year=2021)
    st = ReviewState(run_id="t", protocol=ReviewProtocol(title="T"))
    st.unique_records = [a, b, c]
    st.included_studies = [a.uid, b.uid, c.uid]
    nums = assign_citation_numbers(st)
    # Adams 2019 = 1, Adams 2021 = 2, Young 2020 = 3
    assert nums[b.uid] == 1 and nums[c.uid] == 2 and nums[a.uid] == 3
    assert assign_citation_numbers(st) == nums          # idempotent


def test_grounding_flags_unextracted_and_uncitable():
    ok = Record(source="pubmed", doi="10/x", title="Extracted", authors=["Rossi A"], year=2020)
    bad = Record(source="snowball", title="No id no extraction", authors=["Bianchi B"], year=2021)
    st = ReviewState(run_id="t", protocol=ReviewProtocol(title="T"))
    st.unique_records = [ok, bad]
    st.included_studies = [ok.uid, bad.uid]
    st.extractions = [ExtractionRecord(uid=ok.uid, study_label="Rossi 2020")]
    assign_citation_numbers(st)
    checks = {c["check"]: c for c in check_grounding(st)}
    assert not checks["every_included_study_extracted"]["ok"]
    assert not checks["every_included_study_citable"]["ok"]


def test_run_integrity_passes_on_clean_state():
    ok = Record(source="pubmed", doi="10/x", title="Extracted", authors=["Rossi A"], year=2020)
    ok2 = Record(source="pubmed", doi="10/y", title="Extracted 2", authors=["Bianchi B"], year=2021)
    st = ReviewState(run_id="t", protocol=ReviewProtocol(title="T"))
    st.records = [ok, ok2]
    st.unique_records = [ok, ok2]
    st.included_after_screening = [ok.uid, ok2.uid]
    st.eligibility = [EligibilityDecision(uid=ok.uid, eligible=True, full_text_retrieved=True),
                      EligibilityDecision(uid=ok2.uid, eligible=True, full_text_retrieved=True)]
    st.included_studies = [ok.uid, ok2.uid]
    st.extractions = [ExtractionRecord(uid=ok.uid, study_label="Rossi 2020"),
                      ExtractionRecord(uid=ok2.uid, study_label="Bianchi 2021")]
    st.prisma = compute_flow(st)
    st.synthesis = Synthesis(meta_analysis=MetaAnalysisResult(
        measure="RR", k_studies=2, ci_lower=1.0, ci_upper=1.5,
        forest=[{"study": "Rossi 2020"}, {"study": "Bianchi 2021"}]))
    assign_citation_numbers(st)
    report = run_integrity(st)
    assert report["passed"] and report["n_failures"] == 0


def test_grounding_flags_forest_study_outside_corpus():
    ok = Record(source="pubmed", doi="10/x", title="In corpus", authors=["Rossi A"], year=2020)
    st = ReviewState(run_id="t", protocol=ReviewProtocol(title="T"))
    st.unique_records = [ok]
    st.included_studies = [ok.uid]
    st.extractions = [ExtractionRecord(uid=ok.uid, study_label="Rossi 2020")]
    st.prisma = PrismaFlow(records_total=1, records_from_databases=1, duplicates_removed=0,
                           records_screened=1, records_excluded_screening=0,
                           reports_sought=1, reports_not_retrieved=0, reports_assessed=1,
                           reports_excluded={}, studies_included=1, reports_of_included=1)
    st.synthesis = Synthesis(meta_analysis=MetaAnalysisResult(
        measure="RR", k_studies=2, ci_lower=1.0, ci_upper=1.5,
        forest=[{"study": "Rossi 2020"}, {"study": "Ghost 2019"}]))
    assign_citation_numbers(st)
    checks = {c["check"]: c for c in check_grounding(st)}
    assert not checks["meta_analysis[0]_forest_in_corpus"]["ok"]
