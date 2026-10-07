"""Cross-checking engine comparing Scholar citations against Scopus indexing."""

import logging
import re
from typing import Callable, List, Optional
from rapidfuzz import fuzz

from citation_tracker.models import (
    CitationRecord,
    DiscrepancyStatus,
    ScholarCitation,
    ScholarPaper,
    ScopusPaper,
)
from citation_tracker.scopus.client import ScopusClient
from citation_tracker.scholar.client import ScholarClient

logger = logging.getLogger(__name__)


def extract_doi_from_text_or_url(text: Optional[str]) -> Optional[str]:
    """Attempt to extract a DOI from a URL or text string."""
    if not text:
        return None
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", text)
    if match:
        clean = match.group(0).rstrip(".,;)>]")
        return clean
    return None


def match_scholar_paper(scopus_paper: ScopusPaper, scholar_papers: List[ScholarPaper]) -> Optional[ScholarPaper]:
    """Find the best matching Scholar paper for a Scopus paper using fuzzy title comparison."""
    best_match = None
    best_score = 0.0

    target_title = scopus_paper.title.lower().strip()

    for sp in scholar_papers:
        candidate_title = sp.title.lower().strip()
        score = fuzz.token_sort_ratio(target_title, candidate_title)
        if score > best_score:
            best_score = score
            best_match = sp

    # Require at least 80% similarity threshold
    if best_score >= 80 and best_match:
        return best_match
    return None


class CitationCrossChecker:
    """Engine to perform the cross-reference check between Scopus and Scholar."""

    def __init__(
        self,
        scopus_client: ScopusClient,
        scholar_client: ScholarClient,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ):
        self.scopus_client = scopus_client
        self.scholar_client = scholar_client
        self.progress_callback = progress_callback

    def check(
        self,
        scopus_papers: List[ScopusPaper],
        scholar_papers: List[ScholarPaper],
        max_papers: Optional[int] = None,
    ) -> List[CitationRecord]:
        """Perform cross-check across all publications.
        
        For each Scopus paper:
          1. Match with corresponding Google Scholar paper.
          2. Retrieve Google Scholar citing documents.
          3. Query Scopus for known citing documents (via refeid).
          4. For each Scholar citing document:
             - Check if indexed in Scopus (by DOI or Title).
             - If indexed, check if Scopus tracks the citation link.
             - Mark as MISSING_IN_SCOPUS if indexed in Scopus but citation not linked.
        """
        records: List[CitationRecord] = []
        papers_to_check = scopus_papers[:max_papers] if max_papers else scopus_papers
        total_papers = len(papers_to_check)

        for i, scopus_paper in enumerate(papers_to_check, start=1):
            if self.progress_callback:
                self.progress_callback(
                    f"Checking paper {i}/{total_papers}: '{scopus_paper.title[:50]}...'",
                    i,
                    total_papers,
                )

            # 1. Match Scopus paper with Scholar paper
            matched_scholar = match_scholar_paper(scopus_paper, scholar_papers)
            if not matched_scholar:
                logger.info(f"No Google Scholar match found for: '{scopus_paper.title}'")
                continue

            if not matched_scholar.cites_id or matched_scholar.cited_by_count == 0:
                logger.info(f"Paper '{scopus_paper.title}' has no citations on Google Scholar.")
                continue

            # 2. Get known Scopus citing documents for this paper
            try:
                scopus_citing_eids = self.scopus_client.get_citing_eids_for_paper(scopus_paper.eid)
                scopus_paper.scopus_citing_eids = scopus_citing_eids
            except Exception as e:
                logger.warning(f"Could not retrieve Scopus citing EIDs for {scopus_paper.eid}: {e}")
                scopus_citing_eids = set()

            # 3. Retrieve Google Scholar citing papers
            try:
                scholar_citations = self.scholar_client.get_citing_papers(
                    cites_id=matched_scholar.cites_id,
                    max_citations=150,
                )
            except Exception as e:
                logger.error(f"Failed to fetch Scholar citations for '{scopus_paper.title}': {e}")
                continue

            # 4. Compare each citing paper
            for citing in scholar_citations:
                record = self._evaluate_citation(
                    cited_paper=scopus_paper,
                    citing=citing,
                    known_scopus_citing_eids=scopus_citing_eids,
                )
                records.append(record)

        return records

    def _evaluate_citation(
        self,
        cited_paper: ScopusPaper,
        citing: ScholarCitation,
        known_scopus_citing_eids: set,
    ) -> CitationRecord:
        # Check if citing paper has DOI
        doi = extract_doi_from_text_or_url(citing.url)

        # Search if citing paper is indexed in Scopus
        citing_scopus_paper: Optional[ScopusPaper] = None
        try:
            citing_scopus_paper = self.scopus_client.search_paper(doi=doi, title=citing.title)
        except Exception as e:
            logger.debug(f"Error checking Scopus index for '{citing.title}': {e}")

        if not citing_scopus_paper:
            # Citing document is not indexed in Scopus
            return CitationRecord(
                cited_paper=cited_paper,
                scholar_citation=citing,
                citing_scopus_paper=None,
                status=DiscrepancyStatus.CITING_NOT_IN_SCOPUS,
                notes="Citing paper not found in Scopus index (e.g. preprint, thesis, or non-indexed journal)",
            )

        # Citing paper IS indexed in Scopus!
        # Now check: does Scopus track this citation link?
        citing_eid = citing_scopus_paper.eid
        # Check against refeid set (handle potential '2-s2.0-' prefix difference)
        clean_citing_eid = citing_eid.replace("2-s2.0-", "")
        clean_known_eids = {e.replace("2-s2.0-", "") for e in known_scopus_citing_eids}

        is_tracked = clean_citing_eid in clean_known_eids

        if is_tracked:
            return CitationRecord(
                cited_paper=cited_paper,
                scholar_citation=citing,
                citing_scopus_paper=citing_scopus_paper,
                status=DiscrepancyStatus.TRACKED_IN_SCOPUS,
                notes="Citation is properly tracked in Scopus",
            )
        else:
            # DISCREPANCY DETECTED!
            return CitationRecord(
                cited_paper=cited_paper,
                scholar_citation=citing,
                citing_scopus_paper=citing_scopus_paper,
                status=DiscrepancyStatus.MISSING_IN_SCOPUS,
                notes="LOST CITATION: Citing paper is indexed in Scopus, but reference link is missing in Scopus database",
            )

