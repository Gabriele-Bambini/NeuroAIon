"""Per-database query translation (reproducible native search syntax)."""
from neuroaion.sources.translate import translate, supported


KW = [["tDCS", "transcranial direct current stimulation"],
      ["working memory", "n-back"]]


def test_pubmed_uses_tiab_and_dates():
    q = translate("pubmed", KW, "2010-01-01", "2024-12-31")
    assert '"transcranial direct current stimulation"[Title/Abstract]' in q
    assert "tDCS[Title/Abstract]" in q
    assert " AND " in q and " OR " in q
    assert '2010' in q and '2024' in q and "Date - Publication" in q


def test_scopus_and_wos_field_syntax():
    s = translate("scopus", KW, "2010", "2024")
    assert s.startswith("TITLE-ABS-KEY(") and "PUBYEAR >" in s and "PUBYEAR <" in s
    w = translate("webofscience", KW, "2010", "2024")
    assert "TS=(" in w and "PY=(2010-2024)" in w


def test_europepmc_and_arxiv():
    e = translate("europepmc", KW, None, None)
    assert "TITLE:" in e and "ABSTRACT:" in e
    a = translate("arxiv", KW, None, None)
    assert "abs:" in a and " AND " in a


def test_plain_fallback_for_unknown_source():
    q = translate("openalex", KW)
    # Quoted Boolean every engine accepts; no field tags.
    assert '"working memory"' in q and " OR " in q and " AND " in q
    assert "TITLE-ABS-KEY" not in q and "[Title/Abstract]" not in q


def test_auto_date_is_ignored():
    q = translate("pubmed", KW, "2010-01-01", "auto")
    assert "3000" in q   # open upper bound when date_to == auto


def test_empty_keywords():
    assert translate("pubmed", []) == ""


def test_supported_list():
    s = supported()
    assert "pubmed" in s and "scopus" in s and "wos" in s
