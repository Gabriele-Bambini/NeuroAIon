"""The eight specialised review agents.

Each agent owns one PRISMA-aligned responsibility and communicates only through
the typed models in ``neuroaion.models``. The orchestrator wires them together.
"""
from .adjudicator import DualScreenAdjudicator
from .extraction import DataExtractor
from .fulltext import FullTextEligibility
from .protocol import ProtocolArchitect
from .reporter import PRISMAReporter
from .rob import RiskOfBiasAssessor
from .screen_ta import TitleAbstractScreener
from .search import SearchStrategist
from .synthesis import EvidenceSynthesizer
from .dedup_agent import DeduplicationAgent

# The official roster — eight logical agents (deterministic helpers such as
# de-duplication and conflict-resolution run inside the owning agent).
ROSTER = [
    ("1", "ProtocolArchitect", "Protocol, PICO & eligibility (PRISMA 4–7)"),
    ("2", "SearchStrategist", "Search, identification & de-duplication (PRISMA 7–8, 16a)"),
    ("3", "TitleAbstractScreener", "Dual independent screening + Cohen's κ (PRISMA 8)"),
    ("4", "EligibilityAdjudicator", "Conflict resolution, full-text retrieval & eligibility (PRISMA 8, 16b)"),
    ("5", "DataExtractor", "Structured data extraction (PRISMA 9–10)"),
    ("6", "RiskOfBiasAssessor", "Risk of bias & GRADE certainty (PRISMA 11–12, 15)"),
    ("7", "EvidenceSynthesizer", "Meta-analysis, heterogeneity & publication bias (PRISMA 13–14, 20)"),
    ("8", "PRISMAReporter", "Flow diagram, manuscript & PDF/LaTeX/PROSPERO (PRISMA 16–27)"),
]

__all__ = [
    "ProtocolArchitect", "SearchStrategist", "DeduplicationAgent",
    "TitleAbstractScreener", "DualScreenAdjudicator", "FullTextEligibility",
    "DataExtractor", "RiskOfBiasAssessor", "EvidenceSynthesizer",
    "PRISMAReporter", "ROSTER",
]
