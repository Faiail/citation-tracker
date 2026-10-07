"""Tests for data models."""

from citation_tracker.models import (
    CitationRecord,
    DiscrepancyStatus,
    ScholarCitation,
    ScholarPaper,
    ScopusPaper,
)


def test_scopus_paper_url():
    p = ScopusPaper(
        eid="2-s2.0-85012345678",
        title="Test Paper",
        year=2021,
    )
    assert p.scopus_url == "https://www.scopus.com/record/display.uri?eid=2-s2.0-85012345678&origin=resultslist"

    # Numeric EID auto-formatted
    p2 = ScopusPaper(
        eid="85012345678",
        title="Test Paper 2",
    )
    assert "2-s2.0-85012345678" in p2.scopus_url


def test_citation_record_support_summary():
    cited = ScopusPaper(
        eid="2-s2.0-85011111111",
        title="Foundations of AI",
        doi="10.1016/j.ai.2020.01",
        year=2020,
    )
    citing_scholar = ScholarCitation(
        title="Advances in Deep Learning",
        authors="J. Doe, A. Smith",
        year=2022,
    )
    citing_scopus = ScopusPaper(
        eid="2-s2.0-85022222222",
        title="Advances in Deep Learning",
        doi="10.1016/j.dl.2022.05",
        year=2022,
    )

    record = CitationRecord(
        cited_paper=cited,
        scholar_citation=citing_scholar,
        citing_scopus_paper=citing_scopus,
        status=DiscrepancyStatus.MISSING_IN_SCOPUS,
    )

    summary = record.support_request_summary()
    assert "2-s2.0-85022222222" in summary
    assert "2-s2.0-85011111111" in summary
    assert "10.1016/j.ai.2020.01" in summary
    assert "10.1016/j.dl.2022.05" in summary

