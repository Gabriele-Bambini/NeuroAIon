#!/usr/bin/env python3
"""Download the open-access full texts of the 8 CADe trials into ./review_pdfs/.

Run this on your own machine (it needs internet). It fetches the legal
open-access copies from Europe PMC / PMC for the 6 OA trials; the 2 paywalled
trials (Shaukat/SKOUT 2022, Thiruvengadam 2024) are not downloadable without your
institutional access — open them from the DOI and export/save the PDF yourself.

    python fetch_oa_fulltext.py
    # then run the review with:  fulltext_dir: "review_pdfs"

No credentials are used; only public Europe PMC / PMC endpoints.
"""
from pathlib import Path
import urllib.request

OUT = Path(__file__).parent / "review_pdfs"
OUT.mkdir(exist_ok=True)

# (label, PMID, PMCID or None, DOI, open_access?)
STUDIES = [
    ("S01_Wang2019",        "30814121", "PMC6839720",  "10.1136/gutjnl-2018-317500", True),
    ("S02_Shaukat2022",     "35643173", None,          "10.1053/j.gastro.2022.05.028", False),
    ("S03_Schoeler2024",    "38290758", "PMC10870789", "10.1136/bmjgast-2023-001247", True),
    ("S04_Thiruvengadam2024","38437999", None,         "10.1016/j.cgh.2024.02.021", False),
    ("S05_Park2024",        "39455850", "PMC11512038", "10.1038/s41598-024-77079-1", True),
    ("S06_AlAli2025",       "39860586", "PMC11766411", "10.3390/jcm14020581", True),
    ("S07_EAGLE2025",       "41449203", "PMC12852673", "10.1038/s41746-025-02270-1", True),
    ("S08_GutLiver2025",    "41306099", "PMC12800677", "10.5009/gnl250369", True),
]
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/{src}/{pid}/fullTextXML"
PMC_PDF = "https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
UA = {"User-Agent": "CADe-review/1.0 (mailto:02gabrielebambini@gmail.com)"}


def get(url, dest):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        dest.write_bytes(r.read())


def main():
    for label, pmid, pmcid, doi, oa in STUDIES:
        if not oa or not pmcid:
            print(f"⚠ {label}: paywalled — open https://doi.org/{doi} and save the PDF "
                  f"into {OUT}/ yourself (institutional access).")
            continue
        # 1) Europe PMC full-text XML (always works for OA).
        try:
            get(EPMC.format(src="PMC", pid=pmcid), OUT / f"{label}_{pmcid}.xml")
            print(f"✓ {label}: Europe PMC full-text XML")
        except Exception as e:
            print(f"… {label}: XML failed ({e})")
        # 2) Try the PMC PDF (may require a browser; best-effort).
        try:
            get(PMC_PDF.format(pmcid=pmcid), OUT / f"{label}_{pmcid}.pdf")
            print(f"✓ {label}: PMC PDF")
        except Exception:
            print(f"… {label}: PMC PDF not fetched (open {PMC_PDF.format(pmcid=pmcid)} in a browser)")
    print(f"\nDone → {OUT}")


if __name__ == "__main__":
    main()
