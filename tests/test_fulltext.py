"""Full-text retrieval adapters — JATS parsing and MCP-shape normalisation."""
from neuroaion.models import Record
from neuroaion.sources.fulltext import (McpFullTextRetriever, _first_pmcid,
                                        _jats_body_text, _mcp_body_text)

# Real response shapes observed from the PMC MCP server.
CONVERT_RESPONSE = {
    "status": "ok",
    "records": [
        {"pmid": "35734582", "pmcid": "PMC9207555", "doi": "10.1016/j.cnp.2022.05.002"},
        {"pmid": "40350963"},  # no pmcid → no full text
    ],
}
FULLTEXT_RESPONSE = {
    "articles": [{
        "identifiers": {"pmcid": "PMC9207555", "pmid": "35734582"},
        "title": "Non-invasive brain stimulation and neuroenhancement",
        "abstract": "Highlights ...",
        "full_text": "1\n\nIntroduction\n\nNon-invasive brain stimulation (NIBS) ...",
        "doi": "10.1016/j.cnp.2022.05.002",
    }],
    "count": 1,
}


def test_first_pmcid_from_mcp_records():
    assert _first_pmcid(CONVERT_RESPONSE) == "PMC9207555"
    assert _first_pmcid([{"pmcid": "PMC42"}]) == "PMC42"        # bare list form
    assert _first_pmcid({"records": [{"pmid": "x"}]}) == ""     # no pmcid available


def test_mcp_body_text_extracts_full_text():
    body = _mcp_body_text(FULLTEXT_RESPONSE)
    assert "Non-invasive brain stimulation" in body
    assert _mcp_body_text("plain string body") == "plain string body"


def test_mcp_retriever_end_to_end():
    """Drive the retriever with callables returning the real MCP shapes."""
    calls = {}

    def convert(ids, idtype):
        calls["convert"] = (ids, idtype)
        return CONVERT_RESPONSE

    def full(pmc_ids):
        calls["full"] = pmc_ids
        return FULLTEXT_RESPONSE

    r = McpFullTextRetriever(convert_ids=convert, get_full_text=full)
    rec = Record(source="pubmed", source_id="35734582", title="probe")
    ft = r.retrieve(rec)

    assert ft.retrieved is True
    assert ft.source == "pmc"
    assert ft.pmcid == "PMC9207555"
    assert "Non-invasive brain stimulation" in ft.text
    assert calls["full"] == ["PMC9207555"]


def test_mcp_retriever_falls_back_to_abstract():
    r = McpFullTextRetriever(convert_ids=lambda i, t: {"records": [{}]},
                             get_full_text=lambda p: {"articles": []})
    rec = Record(source="crossref", doi="10.1/x", abstract="only an abstract here")
    ft = r.retrieve(rec)
    assert ft.retrieved is False
    assert ft.source == "abstract"
    assert ft.text == "only an abstract here"


def test_jats_body_text_skips_front_matter():
    xml = ("<article><front><article-meta><abstract><p>ABS</p></abstract>"
           "</article-meta></front><body><sec><title>Methods</title>"
           "<p>Forty adults received anodal tDCS.</p></sec></body></article>")
    body = _jats_body_text(xml)
    assert "Forty adults received anodal tDCS." in body
    assert "ABS" not in body  # abstract (front matter) excluded
