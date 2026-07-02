"""Identifier-aware de-duplication + the citation-integrity gate."""
from neuroaion.dedup import deduplicate
from neuroaion.models import Record, ReviewProtocol, ReviewState
from neuroaion.report import verify_citations


def test_merge_by_shared_pmid_without_doi():
    a = Record(source="pubmed", pmid="12345", title="A trial of X", authors=["Rossi A"])
    b = Record(source="crossref", doi="10.1/x", ids={"pmid": "12345"},
               title="A trial of X", journal="Gut", volume="10")
    unique, removed = deduplicate([a, b])
    assert removed == 1 and len(unique) == 1
    m = unique[0]
    # All identifiers unioned; both sources recorded; metadata reconciled.
    assert m.all_ids().get("pmid") == "12345" and m.all_ids().get("doi") == "10.1/x"
    assert set(m.found_by) == {"pubmed", "crossref"}
    assert m.journal == "Gut" and m.volume == "10"


def test_no_false_merge_distinct_ids():
    a = Record(source="pubmed", doi="10.1/a", title="Study A")
    b = Record(source="pubmed", doi="10.1/b", title="Study B")
    unique, removed = deduplicate([a, b])
    assert removed == 0 and len(unique) == 2


def test_fuzzy_title_merge_only_without_ids():
    a = Record(source="s1", title="Deep learning for polyp detection in colonoscopy")
    b = Record(source="s2", title="Deep learning for polyp detection in colonoscopy.")
    unique, removed = deduplicate([a, b])
    assert removed == 1 and len(unique) == 1


def test_verify_citations_flags_unresolvable():
    r_ok = Record(source="pubmed", doi="10.1/x", title="OK")
    r_bad = Record(source="snowball", title="Title only, no id, no url")
    st = ReviewState(run_id="t", protocol=ReviewProtocol(title="T"))
    st.unique_records = [r_ok, r_bad]
    st.included_studies = [r_ok.uid, r_bad.uid]
    unresolved = verify_citations(st)
    assert unresolved == [r_bad.uid]
    assert r_ok.has_resolvable_id() and not r_bad.has_resolvable_id()


def test_no_false_merge_of_distinct_idless_studies():
    # Two DIFFERENT trials, one word apart, no identifiers, different first author.
    a = Record(source="s1", title="Drug X for major depression: a randomized trial",
               authors=["Rossi A"], year=2019)
    b = Record(source="s2", title="Drug Y for major depression: a randomized trial",
               authors=["Bianchi B"], year=2021)
    unique, removed = deduplicate([a, b])
    assert removed == 0 and len(unique) == 2


def test_high_similarity_plus_same_year_and_author_merges():
    a = Record(source="s1", title="CADe for adenoma detection in colonoscopy",
               authors=["Rossi A"], year=2020)
    b = Record(source="s2", title="CADe for adenoma detection at colonoscopy",
               authors=["Rossi A"], year=2020)
    unique, removed = deduplicate([a, b])
    assert removed == 1 and len(unique) == 1
