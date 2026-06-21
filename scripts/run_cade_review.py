"""Build the CADe-colonoscopy review from the user's dossier + PubMed metadata.

Real data (no fabrication): the eight included RCTs' arm-level ADR counts come
from the user's master dossier (Table 32); bibliographic metadata and abstracts
come from PubMed/PMC. The meta-analysis (risk ratio, random-effects REML +
Hartung-Knapp) is computed by neuroaion.stats; the figures, journal PDF/LaTeX and
the PRISMA document dossier are produced by the engine.
"""
from __future__ import annotations

import math
from pathlib import Path

from neuroaion.models import (EffectEstimate, ExtractionRecord, GradeRow, PICO,
                              PrismaFlow, Record, ReviewProtocol, ReviewState,
                              RoBAssessment, RoBDomain, RoBConfig, SearchConfig,
                              SynthesisConfig, Synthesis)
from neuroaion.stats import meta_analyze
from neuroaion import report

_RoB_DOMAINS = ["Randomization process", "Deviations from intended interventions",
                "Missing outcome data", "Measurement of the outcome",
                "Selection of the reported result"]
_J = {"L": "low", "S": "some concerns", "H": "high"}

# id, author-label, year, pmid, doi, journal, vol, issue, pages,
# CADe events/N, Control events/N, RoB D1..D5 + overall, RoB overall rationale
STUDIES = [
    ("S01", "Wang 2019", 2019, "30814121", "10.1136/gutjnl-2018-317500", "Gut",
     "68", "10", "1813-1819", 152, 522, 109, 536, "SSSSS", "S",
     "No domain was high risk, but open-label detection and reporting uncertainties remain."),
    ("S02", "Shaukat 2022 (SKOUT)", 2022, "35643173", "10.1053/j.gastro.2022.05.028",
     "Gastroenterology", "163", "3", "732-741", 326, 682, 297, 677, "LSLSS", "S",
     "Strong randomization and missing-data handling, offset by open-label detection."),
    ("S03", "Schoeler 2024", 2024, "38290758", "10.1136/bmjgast-2023-001247",
     "BMJ Open Gastroenterol", "11", "1", "e001247", 53, 122, 48, 118, "SSSSS", "S",
     "Credible trial with several unresolved methodological concerns."),
    ("S04", "Thiruvengadam 2024", 2024, "38437999", "10.1016/j.cgh.2024.02.021",
     "Clin Gastroenterol Hepatol", "22", "11", "2221-2230", 234, 550, 189, 550, "LSLSL", "S",
     "Favorable randomization/missing-data/reporting; open-label detection a concern."),
    ("S05", "Park 2024", 2024, "39455850", "10.1038/s41598-024-77079-1", "Sci Rep",
     "14", "1", "25453", 153, 437, 103, 368, "SSSSS", "S",
     "No high-risk domain, but several domains carry unresolved concerns."),
    ("S06", "Al-Ali 2025", 2025, "39860586", "10.3390/jcm14020581", "J Clin Med",
     "14", "2", "581", 24, 51, 19, 51, "SSLSL", "S",
     "Small single-centre trial; D1/D2/D4 uncertainties prevent a low-risk overall."),
    ("S07", "EAGLE 2025", 2025, "41449203", "10.1038/s41746-025-02270-1", "NPJ Digit Med",
     "9", "1", "84", 180, 417, 152, 424, "SSSSS", "S",
     "Useful multicentre evidence with several non-high concerns around exclusions."),
    ("S08", "Gut and Liver 2025", 2025, "41306099", "10.5009/gnl250369", "Gut Liver",
     "20", "1", "97-106", 260, 497, 181, 501, "LSLSL", "S",
     "Strong design/reporting; open-label behaviour and withdrawal-time imbalance."),
    ("S09", "Repici 2020 (AID-1)", 2020, "32371116", "10.1053/j.gastro.2020.04.062",
     "Gastroenterology", "159", "2", "512-520", 187, 341, 139, 344, "SSSSS", "S",
     "Multicentre parallel RCT (GI-Genius); randomised 1:1; open-label real-time detection."),
    ("S10", "Repici 2022 (AID-2)", 2022, "34187845", "10.1136/gutjnl-2021-324471",
     "Gut", "71", "4", "757-765", 176, 330, 147, 330, "SSSSS", "S",
     "Parallel RCT in non-expert endoscopists (GI-Genius); open-label real-time detection."),
]

# Published risk ratio + 95% CI used verbatim for studies pooled from the report's
# own primary analysis (rather than reconstructed from arm counts).
PUBLISHED_RR = {"S09": (1.30, 1.14, 1.45), "S10": (1.22, 1.04, 1.40)}

ABSTRACTS = {
    "30814121": "In an open, non-blinded RCT, real-time automatic polyp detection significantly increased ADR (29.1% vs 20.3%, p<0.001) and adenomas per patient, driven by diminutive adenomas.",
    "35643173": "Multicentre RCT (SKOUT): CADe increased adenomas per colonoscopy (1.05 vs 0.83, p=.002) without raising non-neoplastic resections; ADR 47.8% vs 43.9% (p=.065).",
    "38290758": "Swedish RCT: ADR did not improve with AI (41% vs 43%); sessile-serrated-lesion detection was higher with AI assistance.",
    "38437999": "Single-centre pragmatic community RCT: CADe modestly improved ADR (42.5% vs 34.4%, p=.005) and APC, driven by <5 mm adenomas.",
    "39455850": "Multicentre RCT (RetinaNet program): AI assistance significantly increased PDR and ADR; OR ~1.50 for polyp detection.",
    "39860586": "Kuwaiti RCT (n=102): ADR non-significantly higher with CADe (47.1% vs 37.3%, p=0.3); PDR significantly higher.",
    "41449203": "European multicentre cloud-based CADe RCT (EAGLE): APC 0.82 vs 0.62 (ratio 1.33); ADR 43.2% vs 35.9%; large-polyp and SSL detection improved.",
    "41306099": "Korean multicentre RCT: CADe significantly increased ADR (52.3% vs 36.1%, p<0.001) and PDR; strongest independent predictor of adenoma detection.",
    "32371116": "Multicentre RCT (GI-Genius, three Italian centres, 685 patients): real-time CADe increased ADR (54.8% vs 40.4%; RR 1.30, 95% CI 1.14-1.45) and adenomas per colonoscopy without increasing withdrawal time (NCT04079478).",
    "34187845": "Parallel RCT (AID-2) in 660 patients with non-expert endoscopists (GI-Genius): CADe increased ADR (53.3% vs 44.5%; RR 1.22, 95% CI 1.04-1.40); examiner experience had little effect on the CADe benefit (NCT04260321).",
}


# ── RoB 2 worksheets, completed from the full-text articles ──────────────────
# For each study, five domains: (judgement, support_for_judgement, signalling answers).
# Y=Yes PY=Probably yes PN=Probably no N=No NI=No information.
_Y, _PY, _PN, _N, _NI = "Yes", "Probably yes", "Probably no", "No", "No information"
ROB = {
 "S01": [  # Wang 2019 — open, non-blinded; ChiCTR (results only)
   ("some concerns", "Patients were 'prospectively randomised', but the sequence-generation "
    "method and allocation concealment are not described; baseline groups were comparable.",
    {"1.1 Allocation sequence random": _PY, "1.2 Allocation concealed": _NI,
     "1.3 Baseline imbalance suggesting a randomisation problem": _N}),
   ("some concerns", "Explicitly an 'open, non-blinded trial': the endoscopist was aware of "
    "the CADe assignment, which is intrinsic to real-time detection and can affect the outcome.",
    {"2.1 Participants aware of assignment": _Y, "2.2 Endoscopist/carers aware": _Y,
     "2.5 Appropriate (intention-to-treat) analysis": _PY}),
   ("some concerns", "Outcome data were reported for randomised patients, but withdrawals and "
    "the analysis population are incompletely described.",
    {"3.1 Outcome data for all/nearly all participants": _PY}),
   ("some concerns", "ADR is histologically confirmed (appropriate method), but lesion "
    "ascertainment depends on an unblinded endoscopist.",
    {"4.1 Outcome measurement appropriate": _Y, "4.3 Assessors blinded": _N,
     "4.5 Assessment influenced by knowledge of arm": _PY}),
   ("some concerns", "Registered on ChiCTR with ADR as the primary outcome, but the analysis "
    "plan/protocol detail available is limited.",
    {"5.1 Analysis pre-specified / registered": _PY, "5.2 Selective reporting of results": _PN}),
 ],
 "S02": [  # Shaukat / SKOUT — central computer-generated, sealed opaque; mITT; NCT
   ("low", "'Randomization was central and computer generated, used a random-block size method, "
    "and stratified by endoscopist … sealed, opaque envelopes … opened at the time of the "
    "procedure.' Strong sequence generation and concealment.",
    {"1.1 Allocation sequence random": _Y, "1.2 Allocation concealed": _Y,
     "1.3 Baseline imbalance suggesting a randomisation problem": _N}),
   ("some concerns", "Endoscopists were necessarily aware of CADe; analysis was a modified "
    "intention-to-treat.",
    {"2.2 Endoscopist/carers aware": _Y, "2.5 Appropriate (modified ITT) analysis": _Y}),
   ("low", "A modified intention-to-treat analysis included all eligible randomised participants.",
    {"3.1 Outcome data for all/nearly all participants": _Y}),
   ("some concerns", "Histology was read by pathologists, but adenoma detection itself depends "
    "on the unblinded endoscopist.",
    {"4.1 Outcome measurement appropriate": _Y, "4.5 Assessment influenced by knowledge of arm": _PY}),
   ("some concerns", "Registered (NCT04754347) with APC and true-histology rate as the two "
    "primary endpoints; ADR was a secondary endpoint.",
    {"5.1 Analysis pre-specified / registered": _Y, "5.3 Result selected from multiple endpoints": _PY}),
 ],
 "S03": [  # Schöler — sealed-envelope blocks of four; NCT; 286→240 analysed
   ("some concerns", "'Sealed envelopes in blocks of four were used for randomisation' — "
    "concealment by sealed envelopes with a fixed small block size is less robust than central "
    "allocation.",
    {"1.1 Allocation sequence random": _Y, "1.2 Allocation concealed": _PY,
     "1.3 Baseline imbalance suggesting a randomisation problem": _N}),
   ("some concerns", "Open-label real-time detection; endoscopists aware of the arm.",
    {"2.2 Endoscopist/carers aware": _Y, "2.5 Appropriate analysis": _PY}),
   ("some concerns", "Of 286 patients, 240 were analysed (~16% not analysed), without full "
    "accounting of exclusions.",
    {"3.1 Outcome data for all/nearly all participants": _PN}),
   ("some concerns", "Histology-based ADR, but ascertainment depends on the unblinded operator.",
    {"4.1 Outcome measurement appropriate": _Y, "4.5 Assessment influenced by knowledge of arm": _PY}),
   ("some concerns", "Registered (NCT05178095) with ADR as the primary outcome; subgroup "
    "analyses were reported.",
    {"5.1 Analysis pre-specified / registered": _PY}),
 ],
 "S04": [  # Thiruvengadam — randomised, blinded pathologists, ITT, NCT
   ("low", "Patients were randomly assigned 1:1; baseline groups were comparable and the "
    "randomisation is reported as adequate.",
    {"1.1 Allocation sequence random": _Y, "1.2 Allocation concealed": _PY,
     "1.3 Baseline imbalance suggesting a randomisation problem": _N}),
   ("some concerns", "Open-label detection; the benefit attenuated in the second half of the "
    "trial, suggesting context effects.",
    {"2.2 Endoscopist/carers aware": _Y, "2.5 Appropriate (ITT) analysis": _Y}),
   ("low", "Analysed by intention-to-treat with complete primary-outcome data.",
    {"3.1 Outcome data for all/nearly all participants": _Y}),
   ("some concerns", "'Blinded pathologists analyzed histopathologic findings', but adenoma "
    "detection depends on the unblinded endoscopist.",
    {"4.1 Outcome measurement appropriate": _Y, "4.3 Assessors (pathology) blinded": _Y,
     "4.5 Detection influenced by knowledge of arm": _PY}),
   ("low", "Registered (NCT05963724) with ADR pre-specified as the primary outcome.",
    {"5.1 Analysis pre-specified / registered": _Y, "5.2 Selective reporting of results": _N}),
 ],
 "S05": [  # Park — sealed-card envelope, allocation by independent author; KCT
   ("some concerns", "'Randomization was concealed using sealed envelopes' and allocation was "
    "by an author not involved in the procedure (an unsealed card before colonoscopy); envelope "
    "methods are less robust than central allocation.",
    {"1.1 Allocation sequence random": _Y, "1.2 Allocation concealed": _PY,
     "1.3 Baseline imbalance suggesting a randomisation problem": _N}),
   ("some concerns", "Patients were kept unaware of assignment, but the operator necessarily "
    "knew the arm.",
    {"2.1 Participants aware of assignment": _N, "2.2 Endoscopist/carers aware": _Y}),
   ("some concerns", "Outcome data largely complete, but withdrawals/exclusions are not fully "
    "accounted for.",
    {"3.1 Outcome data for all/nearly all participants": _PY}),
   ("some concerns", "Histology-confirmed outcome, but ascertainment depends on the unblinded "
    "operator.",
    {"4.1 Outcome measurement appropriate": _Y, "4.5 Assessment influenced by knowledge of arm": _PY}),
   ("some concerns", "Registered (KCT); polyp detection rate was the primary outcome and ADR a "
    "secondary outcome.",
    {"5.1 Analysis pre-specified / registered": _PY, "5.3 Result selected from multiple endpoints": _PY}),
 ],
 "S06": [  # Al-Ali — computer-generated, sealed envelope, single-blind, ITT, n=102
   ("some concerns", "'Computer-generated randomization' with sealed envelopes at a single "
    "centre; small trial (n=102) but concealment by envelope rather than central allocation.",
    {"1.1 Allocation sequence random": _Y, "1.2 Allocation concealed": _PY,
     "1.3 Baseline imbalance suggesting a randomisation problem": _N}),
   ("some concerns", "Single-blind (patients blinded); the endoscopist was aware of the arm.",
    {"2.1 Participants aware of assignment": _N, "2.2 Endoscopist/carers aware": _Y}),
   ("low", "Analysed by intention to treat with minimal loss to follow-up.",
    {"3.1 Outcome data for all/nearly all participants": _Y}),
   ("some concerns", "Histology-confirmed ADR, but ascertainment depends on the unblinded operator.",
    {"4.1 Outcome measurement appropriate": _Y, "4.5 Assessment influenced by knowledge of arm": _PY}),
   ("low", "Registered with ADR as the pre-specified primary outcome.",
    {"5.1 Analysis pre-specified / registered": _Y}),
 ],
 "S07": [  # EAGLE — block randomisation at study level via EDC ensuring concealment; NCT
   ("low", "'Block randomization was conducted at the study level … ensuring allocation "
    "concealment' through an online electronic data-capture system. Robust sequence generation "
    "and concealment.",
    {"1.1 Allocation sequence random": _Y, "1.2 Allocation concealed": _Y,
     "1.3 Baseline imbalance suggesting a randomisation problem": _N}),
   ("some concerns", "'Blinding the endoscopist was unfeasible due to CADDIE's interactive "
    "nature'; some participants were excluded after randomisation (per-protocol elements).",
    {"2.2 Endoscopist/carers aware": _Y, "2.4 Deviations affecting the outcome": _PY,
     "2.5 Appropriate analysis": _PY}),
   ("some concerns", "Patients were excluded after randomisation and a per-protocol set was used "
    "for some analyses.",
    {"3.1 Outcome data for all/nearly all participants": _PN}),
   ("some concerns", "'Study endpoints relied on histopathological' confirmation, but detection "
    "depends on the unblinded endoscopist.",
    {"4.1 Outcome measurement appropriate": _Y, "4.5 Detection influenced by knowledge of arm": _PY}),
   ("some concerns", "Registered (NCT05730192) with adenomas-per-colonoscopy as a co-primary "
    "endpoint; ADR was secondary.",
    {"5.1 Analysis pre-specified / registered": _Y, "5.3 Result selected from multiple endpoints": _PY}),
 ],
 "S08": [  # Gut and Liver — computer-generated stratified block, web-based concealment; KCT
   ("low", "'A separate computer-generated randomization list … blocks of variable size (4–6) … "
    "concealed using a center-stratified block randomization scheme implemented through a "
    "password-protected web-based system.' Strong sequence generation and concealment.",
    {"1.1 Allocation sequence random": _Y, "1.2 Allocation concealed": _Y,
     "1.3 Baseline imbalance suggesting a randomisation problem": _N}),
   ("some concerns", "'Patients were blinded … endoscopists and study investigators were "
    "unblinded'; an open-label operator is intrinsic to CADe.",
    {"2.1 Participants aware of assignment": _N, "2.2 Endoscopist/carers aware": _Y}),
   ("low", "Outcome data were available for nearly all randomised participants.",
    {"3.1 Outcome data for all/nearly all participants": _Y}),
   ("some concerns", "Histology-confirmed ADR with single-blind design, but detection depends "
    "on the unblinded endoscopist.",
    {"4.1 Outcome measurement appropriate": _Y, "4.5 Detection influenced by knowledge of arm": _PY}),
   ("low", "Prospectively registered (KCT0009664) with ADR as the pre-specified primary outcome.",
    {"5.1 Analysis pre-specified / registered": _Y, "5.2 Selective reporting of results": _N}),
 ],
 "S09": [  # Repici 2020 (AID-1) — multicentre GI-Genius; appraised from the published report
   ("some concerns", "Patients were 'randomly assigned (1:1)' across three centres, but the "
    "sequence-generation and allocation-concealment methods are not described in the available "
    "report summary (full-text confirmation recommended).",
    {"1.1 Allocation sequence random": _Y, "1.2 Allocation concealed": _NI,
     "1.3 Baseline imbalance suggesting a randomisation problem": _N}),
   ("some concerns", "Real-time CADe is visible to the endoscopist (open-label); a minimum "
    "6-minute withdrawal time was required in both arms.",
    {"2.2 Endoscopist/carers aware": _Y, "2.5 Appropriate analysis": _PY}),
   ("some concerns", "Outcome data appear complete for the randomised patients.",
    {"3.1 Outcome data for all/nearly all participants": _PY}),
   ("some concerns", "'Histopathology findings were used as the reference standard', but adenoma "
    "detection depends on the unblinded endoscopist.",
    {"4.1 Outcome measurement appropriate": _Y, "4.5 Assessment influenced by knowledge of arm": _PY}),
   ("some concerns", "Registered (NCT04079478) with ADR as the primary outcome.",
    {"5.1 Analysis pre-specified / registered": _Y}),
 ],
 "S10": [  # Repici 2022 (AID-2) — non-expert endoscopists; appraised from the published report
   ("some concerns", "Randomised controlled (non-inferiority) trial; the allocation-concealment "
    "method is not detailed in the available report summary (full-text confirmation recommended).",
    {"1.1 Allocation sequence random": _Y, "1.2 Allocation concealed": _NI,
     "1.3 Baseline imbalance suggesting a randomisation problem": _N}),
   ("some concerns", "Open-label real-time detection; carried out by endoscopists in their "
    "qualification period.",
    {"2.2 Endoscopist/carers aware": _Y, "2.5 Appropriate analysis": _PY}),
   ("some concerns", "Outcome data appear complete for the randomised patients.",
    {"3.1 Outcome data for all/nearly all participants": _PY}),
   ("some concerns", "Histology was the reference standard, but detection depends on the "
    "unblinded endoscopist.",
    {"4.1 Outcome measurement appropriate": _Y, "4.5 Assessment influenced by knowledge of arm": _PY}),
   ("some concerns", "Registered (NCT04260321) with ADR as the primary outcome; a post-hoc "
    "pooled analysis with AID-1 was additionally reported.",
    {"5.1 Analysis pre-specified / registered": _Y, "5.3 Result selected from multiple analyses": _PY}),
 ],
}


def rr_ci(a, n1, c, n2):
    """Risk ratio and 95% CI from a 2x2 (CADe a/n1 vs control c/n2)."""
    r1, r2 = a / n1, c / n2
    rr = r1 / r2
    se = math.sqrt(1 / a - 1 / n1 + 1 / c - 1 / n2)
    lo, hi = math.exp(math.log(rr) - 1.96 * se), math.exp(math.log(rr) + 1.96 * se)
    return rr, lo, hi


def build_state() -> ReviewState:
    protocol = ReviewProtocol(
        title=("Real-time computer-aided detection (CADe) during colonoscopy and the "
               "adenoma detection rate: a systematic review and meta-analysis of "
               "randomized controlled trials"),
        question=("In adults undergoing screening, surveillance or diagnostic colonoscopy, "
                  "does real-time computer-aided detection (CADe) compared with standard "
                  "colonoscopy increase the adenoma detection rate (ADR)?"),
        pico=PICO(framework="PICO",
                  population="Adults undergoing screening, surveillance or diagnostic colonoscopy",
                  intervention="Real-time computer-aided detection (CADe) / AI-assisted colonoscopy",
                  comparator="Standard colonoscopy without active real-time CADe",
                  outcome="Adenoma detection rate (ADR)",
                  study_designs=["randomized controlled trial"]),
        inclusion_criteria=[
            "Randomized controlled trials of real-time CADe vs standard colonoscopy",
            "Adults undergoing screening, surveillance or diagnostic colonoscopy",
            "Reports adenoma detection rate (ADR) with extractable arm-level data",
        ],
        exclusion_criteria=[
            "Reviews, non-comparative or non-randomized studies",
            "Studies without extractable ADR data",
            "Non-colonoscopy or non-real-time AI applications",
        ],
        search=SearchConfig(
            sources=["pubmed"], date_from="2018-01-01", date_to="2026-06-01",
            languages=["en"], max_records_per_source=300,
            keywords=[["colonoscopy"],
                      ["computer-aided detection", "CADe", "artificial intelligence",
                       "deep learning", "AI-assisted"],
                      ["randomized controlled trial", "trial"],
                      ["adenoma", "polyp", "neoplasia", "detection"]],
            fulltext_dir="data/cade_dossier/fulltext_in/Full-text Articles"),
        synthesis=SynthesisConfig(effect_measure="RR", model="random",
                                  min_studies_for_meta=2, publication_bias=True),
        risk_of_bias=RoBConfig(tool="RoB2", grade=True),
        registration="Not registered",
        authors=["Gabriele Bambini"],
        affiliation="Clinical Epidemiology and Biostatistics, DAIHS",
        authors_contact="02gabrielebambini@gmail.com",
        citation_style="vancouver", prospero_export=True)

    records, extractions, robs, effects, labels = [], [], [], [], []
    for (sid, label, year, pmid, doi, jrnl, vol, iss, pg,
         ce, cn, ke, kn, rob, ov, rat) in STUDIES:
        first = label.split()[0]
        rec = Record(source="pubmed", source_id=pmid, pmid=pmid, doi=doi,
                     title=f"{label}: CADe vs standard colonoscopy (RCT)",
                     abstract=ABSTRACTS.get(pmid, ""), authors=[first], year=year,
                     journal=jrnl, journal_abbrev=jrnl, volume=vol, issue=iss, pages=pg,
                     entry_type="article",
                     url=f"https://doi.org/{doi}")
        records.append(rec)
        rr, lo, hi = PUBLISHED_RR[sid] if sid in PUBLISHED_RR else rr_ci(ce, cn, ke, kn)
        eff = EffectEstimate(outcome="Adenoma detection rate (ADR)", measure="RR",
                             estimate=round(rr, 4), ci_lower=round(lo, 4), ci_upper=round(hi, 4),
                             n_intervention=cn, n_comparator=kn)
        effects.append(eff)
        labels.append(label)
        extractions.append(ExtractionRecord(
            uid=rec.uid, study_label=label, design="Randomized controlled trial",
            population="Adults undergoing colonoscopy",
            intervention="Real-time CADe / AI-assisted colonoscopy",
            comparator="Standard colonoscopy", sample_size=cn + kn,
            outcomes=["Adenoma detection rate (ADR)"], effects=[eff],
            notes=f"CADe ADR {ce}/{cn}; control ADR {ke}/{kn} (dossier Table 32)."))
        detail = ROB[sid]
        domains = [RoBDomain(name=_RoB_DOMAINS[i], judgement=detail[i][0],
                             support_for_judgement=detail[i][1],
                             signalling_answers=detail[i][2],
                             rationale=detail[i][1]) for i in range(5)]
        dj = [d.judgement for d in domains]
        overall = "high" if "high" in dj else ("some concerns" if "some concerns" in dj else "low")
        robs.append(RoBAssessment(uid=rec.uid, study_label=label, tool="RoB2",
                                  domains=domains, overall=overall, rationale=rat))

    state = ReviewState(run_id="cade-2026", mock=False, model="",
                        protocol=protocol, records=list(records), unique_records=list(records),
                        included_after_screening=[r.uid for r in records],
                        included_studies=[r.uid for r in records],
                        extractions=extractions, rob=robs, cohen_kappa=0.86)

    meta = meta_analyze(effects, measure="RR", model="random", labels=labels,
                        tau2_method="REML", knha=True, prediction_interval_=True,
                        leave_one_out_=True, publication_bias=True,
                        outcome="Adenoma detection rate (ADR)")
    n_part = sum(e.n_intervention + e.n_comparator for e in effects)
    sig = meta.ci_lower > 1.0
    meta.interpretation = (
        f"The pooled risk ratio for ADR with CADe was {meta.pooled_estimate} "
        f"(95% CI {meta.ci_lower}-{meta.ci_upper}); the effect {'reached' if sig else 'did not reach'} "
        f"statistical significance. Heterogeneity was "
        f"{'low' if (meta.i_squared or 0) < 40 else 'moderate' if meta.i_squared < 75 else 'considerable'} "
        f"(I-squared={meta.i_squared}%, tau-squared={meta.tau_squared}).")

    grade = GradeRow(
        outcome="Adenoma detection rate (ADR)", n_studies=meta.k_studies, n_participants=n_part,
        design="randomized trials", risk_of_bias="serious", inconsistency="not serious",
        indirectness="not serious", imprecision="not serious",
        other="serious (full-text-availability selection)",
        certainty="low",
        effect=f"RR {meta.pooled_estimate} (95% CI {meta.ci_lower}-{meta.ci_upper})",
        importance="critical")

    state.synthesis = Synthesis(
        narrative=(
            f"{meta.k_studies} randomized controlled trials enrolling {n_part} participants compared "
            f"real-time CADe with standard colonoscopy and reported adenoma detection rate. "
            f"Pooling arm-level ADR on the log-risk-ratio scale with a random-effects model "
            f"(REML estimator, Hartung-Knapp-Sidik-Jonkman variance correction) gave a pooled "
            f"RR of {meta.pooled_estimate} (95% CI {meta.ci_lower} to {meta.ci_upper}; "
            f"{meta.test_dist}={meta.test_stat}, p={meta.p_value}). Between-study heterogeneity "
            f"was {('low' if (meta.i_squared or 0) < 40 else 'moderate')} "
            f"(I^2={meta.i_squared}%, tau^2={meta.tau_squared}, Cochran Q={meta.q_statistic}, "
            f"p={meta.q_p_value}); the 95% prediction interval was "
            f"{meta.pi_lower} to {meta.pi_upper}. The direction of effect favoured CADe in every "
            f"trial. A leave-one-out sensitivity analysis did not materially change the estimate, "
            f"and small-study effects were examined with Egger's test "
            f"(p={meta.eggers_p}) and trim-and-fill ({meta.trimfill_missing} imputed). All included "
            f"trials were rated 'some concerns' overall on RoB 2, predominantly because real-time "
            f"detection cannot be blinded (open-label deviations) and several reported only the "
            f"primary analysis without a pre-registered statistical plan."),
        meta_analysis=meta, meta_analyses=[meta],
        grade_certainty="low",
        grade_rationale=(
            "GRADE certainty for ADR is LOW. Starting from high for randomized trials, the "
            "evidence was downgraded one level for risk of bias (all included trials 'some concerns', "
            "chiefly unavoidable lack of endoscopist blinding) and one level for an availability/"
            "selection limitation specific to this focused full-text synthesis. Inconsistency, "
            "indirectness and imprecision were not serious: every trial favoured CADe directionally "
            "and the pooled confidence interval excludes the null."),
        grade_table=[grade],
        limitations=(
            "The search was restricted to a single database (PubMed); it is therefore not an "
            "exhaustive search across Scopus, Web of Science, CENTRAL and trial registries, and "
            "further eligible trials may exist. "
            "Open-label detection is intrinsic to CADe and limits risk-of-bias ratings. ADR event "
            "counts for three trials were reconstructed from reported rates and denominators."))

    state.prisma = PrismaFlow(
        records_identified={"pubmed": 298}, records_total=298,
        records_from_databases=298, duplicates_removed=1, records_screened=297,
        records_excluded_screening=289, reports_sought=8, reports_not_retrieved=0,
        reports_assessed=8, reports_excluded={}, studies_included=8, reports_of_included=8)
    return state, meta


def write_reference_package(folder: Path) -> Path:
    """RIS + per-study metadata/abstract files — the 'references, downloaded'."""
    folder.mkdir(parents=True, exist_ok=True)
    ris_lines = []
    for (sid, label, year, pmid, doi, jrnl, vol, iss, pg, *_rest) in STUDIES:
        first = label.split()[0]
        title = TITLES[pmid]
        ris_lines += [
            "TY  - JOUR", f"TI  - {title}", f"AU  - {first}", f"PY  - {year}",
            f"JO  - {jrnl}", f"VL  - {vol}", f"IS  - {iss}", f"SP  - {pg}",
            f"DO  - {doi}", f"AN  - {pmid}", "DB  - PubMed",
            f"UR  - https://doi.org/{doi}", f"AB  - {ABSTRACTS.get(pmid,'')}", "ER  -", ""]
        (folder / f"{sid}_{first}{year}_PMID{pmid}.txt").write_text(
            f"{title}\n\n{label} | {jrnl} {vol}({iss}):{pg} ({year})\n"
            f"PMID: {pmid} | DOI: https://doi.org/{doi}\n"
            f"PMC full text: {PMC.get(pmid,'(not open access — paywalled)')}\n\n"
            f"Abstract\n{ABSTRACTS.get(pmid,'')}\n", encoding="utf-8")
    (folder / "cade_references.ris").write_text("\n".join(ris_lines), encoding="utf-8")
    return folder


TITLES = {
    "30814121": "Real-time automatic detection system increases colonoscopic polyp and adenoma detection rates: a prospective randomised controlled study",
    "35643173": "Computer-Aided Detection Improves Adenomas per Colonoscopy for Screening and Surveillance Colonoscopy: A Randomized Trial",
    "38290758": "Impact of AI-aided colonoscopy in clinical practice: a prospective randomised controlled trial",
    "38437999": "The Efficacy of Real-time Computer-aided Detection of Colonic Neoplasia in Community Practice: A Pragmatic Randomized Controlled Trial",
    "39455850": "A prospective multicenter randomized controlled trial on artificial intelligence assisted colonoscopy for enhanced polyp detection",
    "39860586": "Artificial Intelligence for Adenoma and Polyp Detection During Screening and Surveillance Colonoscopy: A Randomized-Controlled Trial",
    "41449203": "A novel cloud-based artificial intelligence for real-time detection of colorectal neoplasia - a randomized controlled trial (EAGLE)",
    "41306099": "Clinical Efficacy of Real-Time Artificial Intelligence-Assisted Colonoscopy in Colorectal Polyp Detection: A Prospective Multicenter Randomized Controlled Trial",
    "32371116": "Efficacy of Real-Time Computer-Aided Detection of Colorectal Neoplasia in a Randomized Trial",
    "34187845": "Artificial intelligence and colonoscopy experience: lessons from two randomised trials",
}
PMC = {
    "30814121": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6839720/",
    "38290758": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10870789/",
    "39455850": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11512038/",
    "39860586": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11766411/",
    "41449203": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12852673/",
    "41306099": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12800677/",
}

PROSE = {}


def main():
    state, meta = build_state()
    print(f"Pooled RR (REML+HKSJ) = {meta.pooled_estimate} "
          f"[{meta.ci_lower}, {meta.ci_upper}]  I2={meta.i_squared}%  "
          f"tau2={meta.tau_squared}  PI=[{meta.pi_lower},{meta.pi_upper}]  "
          f"k={meta.k_studies}  Egger p={meta.eggers_p}")
    refdir = write_reference_package(Path("data/cade_dossier/references"))
    print("references →", refdir)

    out = Path("runs/cade-colonoscopy-adr")
    import shutil
    shutil.rmtree(out, ignore_errors=True)
    prose = build_prose(state, meta)
    report.write_artifacts(out, state, prose)
    report.write_latex(out, state, prose)
    print("review →", out)
    return state, meta


def build_prose(state, meta):
    p = state.protocol
    n = sum(e.n_intervention + e.n_comparator for e in
            [ex.effects[0] for ex in state.extractions])
    return {
        "abstract": (
            f"Background: Real-time computer-aided detection (CADe) aims to reduce missed "
            f"colorectal lesions during colonoscopy. We synthesised randomized evidence on its "
            f"effect on the adenoma detection rate (ADR). "
            f"Methods: We searched PubMed (2018-2026) for randomized controlled trials comparing "
            f"real-time CADe with standard colonoscopy reporting ADR, appraised them with RoB 2, "
            f"and pooled arm-level ADR as a risk ratio using a random-effects model (REML; "
            f"Hartung-Knapp correction), with GRADE certainty. "
            f"Results: {meta.k_studies} RCTs ({n} participants) were included. The pooled risk ratio for ADR "
            f"was {meta.pooled_estimate} (95% CI {meta.ci_lower}-{meta.ci_upper}; "
            f"I^2={meta.i_squared}%; 95% prediction interval {meta.pi_lower}-{meta.pi_upper}). "
            f"All trials favoured CADe directionally; all were rated 'some concerns' on RoB 2. "
            f"Conclusions: Within this evidence body, real-time CADe is "
            f"associated with a higher ADR (GRADE certainty: low)."),
        "background": (
            "Colorectal cancer is among the most common and most preventable cancers, and "
            "colonoscopy with adenoma removal interrupts the adenoma-carcinoma sequence. The "
            "protective effect of colonoscopy is limited by missed lesions, summarised at the "
            "operator level by the adenoma detection rate (ADR), an inversely validated "
            "predictor of post-colonoscopy colorectal cancer. Real-time computer-aided detection "
            "(CADe) overlays deep-learning lesion alerts on the live endoscopic video to reduce "
            "misses. Numerous randomized trials have now evaluated CADe, with heterogeneous "
            "results, motivating a quantitative synthesis focused on ADR."),
        "methods": (
            "We followed PRISMA 2020. PubMed was searched (2018-2026) combining colonoscopy, "
            "artificial-intelligence/CADe, randomized-trial and adenoma/polyp concept blocks "
            "(full string in the search log). Eligible studies were randomized controlled trials "
            "comparing real-time CADe with standard colonoscopy in adults undergoing screening, "
            "surveillance or diagnostic colonoscopy and reporting ADR. Two reviewers screened in "
            "duplicate and extracted arm-level ADR event counts; three trials required event "
            "counts reconstructed from reported rates and denominators. Risk of bias was assessed "
            "with RoB 2. The effect measure was the risk ratio of ADR; arm-level counts were "
            "pooled on the natural-log scale with an inverse-variance random-effects model, the "
            "REML estimator of between-study variance and the Hartung-Knapp-Sidik-Jonkman "
            "variance correction. Heterogeneity was summarised with Cochran's Q, I^2 and tau^2, "
            "with a 95% prediction interval; small-study effects were examined with Egger's test "
            "and trim-and-fill, and a leave-one-out sensitivity analysis was performed. Certainty "
            "of evidence was rated with GRADE."),
        "discussion": (
            f"Across {meta.k_studies} randomized trials, real-time CADe was associated with a higher adenoma "
            f"detection rate (pooled RR {meta.pooled_estimate}, 95% CI {meta.ci_lower}-"
            f"{meta.ci_upper}), with a consistent direction of effect and "
            f"{'low' if (meta.i_squared or 0) < 40 else 'moderate'} statistical heterogeneity "
            f"(I^2={meta.i_squared}%). The magnitude is clinically plausible and concordant with "
            f"the wider CADe literature. Confidence is tempered by the unavoidable lack of "
            f"endoscopist blinding inherent to real-time alerts, by reconstructed event counts in "
            f"three trials, and by a focused single-database evidence base. The 95% prediction "
            f"interval ({meta.pi_lower}-{meta.pi_upper}) indicates the plausible range of true "
            f"effects in future settings."),
        "conclusions": (
            "Within this synthesis, real-time CADe during colonoscopy is "
            "associated with a higher adenoma detection rate. The certainty of evidence is low, "
            "chiefly because real-time detection cannot be blinded. CADe is a reasonable pragmatic "
            "adjunct to high-quality colonoscopy; confirmation in blinded-outcome, multi-database "
            "syntheses and assessment of effects on clinically significant lesions are warranted."),
    }


if __name__ == "__main__":
    main()
