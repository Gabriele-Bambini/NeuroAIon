"""Deterministic risk-of-bias judgement engine.

The model answers factual SIGNALLING QUESTIONS (see :mod:`neuroaion.rob_tools`);
this module applies the *published algorithm* to derive each domain judgement
and the overall judgement in pure Python. Separating "answer the facts" (the
model) from "apply the algorithm" (deterministic code) is exactly how RoB 2 and
ROBINS-I are meant to be operated, and it is what makes the output differentiated
and reproducible instead of a flat "some concerns" for everything.

Per-instrument logic
--------------------
RoB2
    Each signalling question has a *polarity*: for most, an unfavourable answer
    is No/Probably-no; for a documented subset (1.3, 2.3/2.4/2.7, 3.3/3.4,
    4.1–4.5, 5.2/5.3) an unfavourable answer is Yes/Probably-yes. A domain is
    judged ``high`` if a critical question flags clear risk, ``low`` if every
    key question is favourable with no "No information", otherwise
    ``some concerns``. Overall: ``low`` if all domains low; ``high`` if any
    domain high OR at least three domains raise "some concerns"; else
    ``some concerns``.
ROBINS-I / ROBINS-E
    Native five-level ladder (low / moderate / serious / critical / no
    information) derived per domain, then collapsed to the stored three-level
    scale (moderate→some concerns; serious/critical→high). Overall takes the
    worst domain (the ROBINS rule).
QUADAS-2
    Risk-of-bias signalling questions per domain plus applicability concerns;
    ``high`` if any answer flags risk, ``low`` if all favourable, else
    ``some concerns``/unclear. Overall = worst domain.
Newcastle-Ottawa
    Star-count per section mapped to a 3-level judgement, overall by good/fair/
    poor thresholds.
Generic
    Majority vote over the three generic signalling answers.

Public surface
--------------
``derive_domain_judgement(tool, domain, answers) -> (judgement, support)``
``derive_overall(tool, domain_judgements) -> str``
``build_assessment(tool, study_label, uid, signalling_by_domain, …) -> RoBAssessment``
"""
from __future__ import annotations

from typing import Optional

from . import rob_tools as T
from .models import RoBAssessment, RoBDomain

# Stored 3-level scale.
LOW, SOME, HIGH = "low", "some concerns", "high"
_ORDER = {LOW: 0, SOME: 1, HIGH: 2}

# RoB 2 signalling questions whose *risk-raising* answer is Yes/Probably-yes
# (rather than the usual No/Probably-no). Keyed by SQ code. Includes the
# "awareness" questions (2.1/2.2/4.3) where Yes raises risk.
_ROB2_RISK_WHEN_YES = {
    "1.3", "2.1", "2.2", "2.3", "2.4", "2.7", "3.3", "3.4",
    "4.1", "4.2", "4.3", "4.4", "4.5", "5.2", "5.3",
}
# The small set of "key" SQs that, if clearly unfavourable, push a RoB2 domain
# straight to ``high``.
_ROB2_CRITICAL = {
    "1.2": "concealment failed",        # allocation not concealed
    "1.3": "baseline imbalance",        # baseline differences signal a problem
    "2.5": "deviations unbalanced",     # imbalanced deviations affecting outcome
    "3.4": "outcome-dependent missingness",
    "4.1": "inappropriate outcome measure",
    "4.5": "assessment influenced by knowledge",
    "5.2": "selective outcome reporting",
    "5.3": "selective analysis reporting",
}


def _norm(ans: str) -> str:
    a = (ans or "").strip()
    if not a:
        return T.NO_INFO
    low = a.lower()
    if low in ("ni", "no information", "no information / ni", "unclear", "unknown"):
        return T.NO_INFO
    for opt in T.ANSWER_OPTIONS:
        if low == opt.lower():
            return opt
    # Tolerate "probably-yes", "y", "n".
    if low in ("y", "yes"):
        return "Yes"
    if low in ("n", "no"):
        return "No"
    if low in ("py", "probably-yes", "probably yes"):
        return "Probably yes"
    if low in ("pn", "probably-no", "probably no"):
        return "Probably no"
    return a  # keep native ROBINS levels / star tokens verbatim


def _is_favourable(ans: str, risk_when_yes: bool) -> Optional[bool]:
    """True=favourable, False=unfavourable, None=no information.

    ``risk_when_yes`` flips the polarity for questions where a Yes is the
    risk-raising answer.
    """
    a = _norm(ans)
    if a == T.NO_INFO:
        return None
    yes_like = a in ("Yes", "Probably yes")
    no_like = a in ("No", "Probably no")
    if not (yes_like or no_like):
        return None
    if risk_when_yes:
        return no_like      # favourable when "No"
    return yes_like         # favourable when "Yes"


def _sq_code(question: str) -> str:
    return T.sq_number(question) if hasattr(T, "sq_number") else _fallback_code(question)


def _fallback_code(question: str) -> str:
    head = question.strip().split(" ", 1)[0]
    return head if (head[:1].isdigit() and "." in head) else ""


# Per-domain "key" (non-conditional) signalling questions that always count.
# Conditional follow-ups (e.g. 2.3-2.5, 3.2-3.4, 4.4-4.5) only matter when their
# branch is actually triggered, so they are evaluated via the branch logic below
# rather than penalising the domain as "no information" when not reached.
_ROB2_KEY = {
    "Randomization process": ["1.1", "1.2", "1.3"],
    "Deviations from intended interventions": ["2.1", "2.2", "2.6"],
    "Missing outcome data": ["3.1"],
    "Measurement of the outcome": ["4.1", "4.2", "4.3"],
    "Selection of the reported result": ["5.1", "5.2", "5.3"],
}


def _verdict(code: str, raw: str) -> Optional[bool]:
    return _is_favourable(raw, code in _ROB2_RISK_WHEN_YES)


def _get(answers: dict[str, str], code: str, question: str = "") -> str:
    return answers.get(code, answers.get(question, ""))


# ── RoB 2 ────────────────────────────────────────────────────────────────────
def _derive_rob2(domain: str, answers: dict[str, str]) -> tuple[str, str]:
    """Branch-aware RoB 2 algorithm: only count signalling questions that are
    reached, so conditional follow-ups never falsely deflate a clean domain."""
    qmap = {_sq_code(q): q for q in T.questions_for("RoB2", domain)}
    key_codes = _ROB2_KEY.get(domain, list(qmap))

    fav = unfav = ni = 0
    critical_hits: list[str] = []
    notes: list[str] = []
    for code in key_codes:
        raw = _get(answers, code, qmap.get(code, ""))
        v = _verdict(code, raw)
        if v is None:
            ni += 1
        elif v:
            fav += 1
        else:
            unfav += 1
            if code in _ROB2_CRITICAL:
                critical_hits.append(f"{code} ({_ROB2_CRITICAL[code]})")
            notes.append(f"{code}={_norm(raw)}")

    # Evaluate any *answered* conditional follow-up that points to clear risk.
    for code, q in qmap.items():
        if code in key_codes:
            continue
        raw = _get(answers, code, q)
        if _norm(raw) == T.NO_INFO:
            continue                     # unreached / unanswered → ignore
        v = _verdict(code, raw)
        if v is False:
            unfav += 1
            if code in _ROB2_CRITICAL:
                critical_hits.append(f"{code} ({_ROB2_CRITICAL[code]})")
            notes.append(f"{code}={_norm(raw)}")

    if critical_hits:
        return HIGH, ("High risk on a key signalling question: "
                      + "; ".join(critical_hits) + ".")
    if unfav:
        return SOME, ("Some concerns: unfavourable answer(s) on "
                      + ", ".join(notes) + ".")
    if fav == 0:
        return SOME, "Some concerns: insufficient information to judge this domain."
    if ni:
        return SOME, (f"Some concerns: {ni} key signalling question(s) lacked "
                      "information although the rest were favourable.")
    return LOW, "Low risk: all key signalling questions answered favourably."


# ── ROBINS-I / ROBINS-E (native 5-level) ─────────────────────────────────────
def _derive_robins(tool: str, domain: str, answers: dict[str, str]) -> tuple[str, str]:
    questions = T.questions_for(tool, domain)
    fav = unfav = ni = 0
    notes: list[str] = []
    for q in questions:
        code = _sq_code(q)
        raw = answers.get(code, answers.get(q, ""))
        # For ROBINS, "Yes/Probably yes" generally means a well-handled domain,
        # but the confounding-potential first question is risk-raising on Yes.
        risk_when_yes = code.endswith(".1") and domain == "Confounding"
        verdict = _is_favourable(raw, risk_when_yes)
        if verdict is None:
            ni += 1
        elif verdict:
            fav += 1
        else:
            unfav += 1
            notes.append(f"{code or q[:18]}={_norm(raw)}")

    total = fav + unfav + ni
    if total == 0 or ni == total:
        native = "no information"
    elif unfav >= 2:
        native = "serious"
    elif unfav == 1:
        native = "moderate"
    elif ni and fav:
        native = "moderate"
    else:
        native = "low"

    stored = _robins_to_stored(native)
    txt = {
        "low": "Low risk of bias for this domain (ROBINS-I/E).",
        "moderate": "Moderate risk of bias (sound for a non-randomized study "
                    "but not comparable to a well-performed RCT): " + "; ".join(notes),
        "serious": "Serious risk of bias on this domain: " + "; ".join(notes),
        "critical": "Critical risk of bias on this domain: " + "; ".join(notes),
        "no information": "No information to judge this domain.",
    }[native]
    return stored, f"[native: {native}] {txt}".strip()


def _robins_to_stored(native: str) -> str:
    return {
        "low": LOW, "moderate": SOME, "serious": HIGH,
        "critical": HIGH, "no information": SOME,
    }.get(native, SOME)


# ── QUADAS-2 ─────────────────────────────────────────────────────────────────
def _derive_quadas(domain: str, answers: dict[str, str]) -> tuple[str, str]:
    questions = T.questions_for("QUADAS-2", domain)
    # In QUADAS-2 every risk-of-bias signalling question is phrased so that
    # "Yes" is the low-risk answer.
    fav = unfav = ni = 0
    notes: list[str] = []
    for q in questions:
        raw = answers.get(q, "")
        verdict = _is_favourable(raw, risk_when_yes=False)
        if verdict is None:
            ni += 1
        elif verdict:
            fav += 1
        else:
            unfav += 1
            notes.append(q[:40])
    # Applicability concerns (do not change RoB level, recorded in support text).
    applic = T.APPLICABILITY.get("QUADAS-2", {}).get(domain, [])
    applic_flags = [a for a in applic
                    if _is_favourable(answers.get(a, ""), risk_when_yes=True) is False]

    if unfav:
        j, base = HIGH, "High risk: " + "; ".join(notes)
    elif ni and fav == 0:
        j, base = SOME, "Unclear risk: insufficient information."
    elif ni:
        j, base = SOME, "Some concerns: one or more items lacked information."
    else:
        j, base = LOW, "Low risk: all signalling questions favourable."
    if applic_flags:
        base += " Applicability concern noted."
    return j, base


# ── Newcastle-Ottawa (stars) ─────────────────────────────────────────────────
# Per section: count "Yes" (star awarded). Section thresholds → 3-level.
_NOS_MAX = {"Selection": 4, "Comparability": 2, "Outcome/Exposure": 3}


def _derive_nos(domain: str, answers: dict[str, str]) -> tuple[str, str]:
    questions = T.questions_for("Newcastle-Ottawa", domain)
    stars = sum(1 for q in questions if _norm(answers.get(q, "")) in ("Yes", "Probably yes"))
    mx = _NOS_MAX.get(domain, len(questions))
    if mx and stars >= mx - 0:
        j = LOW
    elif stars >= max(1, mx - 1):
        j = SOME
    else:
        j = HIGH
    return j, f"Newcastle-Ottawa: {stars}/{mx} stars awarded for {domain}."


# ── Generic fallback ─────────────────────────────────────────────────────────
def _derive_generic(tool: str, domain: str, answers: dict[str, str]) -> tuple[str, str]:
    questions = T.questions_for(tool, domain)
    fav = unfav = ni = 0
    for q in questions:
        verdict = _is_favourable(answers.get(q, answers.get(_sq_code(q), "")),
                                 risk_when_yes=False)
        if verdict is None:
            ni += 1
        elif verdict:
            fav += 1
        else:
            unfav += 1
    if unfav > fav:
        return HIGH, f"{tool}: majority of items for '{domain}' flag a problem."
    if unfav or (ni and fav == 0):
        return SOME, f"{tool}: some concerns or missing information for '{domain}'."
    if ni:
        return SOME, f"{tool}: partial information for '{domain}'."
    return LOW, f"{tool}: '{domain}' adequately addressed."


# ── Public derivation API ────────────────────────────────────────────────────
def derive_domain_judgement(tool: str, domain: str,
                            answers: dict[str, str]) -> tuple[str, str]:
    """Derive (judgement, support_for_judgement) for one domain from answers."""
    answers = answers or {}
    if tool == "RoB2":
        return _derive_rob2(domain, answers)
    if tool in ("ROBINS-I", "ROBINS-E"):
        return _derive_robins(tool, domain, answers)
    if tool == "QUADAS-2":
        return _derive_quadas(domain, answers)
    if tool == "Newcastle-Ottawa":
        return _derive_nos(domain, answers)
    return _derive_generic(tool, domain, answers)


def derive_overall(tool: str, domain_judgements: list[str]) -> str:
    """Derive the overall judgement from the list of stored domain judgements."""
    js = [j for j in domain_judgements if j in _ORDER] or [SOME]
    if tool in ("ROBINS-I", "ROBINS-E", "QUADAS-2", "Newcastle-Ottawa"):
        # Worst-domain rule.
        return max(js, key=lambda j: _ORDER[j])
    # RoB 2 algorithm.
    if any(j == HIGH for j in js):
        return HIGH
    n_some = sum(1 for j in js if j == SOME)
    if n_some >= 3:
        return HIGH
    if n_some >= 1:
        return SOME
    return LOW


def _overall_rationale(tool: str, judgements: list[str], overall: str) -> str:
    n_low = judgements.count(LOW)
    n_some = judgements.count(SOME)
    n_high = judgements.count(HIGH)
    counts = f"{n_low} low, {n_some} some concerns, {n_high} high"
    if overall == LOW:
        return f"Overall low risk of bias ({tool}): all domains low ({counts})."
    if overall == HIGH:
        if n_high:
            return (f"Overall high risk of bias ({tool}): at least one domain is "
                    f"high ({counts}).")
        return (f"Overall high risk of bias ({tool}): multiple domains raise some "
                f"concerns ({counts}).")
    return (f"Overall some concerns ({tool}): at least one domain raises concerns "
            f"but none is high ({counts}).")


# ── Assembly ─────────────────────────────────────────────────────────────────
def build_assessment(tool: str, study_label: str, uid: str,
                     signalling_by_domain: dict[str, dict[str, str]],
                     extra_rationale: str = "") -> RoBAssessment:
    """Assemble a full :class:`RoBAssessment` from per-domain signalling answers.

    ``signalling_by_domain`` maps domain name → {question-or-code: answer}.
    Missing domains / answers are treated as "No information" so the result is
    always complete and never crashes on partial input.
    """
    signalling_by_domain = signalling_by_domain or {}
    domains_out: list[RoBDomain] = []
    judgements: list[str] = []

    for domain in T.domains_for(tool):
        answers = signalling_by_domain.get(domain, {}) or {}
        # Normalise the stored answers to canonical question keys where possible.
        stored_answers = _stored_answers(tool, domain, answers)
        judgement, support = derive_domain_judgement(tool, domain, answers)
        rationale = _domain_rationale(tool, domain, judgement, stored_answers)
        domains_out.append(RoBDomain(
            name=domain,
            judgement=judgement,
            rationale=rationale,
            support_for_judgement=support,
            signalling_answers=stored_answers,
        ))
        judgements.append(judgement)

    overall = derive_overall(tool, judgements)
    rationale = _overall_rationale(tool, judgements, overall)
    if extra_rationale:
        rationale = f"{rationale} {extra_rationale}".strip()
    return RoBAssessment(
        uid=uid, study_label=study_label, tool=tool,
        domains=domains_out, overall=overall, rationale=rationale,
    )


def _stored_answers(tool: str, domain: str, answers: dict[str, str]) -> dict[str, str]:
    """Return a complete {question: normalized-answer} map for storage.

    Every signalling question for the domain is present; unanswered ones are
    recorded as "No information" so the audit trail is explicit.
    """
    out: dict[str, str] = {}
    for q in T.questions_for(tool, domain):
        code = _sq_code(q)
        raw = answers.get(q, answers.get(code, ""))
        out[q] = _norm(raw)
    # Preserve any applicability-concern answers (QUADAS-2) verbatim.
    for a in T.APPLICABILITY.get(tool, {}).get(domain, []):
        if a in answers:
            out[a] = _norm(answers[a])
    return out


def _domain_rationale(tool: str, domain: str, judgement: str,
                      stored_answers: dict[str, str]) -> str:
    answered = sum(1 for v in stored_answers.values() if v != T.NO_INFO)
    total = len(stored_answers)
    return (f"{tool} domain '{domain}' judged {judgement} on the basis of "
            f"{answered}/{total} signalling questions with information.")
