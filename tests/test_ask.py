"""Question-first entry: a plain-English question becomes a full protocol + run."""
from neuroaion.agents.protocol import ProtocolArchitect
from neuroaion.llm import MockProvider
from neuroaion.models import ReviewProtocol


def _architect():
    return ProtocolArchitect(MockProvider(), ReviewProtocol(title=""))


def test_build_from_free_text_question_populates_pico():
    seed = {"question": "Does AI-assisted colonoscopy improve adenoma detection?"}
    proto = _architect().build(seed)
    # The question is preserved and a PICO framework is set (mock fills schema slots).
    assert proto.question
    assert proto.pico.framework
    # A formal question always exists (fallback guarantees it).
    assert isinstance(proto.inclusion_criteria, list)


def test_explicit_pico_not_overridden_by_derivation():
    seed = {"question": "anything", "pico": {"population": "MY POP", "intervention": "MY INT"}}
    proto = _architect().build(seed)
    assert proto.pico.population == "MY POP" and proto.pico.intervention == "MY INT"


def test_cli_ask_runs_end_to_end(tmp_path):
    from neuroaion.orchestrator import Orchestrator
    seed = {"question": "Does drug X reduce mortality versus placebo?"}
    orch = Orchestrator(seed, mock=True, make_latex=False, compile_pdf=False, make_bundle=False)
    state = orch.run(out_root=str(tmp_path))
    assert state.protocol.question
    assert state.integrity.get("passed") is True
    # Corpus is numbered and every included study is numbered.
    assert all(u in state.citation_numbers for u in state.included_studies)
