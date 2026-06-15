"""Offline tests for citation snowballing (network monkeypatched)."""
from neuroaion.models import Record
from neuroaion.sources import snowball


class _Resp:
    """Minimal stand-in for requests.Response."""
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _inverted(text: str) -> dict:
    """Build an OpenAlex abstract_inverted_index from plain text."""
    idx: dict[str, list[int]] = {}
    for i, w in enumerate(text.split()):
        idx.setdefault(w, []).append(i)
    return idx


# ── canned OpenAlex objects ──────────────────────────────────────────────────
SEED_WORK = {
    "id": "https://openalex.org/W100",
    "doi": "https://doi.org/10.1/seed",
    "title": "Seed Study",
    "referenced_works": ["https://openalex.org/W200", "https://openalex.org/W201"],
}

REF_BATCH = {
    "results": [
        {"id": "https://openalex.org/W200", "doi": "https://doi.org/10.2/ref-a",
         "title": "Reference A", "publication_year": 2019,
         "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
         "abstract_inverted_index": _inverted("we benchmark a method"),
         "primary_location": {"source": {"display_name": "Journal X"}}},
        {"id": "https://openalex.org/W201", "doi": "https://doi.org/10.2/ref-b",
         "title": "Reference B", "publication_year": 2020,
         "authorships": [{"author": {"display_name": "Alan Turing"}}]},
    ]
}

CITES_RESULTS = {
    "results": [
        {"id": "https://openalex.org/W300", "doi": "https://doi.org/10.3/cite-a",
         "title": "Citing Paper A", "publication_year": 2022},
        {"id": "https://openalex.org/W301", "doi": "https://doi.org/10.3/cite-b",
         "title": "Citing Paper B", "publication_year": 2023},
    ]
}

CROSSREF_WORK = {
    "message": {
        "reference": [
            {"DOI": "10.4/cr-a", "article-title": "CR Ref A",
             "author": "Hopper", "year": "2018"},
            {"DOI": "10.4/cr-b", "unstructured": "Some unstructured ref, 2017"},
            {"key": "no-doi-no-title"},  # dropped: no doi and no title
        ]
    }
}


def _dispatcher(url: str, params=None, **kw):
    """Route a faked http_get call to the right canned payload."""
    params = params or {}
    flt = params.get("filter", "")
    if url.startswith("https://api.openalex.org/works/"):
        return _Resp(SEED_WORK)                       # single-work resolve
    if url == snowball.OA_WORKS and flt.startswith("openalex_id:"):
        return _Resp(REF_BATCH)                       # batch reference fetch
    if url == snowball.OA_WORKS and flt.startswith("cites:"):
        return _Resp(CITES_RESULTS)                   # forward cited-by
    if url.startswith("https://api.crossref.org/works/"):
        return _Resp(CROSSREF_WORK)
    raise AssertionError(f"unexpected url={url} params={params}")


# ── backward / forward / crossref ────────────────────────────────────────────
def test_references_openalex_offline(monkeypatch):
    monkeypatch.setattr(snowball, "http_get", _dispatcher)
    recs = snowball.references_openalex("10.1/seed")
    assert len(recs) == 2
    assert all(r.source == "snowball:backward" for r in recs)
    a = next(r for r in recs if r.title == "Reference A")
    assert a.doi == "10.2/ref-a" and a.year == 2019
    assert a.authors == ["Ada Lovelace"] and a.journal == "Journal X"
    assert a.abstract == "we benchmark a method"      # de-inverted


def test_cited_by_openalex_offline(monkeypatch):
    monkeypatch.setattr(snowball, "http_get", _dispatcher)
    recs = snowball.cited_by_openalex("https://doi.org/10.1/seed")
    assert len(recs) == 2
    assert all(r.source == "snowball:forward" for r in recs)
    assert {r.doi for r in recs} == {"10.3/cite-a", "10.3/cite-b"}


def test_cited_by_accepts_openalex_id(monkeypatch):
    # When given an OpenAlex id directly, no resolve round-trip is needed.
    calls = []

    def _spy(url, params=None, **kw):
        calls.append((url, (params or {}).get("filter", "")))
        return _Resp(CITES_RESULTS)

    monkeypatch.setattr(snowball, "http_get", _spy)
    recs = snowball.cited_by_openalex("W100")
    assert len(recs) == 2
    assert calls == [(snowball.OA_WORKS, "cites:W100")]


def test_references_crossref_offline(monkeypatch):
    monkeypatch.setattr(snowball, "http_get", _dispatcher)
    recs = snowball.references_crossref("https://doi.org/10.4/seed")
    assert len(recs) == 2                              # third entry dropped
    assert all(r.source == "snowball:backward" for r in recs)
    a = next(r for r in recs if r.doi == "10.4/cr-a")
    assert a.title == "CR Ref A" and a.year == 2018 and a.authors == ["Hopper"]
    b = next(r for r in recs if r.doi == "10.4/cr-b")
    assert "unstructured" in b.title.lower()


# ── orchestration ────────────────────────────────────────────────────────────
def test_snowball_dedups_seeds_and_caps(monkeypatch):
    monkeypatch.setattr(snowball, "http_get", _dispatcher)
    # Seed shares a DOI with one forward result → must be dropped from output.
    seeds = [Record(source="x", doi="10.3/cite-a", title="already included"),
             Record(source="x", doi="10.1/seed", title="Seed Study")]
    out = snowball.snowball(seeds, per_seed=100, max_total=3)
    assert len(out) == 3                               # capped
    uids = {r.uid for r in out}
    assert "doi:10.3/cite-a" not in uids               # seed uid excluded
    assert len(uids) == len(out)                       # no internal dups


def test_snowball_skips_seed_without_handle(monkeypatch):
    monkeypatch.setattr(snowball, "http_get", _dispatcher)
    # No DOI and no OpenAlex id → skipped without any network call.
    seeds = [Record(source="x", title="no identifiers", source_id="pmid:123")]
    out = snowball.snowball(seeds)
    assert out == []


def test_snowball_resilient_to_http_error(monkeypatch):
    def _boom_forward(url, params=None, **kw):
        params = params or {}
        if (params.get("filter", "")).startswith("cites:"):
            raise RuntimeError("network down")
        return _dispatcher(url, params, **kw)

    monkeypatch.setattr(snowball, "http_get", _boom_forward)
    seeds = [Record(source="x", doi="10.1/seed", title="Seed Study")]
    # Forward blows up but backward still yields records; sweep doesn't crash.
    out = snowball.snowball(seeds, max_total=50)
    assert len(out) == 2
    assert {r.doi for r in out} == {"10.2/ref-a", "10.2/ref-b"}
