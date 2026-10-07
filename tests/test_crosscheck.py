"""Tests for citation cross-check logic."""

from unittest.mock import MagicMock
from citation_tracker.crosscheck import (
    CitationCrossChecker,
    extract_doi_from_text_or_url,
    match_scholar_paper,
)
from citation_tracker.models import (
    DiscrepancyStatus,
    ScholarCitation,
    ScholarPaper,
    ScopusPaper,
)


def test_extract_doi():
    url1 = "https://doi.org/10.1016/j.neucom.2021.05.012"
    assert extract_doi_from_text_or_url(url1) == "10.1016/j.neucom.2021.05.012"

    url2 = "https://link.springer.com/article/10.1007/s10994-020-05891-3?other=1"
    assert extract_doi_from_text_or_url(url2) == "10.1007/s10994-020-05891-3"

    assert extract_doi_from_text_or_url("no doi here") is None


def test_match_scholar_paper():
    scopus_p = ScopusPaper(
        eid="2-s2.0-8501",
        title="Deep Residual Learning for Image Recognition",
    )
    scholar_list = [
        ScholarPaper(title="Attention is All You Need", cites_id="111", cited_by_count=50),
        ScholarPaper(title="Deep residual learning for image recognition.", cites_id="222", cited_by_count=100),
    ]

    matched = match_scholar_paper(scopus_p, scholar_list)
    assert matched is not None
    assert matched.cites_id == "222"


def test_cross_check_detects_missing_citation():
    scopus_paper = ScopusPaper(
        eid="2-s2.0-cited100",
        title="Foundational AI Techniques",
        doi="10.1016/j.ai.2020",
        scopus_citing_eids={"2-s2.0-known200"},
    )
    scholar_paper = ScholarPaper(
        title="Foundational AI Techniques",
        cites_id="cluster_ai_100",
        cited_by_count=2,
    )

    citing_1 = ScholarCitation(
        title="Known Citing Paper in Scopus",
        url="https://doi.org/10.1016/j.known.2021",
    )
    citing_2 = ScholarCitation(
        title="Lost Citing Paper (Indexed in Scopus but link missing)",
        url="https://doi.org/10.1016/j.lost.2022",
    )
    citing_3 = ScholarCitation(
        title="Unindexed ArXiv Preprint",
        url="https://arxiv.org/abs/2201.00000",
    )

    # Mock clients
    mock_scopus = MagicMock()
    mock_scholar = MagicMock()

    # refeid returns known200
    mock_scopus.get_citing_eids_for_paper.return_value = {"2-s2.0-known200"}

    # Scholar returns citing 1, 2, 3
    mock_scholar.get_citing_papers.return_value = [citing_1, citing_2, citing_3]

    # Scopus search results for citing papers:
    def fake_search_paper(doi=None, title=None):
        if doi == "10.1016/j.known.2021" or "Known" in (title or ""):
            return ScopusPaper(eid="2-s2.0-known200", title="Known Citing Paper in Scopus", doi="10.1016/j.known.2021")
        if doi == "10.1016/j.lost.2022" or "Lost" in (title or ""):
            return ScopusPaper(eid="2-s2.0-lost300", title="Lost Citing Paper", doi="10.1016/j.lost.2022")
        return None

    mock_scopus.search_paper.side_effect = fake_search_paper

    checker = CitationCrossChecker(scopus_client=mock_scopus, scholar_client=mock_scholar)
    records = checker.check(scopus_papers=[scopus_paper], scholar_papers=[scholar_paper])

    assert len(records) == 3

    statuses = {r.scholar_citation.title: r.status for r in records}
    assert statuses["Known Citing Paper in Scopus"] == DiscrepancyStatus.TRACKED_IN_SCOPUS
    assert statuses["Lost Citing Paper (Indexed in Scopus but link missing)"] == DiscrepancyStatus.MISSING_IN_SCOPUS
    assert statuses["Unindexed ArXiv Preprint"] == DiscrepancyStatus.CITING_NOT_IN_SCOPUS

