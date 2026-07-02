"""ScopingAgent: a probe that refines the protocol before the full search."""
from neuroaion.agents.scoping import ScopingAgent
from neuroaion.llm import MockProvider
from neuroaion.models import PICO, Record, ReviewProtocol, ScopingResult


def _protocol():
    return ReviewProtocol(
        title="CADe and adenoma detection",
        pico=PICO(population="patients undergoing colonoscopy",
                  intervention="computer-aided detection", outcome="adenoma detection rate"))


def test_scope_returns_result_in_mock():
    p = _protocol()
    agent = ScopingAgent(MockProvider(), p)
    sample = [Record(source="pubmed", doi="10/a", title="CADe RCT", year=2022,
                     abstract="A randomised trial of AI polyp detection.")]
    res = agent.scope(sample, probe_query="colonoscopy CADe adenoma")
    assert isinstance(res, ScopingResult)
    assert res.probe_query == "colonoscopy CADe adenoma"
    assert res.estimated_volume == 1


def test_apply_fills_gaps_only():
    p = _protocol()
    agent = ScopingAgent(MockProvider(), p)
    res = ScopingResult(
        keyword_groups=[["colonoscopy", "endoscopy"], ["CADe", "computer-aided detection"]],
        refined_inclusion=["RCTs of CADe"], refined_exclusion=["non-human"],
        suggested_designs=["RCT"], date_from="2015")
    agent.apply(p, res)
    assert p.search.keywords == res.keyword_groups
    assert p.inclusion_criteria == ["RCTs of CADe"]
    assert p.pico.study_designs == ["RCT"]
    assert p.search.date_from == "2015"


def test_apply_does_not_override_explicit_choices():
    p = _protocol()
    p.inclusion_criteria = ["Only my criterion"]
    p.search.keywords = [["mine"]]
    agent = ScopingAgent(MockProvider(), p)
    res = ScopingResult(keyword_groups=[["auto"]], refined_inclusion=["auto crit"])
    agent.apply(p, res)
    assert p.inclusion_criteria == ["Only my criterion"]     # untouched
    assert p.search.keywords == [["mine"]]                    # untouched


def test_scope_survives_empty_sample():
    p = _protocol()
    agent = ScopingAgent(MockProvider(), p)
    res = agent.scope([], probe_query="q")
    assert isinstance(res, ScopingResult)
