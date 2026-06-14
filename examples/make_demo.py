#!/usr/bin/env python3
"""Generate the demo review sample (ILLUSTRATIVE DATA) into runs/demo/.

The study data here are authored for demonstration — NOT a real evidence
synthesis (the output is labelled as such). The statistics and rendering are the
engine's real output: meta-analysis, Egger's test, Cohen's kappa, PRISMA flow,
and the Markdown / HTML / LaTeX / PROSPERO artefacts.

    python examples/make_demo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neuroaion.models import (PICO, Decision, EffectEstimate, EligibilityDecision,
                              ExtractionRecord, Record, ReviewProtocol, ReviewState,
                              RoBAssessment, RoBConfig, RoBDomain, ScreeningDecision,
                              SearchConfig, Synthesis, SynthesisConfig)
from neuroaion.stats import cohen_kappa, eggers_test, funnel_points, meta_analyze
from neuroaion import prisma as P, report as R


def build() -> ReviewState:
    proto = ReviewProtocol(
        title="Anodal tDCS over the left DLPFC and working memory in healthy adults "
              "(PIPELINE DEMONSTRATION — illustrative data)",
        question=("In healthy adults, does anodal tDCS over the left DLPFC, versus sham, "
                  "improve working-memory performance on n-back tasks?"),
        pico=PICO(population="Healthy adults 18-65", intervention="Anodal tDCS, left DLPFC",
                  comparator="Sham stimulation", outcome="n-back accuracy (Hedges g)",
                  study_designs=["RCT", "randomized crossover"]),
        inclusion_criteria=["Healthy adults", "Sham-controlled RCT/crossover", "n-back outcome"],
        exclusion_criteria=["Clinical populations", "No sham arm", "Reviews/abstracts"],
        search=SearchConfig(sources=["pubmed", "europepmc", "crossref", "openalex"],
                            date_from="2008-01-01", date_to="2024-12-31",
                            keywords=[["tDCS"], ["working memory", "n-back"], ["DLPFC"]]),
        synthesis=SynthesisConfig(effect_measure="SMD", model="random", publication_bias=True),
        risk_of_bias=RoBConfig(tool="RoB2", grade=True),
        authors_contact="02gabrielebambini@gmail.com",
        registration="Demonstration — not registered")

    def rec(i, src, title, year):
        return Record(source=src, source_id=f"{src}{i}", doi=f"10.9999/demo.{i:03d}",
                      title=title, abstract=f"Sham-controlled n-back trial (illustrative).",
                      authors=[f"Author{i} A", "Bianchi L"], year=year, journal="NeuroImage (demo)")

    raw = [
        rec(1, "pubmed", "Anodal tDCS improves n-back accuracy over left DLPFC", 2013),
        rec(2, "pubmed", "Single-session tDCS and working memory: a crossover RCT", 2015),
        rec(3, "europepmc", "Prefrontal tDCS enhances 2-back performance", 2012),
        rec(4, "europepmc", "No reliable effect of tDCS on spatial working memory", 2018),
        rec(5, "crossref", "tDCS over DLPFC and executive working memory", 2016),
        rec(6, "openalex", "Anodal tDCS effects on verbal n-back: a sham-controlled trial", 2020),
    ]
    extra = [rec(7, "pubmed", "tACS and memory (off-topic intervention)", 2019),
             rec(8, "pubmed", "tDCS in stroke patients (clinical population)", 2017)]
    dups = [Record(source="crossref", source_id="x1", doi="10.9999/demo.001",
                   title=raw[0].title, abstract=raw[0].abstract, authors=raw[0].authors,
                   year=2013, journal="dup"),
            Record(source="openalex", source_id="x3", doi="10.9999/demo.003",
                   title=raw[2].title, year=2012, journal="dup")]
    unique = raw + extra
    records = unique + dups

    st = ReviewState(run_id="demo", mock=True,
                     model="cowork (Claude, illustrative data)", protocol=proto,
                     records=records, unique_records=unique)

    st.included_after_screening = [r.uid for r in raw]
    r1 = [Decision.INCLUDE] * 6 + [Decision.EXCLUDE, Decision.EXCLUDE]
    r2 = [Decision.INCLUDE] * 6 + [Decision.EXCLUDE, Decision.MAYBE]
    for r, d1, d2 in zip(unique, r1, r2):
        st.screening += [
            ScreeningDecision(uid=r.uid, reviewer="reviewer_1", decision=d1,
                              reason="on-topic" if d1 == Decision.INCLUDE else "wrong intervention/population"),
            ScreeningDecision(uid=r.uid, reviewer="reviewer_2", decision=d2, reason="")]
    st.cohen_kappa = cohen_kappa([d.value for d in r1], [d.value for d in r2])

    for j, r in enumerate(raw):
        if j == 5:
            st.eligibility.append(EligibilityDecision(uid=r.uid, eligible=False,
                                  full_text_retrieved=True,
                                  exclusion_reason="No valid sham comparator"))
        else:
            st.eligibility.append(EligibilityDecision(uid=r.uid, eligible=True,
                                  full_text_retrieved=True))
    st.included_studies = [r.uid for r in raw[:5]]

    gs = [(0.42, 0.18, 52), (0.18, 0.15, 64), (0.55, 0.25, 28), (0.05, 0.20, 40), (0.31, 0.17, 46)]
    for r, (g, se, n) in zip(raw[:5], gs):
        st.extractions.append(ExtractionRecord(
            uid=r.uid, study_label=f"{r.authors[0]} {r.year}", design="randomized crossover",
            population="Healthy adults", intervention="Anodal tDCS L-DLPFC", comparator="Sham",
            sample_size=n, outcomes=["n-back accuracy"],
            effects=[EffectEstimate(outcome="n-back accuracy", measure="SMD", estimate=g, se=se,
                                    n_intervention=n // 2, n_comparator=n // 2)]))
        st.rob.append(RoBAssessment(
            uid=r.uid, study_label=f"{r.authors[0]} {r.year}", tool="RoB2",
            domains=[RoBDomain(name="Randomization process", judgement="low"),
                     RoBDomain(name="Deviations", judgement="some concerns"),
                     RoBDomain(name="Missing outcome data", judgement="low"),
                     RoBDomain(name="Measurement of the outcome", judgement="some concerns"),
                     RoBDomain(name="Selection of the reported result", judgement="low")],
            overall="some concerns", rationale="Blinding of outcome assessment unclear."))

    effs = [e.effects[0] for e in st.extractions]
    labs = [e.study_label for e in st.extractions]
    meta = meta_analyze(effs, measure="SMD", model="random", labels=labs)
    meta.funnel = funnel_points(effs, "SMD")
    eg = eggers_test(effs)
    if eg:
        meta.eggers_intercept, meta.eggers_p, meta.eggers_k = eg["intercept"], eg["p"], eg["k"]
    sig = meta.ci_lower > 0 or meta.ci_upper < 0
    meta.interpretation = (f"The pooled effect {'reached' if sig else 'did not reach'} significance; "
                           f"heterogeneity was {'low' if meta.i_squared < 40 else 'substantial'} "
                           f"(I-squared={meta.i_squared}%).")
    st.synthesis = Synthesis(
        narrative=("Five sham-controlled trials (illustrative) contributed n-back accuracy data. "
                   "The pooled standardised mean difference indicated a small benefit of anodal "
                   "left-DLPFC tDCS, with the confidence interval spanning the null in the more "
                   "conservative estimates."),
        meta_analysis=meta, grade_certainty="low",
        grade_rationale="Downgraded for risk of bias (unclear blinding) and imprecision.",
        limitations="Small samples, single-session designs, and possible small-study effects.")
    st.prisma = P.compute_flow(st)
    return st


PROSE = {
    "abstract": ("Background: Anodal tDCS over the left DLPFC has been proposed to enhance working "
                 "memory. Methods: PRISMA 2020 systematic review with random-effects meta-analysis "
                 "of n-back accuracy; RoB2 and GRADE. Results: Five illustrative trials were pooled. "
                 "Conclusions: A small, uncertain benefit. (DEMONSTRATION — illustrative data.)"),
    "background": ("Working memory is central to cognition; non-invasive prefrontal stimulation has "
                   "been explored as an enhancer, with heterogeneous and contested evidence."),
    "methods": ("This review followed PRISMA 2020. Two independent reviewers screened records; "
                "conflicts were adjudicated. Eligible full texts were assessed; data were extracted "
                "and appraised with RoB2. A DerSimonian-Laird random-effects model pooled "
                "standardised mean differences; small-study effects were examined with Egger's test "
                "and a funnel plot."),
    "discussion": ("The pooled estimate points to a small effect with wide uncertainty. Unclear "
                   "blinding and small samples temper confidence; results are hypothesis-generating."),
    "conclusions": ("Anodal left-DLPFC tDCS may yield a small improvement in n-back accuracy, but "
                    "certainty is low. Adequately powered, pre-registered trials are needed."),
}


def main():
    st = build()
    out = Path(__file__).resolve().parents[1] / "runs" / "demo"
    R.write_artifacts(out, st, PROSE)
    R.write_latex(out, st, PROSE)
    R.bundle_run(out)
    m = st.synthesis.meta_analysis
    print(f"Pooled {m.measure}={m.pooled_estimate} [{m.ci_lower}, {m.ci_upper}] "
          f"I2={m.i_squared}% k={m.k_studies} | Egger p={m.eggers_p} | kappa={st.cohen_kappa}")
    print("Artifacts:", ", ".join(sorted(p.name for p in out.iterdir())))


if __name__ == "__main__":
    main()
