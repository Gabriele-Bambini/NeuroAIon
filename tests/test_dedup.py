from neuroaion.dedup import deduplicate
from neuroaion.models import Record


def test_doi_dedup_keeps_richest():
    a = Record(source="pubmed", doi="10.1/x", title="A study", abstract="short")
    b = Record(source="crossref", doi="10.1/X", title="A study",
               abstract="a much longer abstract with more detail", authors=["Smith J"])
    unique, removed = deduplicate([a, b])
    assert removed == 1
    assert len(unique) == 1
    assert unique[0].abstract.startswith("a much longer")  # richer record kept


def test_fuzzy_title_dedup_without_doi():
    a = Record(source="pubmed", title="tDCS enhances working memory in adults")
    b = Record(source="openalex", title="tDCS enhances working memory in adults.")
    unique, removed = deduplicate([a, b])
    assert removed == 1


def test_distinct_records_survive():
    a = Record(source="pubmed", doi="10.1/a", title="Study A")
    b = Record(source="pubmed", doi="10.1/b", title="Study B")
    unique, removed = deduplicate([a, b])
    assert removed == 0
    assert len(unique) == 2
