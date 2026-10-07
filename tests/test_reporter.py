"""Tests for CSV reporting and cover letter generation."""

import tempfile
from pathlib import Path
from citation_tracker.models import (
    CitationRecord,
    DiscrepancyStatus,
    ScholarCitation,
    ScopusPaper,
)
from citation_tracker.reporter import (
    generate_support_cover_letter,
    write_csv_report,
)


def test_write_csv_and_cover_letter():
    cited = ScopusPaper(
        eid="2-s2.0-11111",
        title="Key Algorithm",
        doi="10.1016/j.alg.2021",
        year=2021,
    )
    citing_scholar = ScholarCitation(
        title="Application of Key Algorithm",
        authors="A. Author",
        year=2022,
        venue="Journal of Computing",
    )
    citing_scopus = ScopusPaper(
        eid="2-s2.0-22222",
        title="Application of Key Algorithm",
        doi="10.1016/j.comp.2022",
        year=2022,
    )

    record_missing = CitationRecord(
        cited_paper=cited,
        scholar_citation=citing_scholar,
        citing_scopus_paper=citing_scopus,
        status=DiscrepancyStatus.MISSING_IN_SCOPUS,
    )
    record_tracked = CitationRecord(
        cited_paper=cited,
        scholar_citation=citing_scholar,
        citing_scopus_paper=citing_scopus,
        status=DiscrepancyStatus.TRACKED_IN_SCOPUS,
    )

    records = [record_missing, record_tracked]

    with tempfile.TemporaryDirectory() as tmpdir:
        full_csv = Path(tmpdir) / "full.csv"
        missing_csv = Path(tmpdir) / "missing.csv"

        count_full = write_csv_report(records, full_csv, only_missing=False)
        count_missing = write_csv_report(records, missing_csv, only_missing=True)

        assert count_full == 2
        assert count_missing == 1

        with open(missing_csv, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()
            assert len(lines) == 2  # header + 1 missing record
            assert "MISSING_IN_SCOPUS" in lines[1]
            assert "2-s2.0-11111" in lines[1]
            assert "2-s2.0-22222" in lines[1]

        letter = generate_support_cover_letter([record_missing], author_name="Mario Rossi")
        assert "Mario Rossi" in letter
        assert "1 publication(s)" in letter

