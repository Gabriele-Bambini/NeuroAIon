"""The results-bearing digest (tables/statistics) must survive truncation."""
from neuroaion.agents.extraction import _relevant_text


def test_appended_tables_survive_a_long_body():
    body = "Introduction. " + ("blah methods prose. " * 2000)   # ~40k chars of prose
    digest = ("\n=== EXTRACTED TABLES ===\n[Table 1]\n"
              "Arm | n | events\nDrug | 60 | 12\nPlacebo | 62 | 20\n")
    refs = "\n=== REFERENCES ===\n" + "\n".join(f"[{i}] Some citation {i}" for i in range(200))
    text = body + digest + refs
    out = _relevant_text(text)
    # The table's numbers survive; the reference dump is dropped.
    assert "Drug | 60 | 12" in out and "Placebo | 62 | 20" in out
    assert "Some citation 150" not in out
    assert len(out) <= 24000


def test_short_text_passes_through():
    t = "Short full text with a mean of 10.2 (SD 2.1)."
    assert _relevant_text(t) == t


def test_reference_section_stripped_from_body():
    body = "Results: the ADR was 40% vs 25%. " + ("prose. " * 4000)   # >24k, forces truncation
    text = body + "\nReferences\n" + "\n".join(f"{i}. cite" for i in range(300))
    out = _relevant_text(text)
    assert "40% vs 25%" in out and "299. cite" not in out
