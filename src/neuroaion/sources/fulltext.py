"""Full-text retrieval (PRISMA item 16b — "reports sought / retrieved").

Resolves an included record to a PubMed Central open-access full text (the same
corpus the PMC MCP server exposes) and, for preprints, to the bioRxiv/medRxiv
full text via Europe PMC. Falls back gracefully to the abstract when no
open-access full text exists, so eligibility and extraction always have the best
available text without the pipeline ever stalling on a paywalled report.

Sources used (all public, no key required):
  • NCBI ID Converter  → map DOI/PMID to a PMCID
  • Europe PMC fullTextXML → JATS XML body for PMC OA articles and preprints
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from ..models import Record
from .base import http_get

IDCONV = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
EPMC_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{src}/{id}/fullTextXML"


@dataclass
class FullText:
    text: str = ""
    retrieved: bool = False
    source: str = ""        # "pmc" | "preprint" | "abstract" | "none"
    pmcid: str = ""


def _resolve_pmcid(record: Record) -> str:
    """Map a record's DOI or PMID to a PMCID via the NCBI ID Converter."""
    ident = ""
    idtype = ""
    if record.source == "pubmed" and record.source_id:
        ident, idtype = record.source_id, "pmid"
    elif record.doi:
        ident, idtype = record.doi, "doi"
    else:
        return ""
    try:
        data = http_get(IDCONV, {"ids": ident, "idtype": idtype,
                                 "format": "json", "tool": "neuroaion"}).json()
        for rec in data.get("records", []):
            if rec.get("pmcid"):
                return rec["pmcid"]
    except Exception:  # noqa: BLE001
        return ""
    return ""


def _jats_body_text(xml_text: str) -> str:
    """Extract readable body text (sections, paragraphs, tables) from JATS XML."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    parts: list[str] = []

    def walk(elem, in_body=False):
        tag = elem.tag.split("}")[-1]
        if tag in {"body"}:
            in_body = True
        if in_body and tag in {"title", "p", "td", "th", "label", "caption"}:
            txt = "".join(elem.itertext()).strip()
            if txt:
                parts.append(txt)
            return
        for child in elem:
            walk(child, in_body)

    walk(root)
    text = "\n".join(parts)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _fetch_epmc_fulltext(src: str, ext_id: str) -> str:
    url = EPMC_FULLTEXT.format(src=src, id=ext_id)
    try:
        resp = http_get(url, accept="application/xml")
        return _jats_body_text(resp.text)
    except Exception:  # noqa: BLE001
        return ""


def retrieve(record: Record, *, max_chars: int = 40000) -> FullText:
    """Best-effort full-text retrieval for one record.

    Order: PMC open-access full text → preprint full text → abstract fallback.
    """
    # 1) Peer-reviewed open-access full text via PMC.
    pmcid = _resolve_pmcid(record)
    if pmcid:
        body = _fetch_epmc_fulltext("PMC", pmcid)
        if body:
            return FullText(text=body[:max_chars], retrieved=True, source="pmc", pmcid=pmcid)

    # 2) Preprint full text (bioRxiv/medRxiv indexed in Europe PMC as PPR).
    if record.source == "biorxiv" and record.source_id:
        body = _fetch_epmc_fulltext("PPR", record.source_id)
        if body:
            return FullText(text=body[:max_chars], retrieved=True, source="preprint")

    # 3) Fallback: the abstract is the best available text (report not fully retrieved).
    if record.abstract:
        return FullText(text=record.abstract, retrieved=False, source="abstract")

    return FullText(text="", retrieved=False, source="none")


# ── Pluggable retrievers ─────────────────────────────────────────────────────
# The engine retrieves full text through whichever channel the host can reach.
# On a machine with open egress, HttpFullTextRetriever talks to PMC/Europe PMC
# directly. Inside an agent host that exposes MCP literature tools (e.g. the PMC
# and bioRxiv MCP servers), McpFullTextRetriever binds those tools instead —
# same result, no direct outbound HTTP required.
class FullTextRetriever(Protocol):
    def retrieve(self, record: Record) -> FullText: ...


class HttpFullTextRetriever:
    """Default retriever — direct HTTP to NCBI ID-converter + Europe PMC."""

    def __init__(self, max_chars: int = 40000):
        self.max_chars = max_chars

    def retrieve(self, record: Record) -> FullText:
        return retrieve(record, max_chars=self.max_chars)


class McpFullTextRetriever:
    """Retriever backed by injected MCP tool callables.

    A host that has the PMC / bioRxiv MCP servers wires its tools in as plain
    callables, so the engine works in restricted-egress environments where only
    the sanctioned MCP channel can reach the internet.

    The adapter normalises the real MCP return shapes, so you can pass the tool
    results through verbatim:
      • ``convert_ids`` may return a ``list[dict]`` or the PMC ``convert_article_ids``
        response ``{"records": [{"pmcid": ...}]}`` (or its JSON string).
      • ``get_full_text`` may return body text, or the ``get_full_text_article``
        response ``{"articles": [{"full_text": ...}]}`` (or its JSON string).

    Parameters
    ----------
    convert_ids:
        ``convert_ids(ids: list[str], id_type: str) -> records`` — mirrors the
        PMC MCP ``convert_article_ids`` tool.
    get_full_text:
        ``get_full_text(pmc_ids: list[str]) -> body`` — mirrors ``get_full_text_article``.
    """

    def __init__(self, *, convert_ids: Callable[[list[str], str], object],
                 get_full_text: Callable[[list[str]], object],
                 max_chars: int = 40000):
        self._convert = convert_ids
        self._full = get_full_text
        self.max_chars = max_chars

    def retrieve(self, record: Record) -> FullText:
        ident, idtype = "", ""
        if record.source == "pubmed" and record.source_id:
            ident, idtype = record.source_id, "pmid"
        elif record.doi:
            ident, idtype = record.doi, "doi"

        pmcid = ""
        if ident:
            try:
                pmcid = _first_pmcid(self._convert([ident], idtype))
            except Exception:  # noqa: BLE001
                pmcid = ""
        if pmcid:
            try:
                body = _mcp_body_text(self._full([pmcid]))
                if body:
                    return FullText(text=body[:self.max_chars], retrieved=True,
                                    source="pmc", pmcid=pmcid)
            except Exception:  # noqa: BLE001
                pass
        if record.abstract:
            return FullText(text=record.abstract, retrieved=False, source="abstract")
        return FullText(text="", retrieved=False, source="none")


def _as_dict(result: object) -> object:
    """Accept a JSON string, a dict, or an SDK object and return a dict/list."""
    import json as _json
    if isinstance(result, str):
        try:
            return _json.loads(result)
        except ValueError:
            return result
    return result


def _first_pmcid(result: object) -> str:
    data = _as_dict(result)
    records = data.get("records", data) if isinstance(data, dict) else data
    if isinstance(records, list):
        for rec in records:
            if isinstance(rec, dict) and rec.get("pmcid"):
                return rec["pmcid"]
    return ""


def _mcp_body_text(result: object) -> str:
    data = _as_dict(result)
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, dict):
        arts = data.get("articles")
        if isinstance(arts, list) and arts:
            parts = [a.get("full_text") or a.get("text") or ""
                     for a in arts if isinstance(a, dict)]
            return "\n\n".join(p for p in parts if p).strip()
        return (data.get("full_text") or data.get("text") or "").strip()
    return ""
