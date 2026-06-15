"""Deep-pagination tests for the source connectors (fully offline).

Each connector is driven with a stub ``http_get`` that hands back two populated
pages followed by an empty/terminal page. We assert that:
  • a large ``retmax`` collects more than a single page's worth of records;
  • paging always terminates (no infinite loop) thanks to the page cap and the
    native cursor/offset signals;
  • the default ``retmax`` still returns only the first page when the API signals
    no further pages.
"""
from __future__ import annotations

from neuroaion.sources import (crossref, europepmc, openalex, pubmed,
                               semanticscholar)


class _Resp:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


# ── OpenAlex: cursor paging via meta.next_cursor ─────────────────────────────
def test_openalex_paginates_then_stops(monkeypatch):
    pages = [
        {"results": [{"id": f"https://openalex.org/W{i}", "title": f"A{i}"}
                     for i in range(200)],
         "meta": {"next_cursor": "C2"}},
        {"results": [{"id": f"https://openalex.org/W{200+i}", "title": f"B{i}"}
                     for i in range(200)],
         "meta": {"next_cursor": "C3"}},
        {"results": [], "meta": {"next_cursor": None}},
    ]
    calls = {"n": 0}

    def fake(url, params=None, **kw):
        i = calls["n"]
        calls["n"] += 1
        return _Resp(pages[min(i, len(pages) - 1)])

    monkeypatch.setattr(openalex, "http_get", fake)
    recs = openalex.search("q", retmax=500)
    assert len(recs) == 400              # two full pages, third empty stops it
    assert calls["n"] <= openalex._MAX_PAGES + 1


def test_openalex_default_single_page(monkeypatch):
    page = {"results": [{"id": f"https://openalex.org/W{i}", "title": f"A{i}"}
                        for i in range(200)],
            "meta": {"next_cursor": None}}   # no further pages signalled

    monkeypatch.setattr(openalex, "http_get", lambda *a, **k: _Resp(page))
    recs = openalex.search("q")          # default retmax=200
    assert len(recs) == 200


# ── Europe PMC: cursorMark paging ────────────────────────────────────────────
def test_europepmc_paginates_then_stops(monkeypatch):
    def make(prefix, n, nxt):
        return {"resultList": {"result": [{"id": f"{prefix}{i}", "title": f"{prefix}{i}",
                                           "source": "MED"} for i in range(n)]},
                "nextCursorMark": nxt}

    pages = [make("a", 1000, "M2"), make("b", 1000, "M3"),
             {"resultList": {"result": []}, "nextCursorMark": "M3"}]
    calls = {"n": 0}

    def fake(url, params=None, **kw):
        i = calls["n"]
        calls["n"] += 1
        return _Resp(pages[min(i, len(pages) - 1)])

    monkeypatch.setattr(europepmc, "http_get", fake)
    recs = europepmc.search("q", retmax=1500)
    assert len(recs) == 1500             # > one page, capped at retmax
    assert calls["n"] <= europepmc._MAX_PAGES + 1


def test_europepmc_stops_on_repeated_cursor(monkeypatch):
    """If nextCursorMark stops advancing, paging must terminate."""
    page = {"resultList": {"result": [{"id": f"x{i}", "title": f"t{i}", "source": "MED"}
                                      for i in range(10)]},
            "nextCursorMark": "SAME"}
    calls = {"n": 0}

    def fake(url, params=None, **kw):
        calls["n"] += 1
        return _Resp(dict(page, **{"resultList": {"result": [
            {"id": f"x{calls['n']}_{i}", "title": "t", "source": "MED"}
            for i in range(10)]}}))

    monkeypatch.setattr(europepmc, "http_get", fake)
    recs = europepmc.search("q", retmax=10000)
    # First call uses cursor "*", second returns "SAME"; once the cursor repeats
    # we stop. So at most a couple of calls, never the full cap.
    assert calls["n"] <= 3
    assert len(recs) <= 30


# ── Crossref: deep cursor paging via message.next-cursor ─────────────────────
def test_crossref_paginates_then_stops(monkeypatch):
    def make(prefix, n, nxt):
        return {"message": {"items": [{"DOI": f"10.1/{prefix}{i}", "title": [f"{prefix}{i}"]}
                                      for i in range(n)],
                            "next-cursor": nxt}}

    pages = [make("a", 200, "C2"), make("b", 200, "C3"),
             {"message": {"items": [], "next-cursor": "C4"}}]
    calls = {"n": 0}

    def fake(url, params=None, **kw):
        i = calls["n"]
        calls["n"] += 1
        return _Resp(pages[min(i, len(pages) - 1)])

    monkeypatch.setattr(crossref, "http_get", fake)
    recs = crossref.search("q", retmax=500)
    assert len(recs) == 400
    assert calls["n"] <= crossref._MAX_PAGES + 1


def test_crossref_default_single_page(monkeypatch):
    page = {"message": {"items": [{"DOI": f"10.1/a{i}", "title": [f"a{i}"]}
                                  for i in range(200)],
                        "next-cursor": None}}
    monkeypatch.setattr(crossref, "http_get", lambda *a, **k: _Resp(page))
    recs = crossref.search("q")
    assert len(recs) == 200


# ── PubMed: esearch retstart paging + efetch XML ─────────────────────────────
def test_pubmed_paginates_then_stops(monkeypatch):
    # esearch returns two full id pages then a short page that stops paging.
    esearch_pages = [
        {"esearchresult": {"idlist": [str(i) for i in range(200)]}},
        {"esearchresult": {"idlist": [str(200 + i) for i in range(200)]}},
        {"esearchresult": {"idlist": [str(400 + i) for i in range(5)]}},  # short → stop
    ]
    state = {"esearch": 0}

    def fake(url, params=None, **kw):
        if "esearch" in url:
            i = state["esearch"]
            state["esearch"] += 1
            return _Resp(esearch_pages[min(i, len(esearch_pages) - 1)])
        # efetch: build XML for the requested ids.
        ids = params["id"].split(",")
        arts = "".join(
            f"<PubmedArticle><MedlineCitation><PMID>{pid}</PMID>"
            f"<Article><ArticleTitle>T{pid}</ArticleTitle></Article>"
            f"</MedlineCitation></PubmedArticle>" for pid in ids)
        return _Resp(text=f"<PubmedArticleSet>{arts}</PubmedArticleSet>")

    monkeypatch.setattr(pubmed, "http_get", fake)
    monkeypatch.setattr(pubmed.time, "sleep", lambda *_: None)  # no real waits
    recs = pubmed.search("q", retmax=1000)
    assert len(recs) == 405              # 200 + 200 + 5, paging stopped on short page
    assert state["esearch"] <= pubmed._MAX_PAGES + 1


def test_pubmed_default_single_page(monkeypatch):
    state = {"esearch": 0}

    def fake(url, params=None, **kw):
        if "esearch" in url:
            state["esearch"] += 1
            # A short page (< per_call) means a single esearch call.
            return _Resp({"esearchresult": {"idlist": [str(i) for i in range(50)]}})
        ids = params["id"].split(",")
        arts = "".join(
            f"<PubmedArticle><MedlineCitation><PMID>{pid}</PMID>"
            f"<Article><ArticleTitle>T{pid}</ArticleTitle></Article>"
            f"</MedlineCitation></PubmedArticle>" for pid in ids)
        return _Resp(text=f"<PubmedArticleSet>{arts}</PubmedArticleSet>")

    monkeypatch.setattr(pubmed, "http_get", fake)
    monkeypatch.setattr(pubmed.time, "sleep", lambda *_: None)
    recs = pubmed.search("q")
    assert len(recs) == 50
    assert state["esearch"] == 1         # short page → no second esearch


# ── Semantic Scholar: offset/limit paging via data["next"] ───────────────────
def test_semanticscholar_paginates_then_stops(monkeypatch):
    pages = [
        {"data": [{"paperId": f"p{i}", "title": f"A{i}"} for i in range(100)],
         "next": 100},
        {"data": [{"paperId": f"p{100+i}", "title": f"B{i}"} for i in range(100)],
         "next": 200},
        {"data": []},                    # no data → stop
    ]
    calls = {"n": 0}

    def fake(url, params=None, **kw):
        i = calls["n"]
        calls["n"] += 1
        return _Resp(pages[min(i, len(pages) - 1)])

    monkeypatch.setattr(semanticscholar, "http_get", fake)
    recs = semanticscholar.search("q", retmax=300)
    assert len(recs) == 200
    assert calls["n"] <= semanticscholar._MAX_PAGES + 1


def test_semanticscholar_default_single_page(monkeypatch):
    page = {"data": [{"paperId": f"p{i}", "title": f"A{i}"} for i in range(100)]}
    # No "next" key → terminal page.
    monkeypatch.setattr(semanticscholar, "http_get", lambda *a, **k: _Resp(page))
    recs = semanticscholar.search("q", retmax=100)
    assert len(recs) == 100
