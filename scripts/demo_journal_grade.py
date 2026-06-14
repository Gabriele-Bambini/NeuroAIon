"""Illustrative end-to-end demonstration of the journal-grade pipeline.

Builds a two-outcome review with REAL meta-analytic statistics (computed by the
deterministic engine from illustrative input effect sizes) and risk-of-bias
assessments derived by the signalling-question engine, then renders the full
dossier (figures, native PDF, LaTeX paper, compliance documents).

The INPUT effect sizes are illustrative; every statistic, figure and judgement is
computed by NeuroAIon. The run is marked mock=True so outputs are labelled
"DEMONSTRATION (illustrative data)".
"""
from __future__ import annotations

import math
import shutil
from pathlib import Path

from neuroaion import rob_engine
from neuroaion.models import (EffectEstimate, ExtractionRecord, PICO, PrismaFlow,
                              Record, ReviewProtocol, ReviewState, Synthesis)
from neuroaion.stats import hedges_g, meta_analyze
from neuroaion import report

# ── illustrative trial data: (mean_t, sd_t, n_t, mean_c, sd_c, n_c) per study ──
NBACK = [  # n-back accuracy (anodal tDCS vs sham), favours tDCS
    (0.78, 0.11, 24, 0.71, 0.12, 24), (0.81, 0.09, 30, 0.74, 0.10, 30),
    (0.69, 0.14, 18, 0.66, 0.13, 18), (0.85, 0.08, 40, 0.76, 0.11, 40),
    (0.73, 0.12, 22, 0.70, 0.12, 22), (0.79, 0.10, 28, 0.69, 0.11, 28),
    (0.88, 0.07, 35, 0.80, 0.09, 35),
]
RT = [  # reaction-time change (ms); smaller is better, modest/null effect
    (-22.0, 40.0, 24, -10.0, 42.0, 24), (-15.0, 38.0, 30, -12.0, 39.0, 30),
    (-30.0, 45.0, 18, -8.0, 44.0, 18), (-12.0, 36.0, 40, -11.0, 37.0, 40),
    (-25.0, 41.0, 22, -9.0, 40.0, 22), (-5.0, 35.0, 28, -7.0, 36.0, 28),
]

# Varied, plausible RoB2 signalling answers per study (drives differentiated RoB).
ROB_ANSWERS = [
    {"Randomization process": {"1.1": "Yes", "1.2": "Yes", "1.3": "No"},
     "Deviations from intended interventions": {"2.1": "No", "2.2": "No", "2.6": "No", "2.7": "No"},
     "Missing outcome data": {"3.1": "Yes", "3.2": "No"},
     "Measurement of the outcome": {"4.1": "No", "4.2": "No", "4.3": "No"},
     "Selection of the reported result": {"5.1": "Yes", "5.2": "No", "5.3": "No"}},
    {"Randomization process": {"1.1": "Yes", "1.2": "No information", "1.3": "No"},
     "Deviations from intended interventions": {"2.1": "No", "2.2": "No", "2.6": "No", "2.7": "No"},
     "Missing outcome data": {"3.1": "Yes"},
     "Measurement of the outcome": {"4.1": "No", "4.2": "No", "4.3": "Probably no"},
     "Selection of the reported result": {"5.1": "Yes", "5.2": "No", "5.3": "No"}},
    {"Randomization process": {"1.1": "No information", "1.2": "No information", "1.3": "Probably yes"},
     "Deviations from intended interventions": {"2.1": "Probably yes", "2.2": "No", "2.6": "No", "2.7": "No"},
     "Missing outcome data": {"3.1": "Probably no", "3.2": "Probably yes"},
     "Measurement of the outcome": {"4.1": "Probably yes", "4.2": "No", "4.3": "Probably yes"},
     "Selection of the reported result": {"5.1": "No information", "5.2": "Probably yes", "5.3": "No"}},
    {"Randomization process": {"1.1": "Yes", "1.2": "Yes", "1.3": "No"},
     "Deviations from intended interventions": {"2.1": "No", "2.2": "No", "2.6": "No", "2.7": "No"},
     "Missing outcome data": {"3.1": "Yes", "3.2": "No"},
     "Measurement of the outcome": {"4.1": "No", "4.2": "No", "4.3": "No"},
     "Selection of the reported result": {"5.1": "Yes", "5.2": "No", "5.3": "No"}},
    {"Randomization process": {"1.1": "Yes", "1.2": "Probably yes", "1.3": "No"},
     "Deviations from intended interventions": {"2.1": "No", "2.2": "Probably no", "2.6": "No", "2.7": "No"},
     "Missing outcome data": {"3.1": "Yes"},
     "Measurement of the outcome": {"4.1": "No", "4.2": "Probably no", "4.3": "No"},
     "Selection of the reported result": {"5.1": "Probably yes", "5.2": "No", "5.3": "No"}},
    {"Randomization process": {"1.1": "Probably no", "1.2": "No", "1.3": "Probably yes"},
     "Deviations from intended interventions": {"2.1": "Yes", "2.2": "Probably yes", "2.6": "No", "2.7": "No"},
     "Missing outcome data": {"3.1": "No", "3.2": "Probably yes"},
     "Measurement of the outcome": {"4.1": "Probably yes", "4.2": "Probably yes", "4.3": "Probably yes"},
     "Selection of the reported result": {"5.1": "No", "5.2": "Probably yes", "5.3": "Probably yes"}},
    {"Randomization process": {"1.1": "Yes", "1.2": "Yes", "1.3": "No"},
     "Deviations from intended interventions": {"2.1": "No", "2.2": "No", "2.6": "No", "2.7": "No"},
     "Missing outcome data": {"3.1": "Yes", "3.2": "No"},
     "Measurement of the outcome": {"4.1": "No", "4.2": "No", "4.3": "No"},
     "Selection of the reported result": {"5.1": "Yes", "5.2": "No", "5.3": "No"}},
]


def _smd(rows, outcome):
    effs = []
    for mt, st, nt, mc, sc, nc in rows:
        g, v = hedges_g(mt, st, nt, mc, sc, nc)
        effs.append(EffectEstimate(outcome=outcome, measure="SMD", estimate=g,
                                   se=math.sqrt(v), n_intervention=nt, n_comparator=nc))
    return effs


def build_state() -> ReviewState:
    nback_eff = _smd(NBACK, "N-back accuracy")
    rt_eff = _smd(RT, "Reaction time")
    labels_nb = [f"Trial {i+1}" for i in range(len(NBACK))]
    labels_rt = [f"Trial {i+1}" for i in range(len(RT))]

    meta_nb = meta_analyze(nback_eff, measure="SMD", model="random", labels=labels_nb,
                           tau2_method="REML", knha=True, prediction_interval_=True,
                           leave_one_out_=True, publication_bias=True,
                           outcome="N-back accuracy")
    meta_rt = meta_analyze(rt_eff, measure="SMD", model="random", labels=labels_rt,
                           tau2_method="REML", knha=True, prediction_interval_=True,
                           leave_one_out_=True, publication_bias=True,
                           outcome="Reaction time")

    recs, exts, robs = [], [], []
    for i in range(len(NBACK)):
        r = Record(source="pubmed", source_id=str(1000 + i), pmid=str(35000 + i),
                   doi=f"10.1000/tdcs.{i+1}", title=f"Anodal tDCS over the DLPFC and "
                   f"working memory in healthy adults: trial {i+1}",
                   authors=[f"Author{i}A B", f"Author{i}C D"], year=2016 + i,
                   journal="Journal of Cognitive Neuroscience", journal_abbrev="J Cogn Neurosci",
                   volume=str(28 + i), issue="3", pages=f"{100+i*12}-{110+i*12}", entry_type="article")
        recs.append(r)
        effs = [nback_eff[i]]
        if i < len(RT):
            effs.append(rt_eff[i])
        exts.append(ExtractionRecord(uid=r.uid, study_label=f"Trial {i+1}", design="RCT (crossover)",
                                     population="Healthy adults 18-40 y", intervention="Anodal tDCS over left DLPFC",
                                     comparator="Sham stimulation", sample_size=NBACK[i][2] + NBACK[i][5],
                                     outcomes=["N-back accuracy", "Reaction time"], effects=effs))
        robs.append(rob_engine.build_assessment("RoB2", f"Trial {i+1}", r.uid, ROB_ANSWERS[i]))

    metas = [m for m in (meta_nb, meta_rt) if m]
    primary = max(metas, key=lambda m: m.k_studies)

    # Deterministic enrichment of interpretations + GRADE via the synthesizer logic
    from neuroaion.agents.synthesis import EvidenceSynthesizer
    for m in metas:
        EvidenceSynthesizer._enrich_interpretation(m)

    st = ReviewState(
        run_id="demo-journal", mock=True, model="cowork (illustrative)",
        protocol=ReviewProtocol(
            title="Anodal transcranial direct current stimulation over the DLPFC and "
                  "working memory in healthy adults: a systematic review and meta-analysis",
            question="In healthy adults, does anodal tDCS over the dorsolateral prefrontal "
                     "cortex improve working-memory performance compared with sham stimulation?",
            authors_contact="02gabrielebambini@gmail.com",
            registration="Illustrative demonstration (not registered)",
            pico=PICO(framework="PICO", population="Healthy adults (18-40 y)",
                      intervention="Anodal tDCS over the left DLPFC",
                      comparator="Sham stimulation",
                      outcome="Working-memory performance (n-back accuracy; reaction time)",
                      study_designs=["randomized controlled trial", "randomized crossover trial"]),
            inclusion_criteria=["Randomized sham-controlled trials", "Healthy adults",
                                "Anodal tDCS over DLPFC", "Quantitative working-memory outcome"],
            exclusion_criteria=["Clinical populations", "Non-DLPFC montage", "No sham control",
                                "Animal or in-silico studies"]),
        unique_records=recs, included_studies=[r.uid for r in recs],
        extractions=exts, rob=robs, cohen_kappa=0.84,
        synthesis=Synthesis(meta_analysis=primary, meta_analyses=metas))
    st.prisma = PrismaFlow(
        records_identified={"pubmed": 214, "europepmc": 156, "arxiv": 18},
        records_total=388, records_from_databases=388, records_from_registers=0,
        duplicates_removed=97, records_screened=291, records_excluded_screening=248,
        reports_sought=43, reports_not_retrieved=3, reports_assessed=40,
        reports_excluded={"No sham control": 12, "Non-DLPFC montage": 9,
                          "Clinical population": 8, "No extractable outcome": 4},
        studies_included=7, reports_of_included=7)

    # Build the GRADE table deterministically.
    syn = EvidenceSynthesizer.__new__(EvidenceSynthesizer)
    rob_overall = {r.uid: a.overall for r, a in zip(recs, robs)}
    rows = []
    groups = {"N-back accuracy": (nback_eff, labels_nb, meta_nb),
              "Reaction time": (rt_eff, labels_rt, meta_rt)}
    for name, (effs, labs, m) in groups.items():
        if m:
            rows.append(syn._grade_row(name, m, effs, labs, exts, rob_overall))
    st.synthesis.grade_table = rows
    primary_row = max(rows, key=lambda r: r.n_studies) if rows else None
    if primary_row:
        st.synthesis.grade_certainty = primary_row.certainty
        st.synthesis.grade_rationale = (
            f"Randomized trials start at high certainty; risk of bias "
            f"{primary_row.risk_of_bias}, inconsistency {primary_row.inconsistency}, "
            f"imprecision {primary_row.imprecision}, publication bias {primary_row.other} "
            f"-> {primary_row.certainty}.")
    st.synthesis.narrative = (
        "Across the seven included trials, anodal tDCS over the left DLPFC was associated "
        f"with a {meta_nb.pooled_estimate} standardised mean improvement in n-back accuracy "
        f"(95% CI {meta_nb.ci_lower} to {meta_nb.ci_upper}); between-study heterogeneity was "
        f"{meta_nb.i_squared}% (tau-squared {meta_nb.tau_squared}). The effect on reaction time "
        f"was smaller and less certain (SMD {meta_rt.pooled_estimate}, 95% CI {meta_rt.ci_lower} "
        f"to {meta_rt.ci_upper}). " + (meta_nb.interpretation or ""))
    st.synthesis.limitations = (
        "The evidence base is small (k=7), several trials carried some-concerns risk of bias in "
        "the randomization and selective-reporting domains, and the 95% prediction interval was "
        "wide, indicating that the true effect in a new setting remains uncertain. Input effect "
        "sizes in this demonstration are illustrative.")
    return st


PROSE = {
    "abstract": (
        "Background: Anodal transcranial direct current stimulation (tDCS) over the "
        "dorsolateral prefrontal cortex (DLPFC) has been proposed as a non-invasive means "
        "of enhancing working memory, but trial results are mixed. "
        "Methods: We conducted a PRISMA 2020 systematic review and random-effects "
        "meta-analysis (REML between-study variance, Hartung-Knapp-Sidik-Jonkman inference) "
        "of randomized sham-controlled trials in healthy adults, with dual independent "
        "screening, RoB2 appraisal and GRADE certainty rating. "
        "Results: Seven trials were included. Anodal tDCS modestly improved n-back accuracy "
        "with substantial heterogeneity, whereas its effect on reaction time was small and "
        "imprecise; small-study effects were examined with Egger, Begg and trim-and-fill. "
        "Conclusions: Anodal tDCS over the DLPFC yields a modest, heterogeneous improvement "
        "in working-memory accuracy of low-to-moderate certainty. (Illustrative demonstration.)"),
    "background": (
        "Working memory is a core component of executive function, and its enhancement has "
        "broad implications for education, occupational performance and the management of "
        "cognitive disorders. Transcranial direct current stimulation (tDCS) delivers weak "
        "constant current through scalp electrodes and is hypothesised to raise cortical "
        "excitability under the anode. The dorsolateral prefrontal cortex (DLPFC) is the most "
        "common anodal target in working-memory studies. Individual randomized trials have "
        "reported heterogeneous effects, motivating a quantitative synthesis that accounts for "
        "between-study variability and assesses the certainty of the pooled evidence."),
    "methods": (
        "This review followed the PRISMA 2020 statement. Randomized sham-controlled trials of "
        "anodal tDCS over the DLPFC in healthy adults reporting a quantitative working-memory "
        "outcome were eligible. Records from PubMed, Europe PMC and arXiv were de-duplicated and "
        "screened in duplicate by two independent reviewers (Cohen's kappa = 0.84), with "
        "disagreements adjudicated. Standardised mean differences (Hedges g) were pooled per "
        "outcome under a random-effects model using REML for the between-study variance and "
        "Hartung-Knapp-Sidik-Jonkman confidence intervals. Heterogeneity was summarised with I2 "
        "(with confidence interval), tau-squared and a 95% prediction interval. Small-study "
        "effects were assessed with Egger's regression, Begg's rank correlation and trim-and-fill. "
        "Risk of bias was appraised with RoB2 and certainty with GRADE."),
    "discussion": (
        "Anodal tDCS over the DLPFC produced a modest improvement in working-memory accuracy, "
        "but the substantial heterogeneity and wide prediction interval indicate that the true "
        "effect varies across populations and montages and may be negligible in some settings. "
        "The weaker reaction-time effect suggests the benefit is expressed more in accuracy than "
        "in speed. These findings are consistent with the broader neuromodulation literature, in "
        "which stimulation parameters, electrode montage and task demands strongly moderate "
        "outcomes. Strengths of this review include duplicate screening, a deterministic and fully "
        "reproducible meta-analytic pipeline, and signalling-question-based risk-of-bias appraisal."),
    "conclusions": (
        "Anodal tDCS over the DLPFC is associated with a modest, heterogeneous improvement in "
        "working-memory accuracy of low-to-moderate certainty in healthy adults. Adequately "
        "powered trials with standardised montages and pre-registered analyses are needed before "
        "clinical or occupational recommendations can be made."),
}


def main():
    out = Path("runs/demo-journal-grade")
    shutil.rmtree(out, ignore_errors=True)
    st = build_state()
    report.write_artifacts(out, st, PROSE)
    report.write_latex(out, st, PROSE)
    report.bundle_run(out)
    m = st.synthesis.meta_analysis
    print(f"Included studies: {len(st.included_studies)} | outcomes meta-analysed: "
          f"{len(st.synthesis.meta_analyses)}")
    print(f"Primary outcome '{m.outcome}': SMD {m.pooled_estimate} "
          f"[{m.ci_lower}, {m.ci_upper}], I2={m.i_squared}% (CI {m.i_squared_ci_lower}-"
          f"{m.i_squared_ci_upper}), PI [{m.pi_lower}, {m.pi_upper}], GRADE "
          f"{st.synthesis.grade_certainty}")
    print(f"RoB overalls: {[a.overall for a in st.rob]}")
    print(f"Output: {out}")


if __name__ == "__main__":
    main()
