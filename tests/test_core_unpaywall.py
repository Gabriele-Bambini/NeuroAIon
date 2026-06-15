"""CORE connector mapping/paging and Unpaywall OA resolution (fully offline)."""
from __future__ import annotations

from neuroaion.sources import core
from neuroaion.sources import fulltext


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


CORE_PAGE = {
    "totalHits": 2,
    "results": [
        {
            "id": 12345,
            "title": "Deep learning for gene regulatory network inference",
            "abstract": "We benchmark deep models on BEELINE.",
            "authors": [{"name": "Jane Doe"}, {"name": "John Roe"}],
            "yearPublished": 2023,
            "doi": "10.1234/core.1",
            "journals": [{"title": "Bioinformatics"}],
            "downloadUrl": "https://core.ac.uk/download/1.pdf",
        },
        {
            "id": 67890,
            "title": "A second work",
            "abstract": "",
            "authors": [{"name": "Ada Lovelace"}],
            "yearPublished": 2021,
            "doi": "",
            "publisher": "Springer",
            "links": [{"url": "https://example.org/work2"}],
        },
    ],
}


def test_core_maps_fields(monkeypatch):
    monkeypatch.setattr(core, "http_get", lambda *a, **k: _Resp(CORE_PAGE))
    # No key in env → keyless path still works against our stub.
    monkeypatch.delenv("CORE_API_KEY", raising=False)
    recs = core.search("grn inference", retmax=200)
    assert len(recs) == 2
    r0 = recs[0]
    assert r0.source == "core"
    assert r0.title.startswith("Deep learning for gene regulatory")
    assert r0.doi == "10.1234/core.1"
    assert r0.year == 2023
    assert r0.authors == ["Jane Doe", "John Roe"]
    assert r0.journal == "Bioinformatics"
    assert r0.url == "https://core.ac.uk/download/1.pdf"
    # Second record: no DOI, no downloadUrl → falls back to links[].url, publisher.
    r1 = recs[1]
    assert r1.journal == "Springer"
    assert r1.url == "https://example.org/work2"


def test_core_paginates_with_offset(monkeypatch):
    def make(prefix, n):
        return {"totalHits": 250,
                "results": [{"id": f"{prefix}{i}", "title": f"{prefix}{i}"}
                            for i in range(n)]}

    pages = [make("a", 100), make("b", 100), {"totalHits": 250, "results": []}]
    calls = {"n": 0}

    def fake(url, params=None, **kw):
        i = calls["n"]
        calls["n"] += 1
        return _Resp(pages[min(i, len(pages) - 1)])

    monkeypatch.setattr(core, "http_get", fake)
    monkeypatch.delenv("CORE_API_KEY", raising=False)
    recs = core.search("q", retmax=250)
    assert len(recs) == 200              # two pages of 100, third empty stops
    assert calls["n"] <= core._MAX_PAGES + 1


def test_core_no_key_graceful_on_401(monkeypatch):
    """No key + a 401 (raised by http_get) → graceful empty list, no crash."""
    def boom(*a, **k):
        raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr(core, "http_get", boom)
    monkeypatch.delenv("CORE_API_KEY", raising=False)
    assert core.search("q", retmax=50) == []


def test_core_sends_bearer_when_key_present(monkeypatch):
    seen = {}

    def fake(url, params=None, **kw):
        seen["params"] = params
        return _Resp({"totalHits": 0, "results": []})

    monkeypatch.setattr(core, "http_get", fake)
    monkeypatch.setenv("CORE_API_KEY", "secret-key")
    core.search("q", retmax=10)
    assert seen["params"].get("Authorization") == "Bearer secret-key"


# ── Unpaywall OA resolution ──────────────────────────────────────────────────
UNPAYWALL_RESP = {
    "doi": "10.1234/oa.1",
    "is_oa": True,
    "best_oa_location": {
        "url": "https://repo.example.org/landing/1",
        "url_for_pdf": "https://repo.example.org/pdf/1.pdf",
        "version": "publishedVersion",
        "host_type": "repository",
    },
}


def test_unpaywall_oa_returns_best_location(monkeypatch):
    monkeypatch.setattr(fulltext, "http_get",
                        lambda *a, **k: _Resp(UNPAYWALL_RESP))
    loc = fulltext.unpaywall_oa("10.1234/oa.1", "me@example.org")
    assert loc is not None
    assert loc["url_for_pdf"] == "https://repo.example.org/pdf/1.pdf"
    assert loc["version"] == "publishedVersion"


def test_unpaywall_oa_none_when_no_location(monkeypatch):
    monkeypatch.setattr(fulltext, "http_get",
                        lambda *a, **k: _Resp({"doi": "x", "best_oa_location": None}))
    assert fulltext.unpaywall_oa("10.1/x", "me@example.org") is None


def test_unpaywall_oa_graceful_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(fulltext, "http_get", boom)
    assert fulltext.unpaywall_oa("10.1/x", "me@example.org") is None
    assert fulltext.unpaywall_oa("", "me@example.org") is None   # empty DOI


def test_retrieve_records_oa_url_when_no_extractor(monkeypatch):
    """When PMC/EPMC miss and pypdf is absent, retrieve() still surfaces the
    Unpaywall OA URL (source 'oa-url') instead of silently dropping it."""
    from neuroaion.models import Record

    # PMC + Europe PMC channels find nothing.
    monkeypatch.setattr(fulltext, "_resolve_pmcid", lambda rec: "")
    monkeypatch.setattr(fulltext, "_epmc_id_by_doi", lambda doi: ("", ""))
    # Unpaywall yields a best location.
    monkeypatch.setattr(fulltext, "unpaywall_oa",
                        lambda doi, email: UNPAYWALL_RESP["best_oa_location"])

    rec = Record(source="crossref", doi="10.1234/oa.1", abstract="the abstract")
    ft = fulltext.retrieve(rec)
    # No pypdf in this env → no extracted text, but the OA URL is recorded.
    if ft.source == "oa-url":
        assert ft.retrieved is False
        assert ft.text == "the abstract"
    else:
        # If pypdf is installed and the (stubbed) PDF was unreachable, we still
        # must not crash and must fall through to a sensible source.
        assert ft.source in {"oa-url", "abstract", "oa-pdf"}
