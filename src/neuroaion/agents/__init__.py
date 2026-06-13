"""The ten specialised review agents.

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

# The official roster — order is the pipeline order.
ROSTER = [
    ("1", "ProtocolArchitect", "Protocol, PICO & eligibility (PRISMA 5–7)"),
    ("2", "SearchStrategist", "Per-database search & identification (PRISMA 7–8)"),
    ("3", "DeduplicationAgent", "Cross-source de-duplication (PRISMA 16a)"),
    ("4", "TitleAbstractScreener", "Reviewer 1 title/abstract screening (PRISMA 8)"),
    ("5", "DualScreenAdjudicator", "Reviewer 2 + conflict resolution, Cohen's κ (PRISMA 8,16)"),
    ("6", "FullTextEligibility", "Full-text eligibility & exclusion reasons (PRISMA 16b)"),
    ("7", "DataExtractor", "Structured data extraction (PRISMA 9–10)"),
    ("8", "RiskOfBiasAssessor", "Risk of bias & GRADE (PRISMA 11–12,15)"),
    ("9", "EvidenceSynthesizer", "Synthesis & meta-analysis (PRISMA 13,20)"),
    ("10", "PRISMAReporter", "Flow diagram, checklist & manuscript (PRISMA 14–27)"),
]

__all__ = [
    "ProtocolArchitect", "SearchStrategist", "DeduplicationAgent",
    "TitleAbstractScreener", "DualScreenAdjudicator", "FullTextEligibility",
    "DataExtractor", "RiskOfBiasAssessor", "EvidenceSynthesizer",
    "PRISMAReporter", "ROSTER",
]
