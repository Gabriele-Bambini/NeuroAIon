"""PROSPERO registration export.

PROSPERO has no open submission API, so the engine produces a completed
registration form (Markdown) covering the mandatory fields. The user pastes it
into https://www.crd.york.ac.uk/prospero/ to register the protocol — closing the
PRISMA item 24 loop with a free, manual-submission artefact.
"""
from __future__ import annotations

from datetime import date

from .models import ReviewState


def build_registration(state: ReviewState) -> str:
    p = state.protocol
    pico = p.pico
    sources = ", ".join(p.search.sources)
    inc = "\n".join(f"- {c}" for c in p.inclusion_criteria) or "- (none specified)"
    exc = "\n".join(f"- {c}" for c in p.exclusion_criteria) or "- (none specified)"
    designs = ", ".join(pico.study_designs) or "any"
    return f"""# PROSPERO registration — {p.title}

> Draft registration form. Submit at https://www.crd.york.ac.uk/prospero/
> (free). Fields map to the PROSPERO registration form.

**1. Review title.** {p.title}

**2. Anticipated or actual start date.** {state.created_at[:10]}

**3. Anticipated completion date.** {date.today().isoformat()}

**4. Stage of review at time of registration.** Completed.

**5. Named contact.** {(', '.join(p.authors) + ' — ' if p.authors else '') + (p.authors_contact or "(to be completed)")}

**6. Organisational affiliation.** {p.affiliation or "(to be completed)"}.

**7. Review question.** {p.question}

**8. Searches.** The following sources were searched: {sources}
(from {p.search.date_from} to {p.search.date_to}); languages: {", ".join(p.search.languages)}.
Records were de-duplicated and screened in duplicate.

**9. Condition or domain being studied.** {pico.population}

**10. Participants/population.** {pico.population}

**11. Intervention(s)/exposure(s).** {pico.intervention}

**12. Comparator(s)/control.** {pico.comparator}

**13. Types of study to be included.** {designs}

**14. Inclusion criteria.**
{inc}

**15. Exclusion criteria.**
{exc}

**16. Main outcome(s).** {pico.outcome}

**17. Data extraction.** Structured extraction of design, population, intervention,
comparator, sample size, and quantitative effect estimates.

**18. Risk of bias assessment.** {p.risk_of_bias.tool}; certainty of evidence by GRADE.

**19. Strategy for data synthesis.** {p.synthesis.model}-effects inverse-variance
meta-analysis of the {p.synthesis.effect_measure} where data permit; heterogeneity
by I-squared and tau-squared; publication bias by Egger's test and funnel plot;
otherwise narrative synthesis.

**20. Analysis of subgroups or subsets.** None pre-specified.

**21. Registration.** {p.registration}

**22. Dissemination plans.** Peer-reviewed manuscript and conference presentation.

**23. Keywords.** {", ".join(t for group in p.search.keywords for t in group)}
"""
