# CADe colonoscopy & ADR — review package

A systematic review and meta-analysis of real-time computer-aided detection (CADe)
during colonoscopy on the adenoma detection rate (ADR), from 8 randomized trials.

## Contents
- `review/paper.pdf` — the formatted manuscript (open this).
- `review/paper.tex` + `references.bib` — LaTeX source.
- `review/figures/` — forest, funnel, PRISMA flow, risk-of-bias (vector PDF + PNG).
- `review/documents/` — full PRISMA dossier: protocol, search log, screening log,
  data extraction, GRADE Summary of Findings, PRISMA 27-item + abstract checklists,
  declarations, and `rob_worksheets/` (one completed RoB 2 form per study).
- `references/` — the 8 trials: import-ready `cade_references.ris` + per-study metadata.
- `rob_blank_templates/` — blank fill-in worksheets for every RoB instrument
  (RoB 2, ROBINS-I, ROBINS-E, QUADAS-2, Newcastle-Ottawa, AMSTAR-2, PROBAST, JBI).

## Headline result
Pooled risk ratio for ADR (CADe vs standard colonoscopy): **RR 1.243 (95% CI 1.130–1.367)**,
random-effects (REML + Hartung–Knapp), I² = 42%, k = 8, 6503 participants. 95% prediction
interval 1.015–1.522; Egger p = 0.70. GRADE certainty: **Low** (downgraded for risk of bias).

## Risk of bias
Each trial's RoB 2 worksheet (`review/documents/rob_worksheets/`) was completed from the
full text: signalling questions answered with the supporting quotation, domain judgments
derived, overall judgment assigned. All eight trials are "some concerns" overall (the
endoscopist cannot be blinded to a real-time detector); randomization/concealment was rated
"Low" where central or web-based concealed block randomization was documented (e.g. EAGLE,
Gut & Liver, SKOUT).
