"""Protocol wizard + framework-agnostic protocol building."""
from neuroaion import frameworks, wizard
from neuroaion.agents.protocol import ProtocolArchitect
from neuroaion.llm import MockProvider
from neuroaion.models import ReviewProtocol


def test_build_seed_peco_maps_canonical_slots():
    seed = wizard.build_seed(
        topic="Air pollution and asthma",
        framework="PECO",
        elements={"Population": "children", "Exposure": "PM2.5",
                  "Comparator": "low exposure", "Outcome": "asthma incidence"},
        rob_tool="ROBINS-E", citation_style="apa",
        inclusion=["cohort studies"], exclusion=["reviews"],
        sources=["pubmed", "europepmc"], effect_measure="OR",
    )
    assert seed["pico"]["framework"] == "PECO"
    # Exposure mapped into the canonical 'intervention' slot for synthesis.
    assert seed["pico"]["intervention"] == "PM2.5"
    assert seed["pico"]["outcome"] == "asthma incidence"
    assert seed["risk_of_bias"]["tool"] == "ROBINS-E"
    assert seed["reporting"]["citation_style"] == "apa"
    assert seed["synthesis"]["effect_measure"] == "OR"


def test_protocol_architect_honours_framework_and_citation():
    seed = wizard.build_seed(
        topic="Scoping review of X", framework="PCC",
        elements={"Population": "adults", "Concept": "self-management",
                  "Context": "primary care"},
        citation_style="harvard", question="What is known about X?",
        inclusion=["any design"], rob_tool="JBI")
    proto = ProtocolArchitect(MockProvider(), ReviewProtocol(title=seed["title"])).build(seed)
    assert proto.pico.framework == "PCC"
    assert proto.pico.as_elements()["Concept"] == "self-management"
    assert proto.citation_style == "harvard"
    assert proto.risk_of_bias.tool == "JBI"
    # The eligibility contract renders the framework elements generically.
    block = proto.criteria_block()
    assert "FRAMEWORK: PCC" in block and "CONCEPT: self-management" in block


def test_write_protocol_yaml_roundtrip(tmp_path):
    seed = wizard.build_seed(topic="T", framework="SPIDER",
                             elements={"Sample": "nurses"})
    path = wizard.write_protocol_yaml(seed, tmp_path / "p.yaml")
    assert path.exists()
    import yaml
    loaded = yaml.safe_load(path.read_text())
    assert loaded["pico"]["framework"] == "SPIDER"


def test_all_frameworks_and_rob_tools_have_elements():
    for fw in frameworks.FRAMEWORKS:
        assert frameworks.framework_elements(fw)
    for tool, domains in frameworks.ROB_TOOLS.items():
        assert len(domains) >= 3
