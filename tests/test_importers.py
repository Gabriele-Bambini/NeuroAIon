"""Citation-file importers — RIS, BibTeX, MEDLINE/NBIB, EndNote XML, CSV.

These prove the legitimate "use my institutional access" path: a reviewer exports
search results from a subscription database and the engine ingests them. All
offline / hermetic — no network, no credentials.
"""
from neuroaion.sources import importers


RIS = """TY  - JOUR
TI  - Anodal tDCS over the DLPFC improves working memory
AU  - Rossi, Anna
AU  - Bianchi, Luca
PY  - 2021
JO  - Journal of Cognitive Neuroscience
VL  - 33
IS  - 4
SP  - 511
EP  - 525
DO  - 10.1234/jcn.2021.0042
AB  - We tested anodal tDCS in a sham-controlled crossover trial.
UR  - https://doi.org/10.1234/jcn.2021.0042
DB  - Scopus
ER  -

TY  - CONF
TI  - Sheaf neural networks for gene regulatory network inference
AU  - Doe, Jane
PY  - 2024
DO  - 10.5555/conf.2024.7
ER  -
"""

BIBTEX = r"""
@article{rossi2021tdcs,
  title = {Anodal {tDCS} over the {DLPFC} improves working memory},
  author = {Rossi, Anna and Bianchi, Luca},
  journal = {Journal of Cognitive Neuroscience},
  year = {2021},
  volume = {33},
  number = {4},
  pages = {511--525},
  doi = {10.1234/jcn.2021.0042},
  pmid = {34000000},
  abstract = {A sham-controlled crossover trial.}
}

@inproceedings{doe2024sheaf,
  title = {Sheaf neural networks for GRN inference},
  author = {Doe, Jane},
  booktitle = {Proceedings of NeurIPS},
  year = {2024},
  doi = {10.5555/conf.2024.7}
}
"""

NBIB = """PMID- 34000000
TI  - Anodal tDCS over the DLPFC improves working memory
      in healthy adults.
AB  - We tested anodal tDCS in a sham-controlled crossover trial
      with twenty participants.
FAU - Rossi, Anna
FAU - Bianchi, Luca
DP  - 2021 Apr
TA  - J Cogn Neurosci
JT  - Journal of Cognitive Neuroscience
VI  - 33
IP  - 4
PG  - 511-525
AID - 10.1234/jcn.2021.0042 [doi]

PMID- 35000001
TI  - A second relevant trial.
DP  - 2022
"""

ENDNOTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<xml><records>
 <record>
  <titles><title>Anodal tDCS over the DLPFC improves working memory</title>
          <secondary-title>Journal of Cognitive Neuroscience</secondary-title></titles>
  <contributors><authors><author>Rossi, Anna</author><author>Bianchi, Luca</author></authors></contributors>
  <dates><year>2021</year></dates>
  <periodical><full-title>Journal of Cognitive Neuroscience</full-title></periodical>
  <volume>33</volume><number>4</number><pages>511-525</pages>
  <electronic-resource-num>10.1234/jcn.2021.0042</electronic-resource-num>
  <abstract>A sham-controlled crossover trial.</abstract>
  <accession-num>34000000</accession-num>
  <remote-database-name>PubMed</remote-database-name>
  <urls><related-urls><url>https://doi.org/10.1234/jcn.2021.0042</url></related-urls></urls>
 </record>
</records></xml>
"""

CSV_SCOPUS = (
    "Authors,Title,Year,Source title,Volume,Issue,DOI,Abstract,PubMed ID\n"
    "Rossi A.; Bianchi L.,Anodal tDCS over the DLPFC improves working memory,2021,"
    "Journal of Cognitive Neuroscience,33,4,10.1234/jcn.2021.0042,A crossover trial.,34000000\n"
)


def test_ris_parses_full_record():
    recs = importers.parse_ris(RIS)
    assert len(recs) == 2
    r = recs[0]
    assert "working memory" in r.title and r.year == 2021
    assert r.authors == ["Rossi, Anna", "Bianchi, Luca"]
    assert r.doi == "10.1234/jcn.2021.0042"
    assert r.journal.startswith("Journal of Cognitive")
    assert r.volume == "33" and r.issue == "4" and r.pages == "511-525"
    assert r.source == "import:ris"
    assert recs[1].entry_type == "inproceedings"


def test_bibtex_parses_and_strips_braces():
    recs = importers.parse_bibtex(BIBTEX)
    assert len(recs) == 2
    r = recs[0]
    assert r.title == "Anodal tDCS over the DLPFC improves working memory"
    assert r.authors == ["Rossi, Anna", "Bianchi, Luca"]
    assert r.year == 2021 and r.pages == "511-525" and r.pmid == "34000000"
    assert r.doi == "10.1234/jcn.2021.0042"
    assert recs[1].entry_type == "inproceedings"
    assert recs[1].journal == "Proceedings of NeurIPS"


def test_medline_nbib_multiline_and_doi_in_aid():
    recs = importers.parse_medline(NBIB)
    assert len(recs) == 2
    r = recs[0]
    assert r.pmid == "34000000"
    assert "working memory in healthy adults" in r.title      # continuation joined
    assert "twenty participants" in r.abstract                # multiline abstract
    assert r.doi == "10.1234/jcn.2021.0042"                   # extracted from AID [doi]
    assert r.journal_abbrev == "J Cogn Neurosci" and r.year == 2021


def test_endnote_xml_parses():
    recs = importers.parse_endnote_xml(ENDNOTE_XML)
    assert len(recs) == 1
    r = recs[0]
    assert r.doi == "10.1234/jcn.2021.0042" and r.year == 2021
    assert r.authors == ["Rossi, Anna", "Bianchi, Luca"]
    assert r.pmid == "34000000"                               # PubMed remote db


def test_csv_scopus_column_mapping():
    recs = importers.parse_csv(CSV_SCOPUS)
    assert len(recs) == 1
    r = recs[0]
    assert r.title.startswith("Anodal tDCS")
    assert r.authors == ["Rossi A.", "Bianchi L."]
    assert r.doi == "10.1234/jcn.2021.0042" and r.pmid == "34000000"
    assert r.year == 2021 and r.journal.startswith("Journal of Cognitive")


def test_format_sniffing_and_dispatch():
    assert importers._sniff_format(RIS, "") == "ris"
    assert importers._sniff_format(BIBTEX, "") == "bib"
    assert importers._sniff_format(NBIB, "") == "nbib"
    assert importers._sniff_format(ENDNOTE_XML, "") == "xml"
    # Explicit format dispatch.
    assert len(importers.parse_text(RIS, "ris")) == 2


def test_import_file_and_paths(tmp_path):
    f1 = tmp_path / "scopus_export.ris"
    f1.write_text(RIS, encoding="utf-8")
    f2 = tmp_path / "wos_export.bib"
    f2.write_text(BIBTEX, encoding="utf-8")
    recs = importers.import_paths([f1, f2])
    assert len(recs) == 4
    # Provenance recorded for the audit/search log.
    assert all(r.raw.get("import_file") for r in recs)
    # A single bad/empty file does not abort the batch.
    bad = tmp_path / "empty.ris"
    bad.write_text("not a citation file", encoding="utf-8")
    assert len(importers.import_paths([f1, bad])) == 2


def test_doi_normalisation():
    assert importers._doi("https://doi.org/10.1/x") == "10.1/x"
    assert importers._doi("doi: 10.2/y") == "10.2/y"
    assert importers._doi("10.3/z") == "10.3/z"
