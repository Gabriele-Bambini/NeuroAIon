"""NeuroAIon — a full-auto, PRISMA 2020-compliant systematic review engine.

A conductor orchestrates eight specialised Claude agents through the complete
systematic-review workflow: protocol → search → de-duplication → dual screening
→ full-text eligibility → data extraction → risk-of-bias → synthesis → PRISMA
reporting. Deterministic computations (deduplication, meta-analysis, PRISMA flow
counts) are performed in Python; the language model is used only for judgement
and narrative, never to invent statistics.
"""

__version__ = "0.1.0"
