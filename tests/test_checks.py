"""Runtime self-audit: PRISMA ledger balance, grounding, corpus numbering."""
from neuroaion.checks import (
    assign_citation_numbers,
    check_grounding,
    check_prisma_ledger,
    run_integrity,
)
from neuroaion.models import (
    EffectEstimate,
    ExtractionRecord,
    MetaAnalysisResult,
    PrismaFlow,
    Record,
    ReviewProtocol,
    ReviewState,
    Synthesis,
)


def _balanced_flow():
    # 100 identified → 20 dups → 80 screened → 60 excluded, 20 sought →
    # 2 not-retrieved, 18 assessed → 8 excluded, 10 included.
    return PrismaFlow(
        records_total=100, records_from_databases=100, records_from_registers=0,
        duplicates_removed=20, records_screened=80, records_excluded_screening=60,
        reports_sought=20, reports_not_retrieved=2, reports_assessed=18,
        reports_excluded={"Wrong population": 5, "Wrong design": 3},
        studies_included=10, reports_of_included=10)


def test_ledger_balances_when_consistent():
    st = ReviewState(run_id="t", protocol=ReviewProtocol(title="T"))
    st.prisma = _balanced_flow()
    checks = check_prisma_ledger(st)
    assert all(c["ok"] for c in checks)


def test_ledger_catches_a_missing_record():
    st = ReviewState(run_id="t", protocol=ReviewProtocol(title="T"))
    f = _balanced_flow()
    f.studies_included = 11          # one study appears from nowhere
    st.prisma = f
    checks = check_prisma_ledger(st)
    bad = [c for c in checks if not c["ok"]]
    assert bad and bad[0]["check"] == "eligibility_balance"


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
        forest=[{"study": "a"}, {"study": "b"}]))
    assign_citation_numbers(st)
    report = run_integrity(st)
    assert report["passed"] and report["n_failures"] == 0
