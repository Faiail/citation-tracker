"""Cross-checking engine comparing Scholar citations against Scopus indexing."""

import logging
import re
import unicodedata
from typing import Callable, List, Optional
from rapidfuzz import fuzz

from citation_tracker.models import (
    CitationRecord,
    DiscrepancyStatus,
    ScholarCitation,
    ScholarPaper,
    ScopusPaper,
)
from citation_tracker.openalex_client import OpenAlexClient
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


def normalize_title(title: str) -> str:
    """Normalize whitespace, unicode non-breaking spaces, and leading punctuation."""
    clean = unicodedata.normalize("NFKD", title).replace("\xa0", " ")
    clean = re.sub(r"\s+", " ", clean).strip().lower()
    return clean.lstrip(": -–—")


def match_scholar_paper(scopus_paper: ScopusPaper, scholar_papers: List[ScholarPaper]) -> Optional[ScholarPaper]:
    """Find the best matching Scholar paper for a Scopus paper using fuzzy title comparison."""
    best_match = None
    best_score = 0.0

    target_clean = normalize_title(scopus_paper.title)

    for sp in scholar_papers:
        candidate_clean = normalize_title(sp.title)
        score = fuzz.token_sort_ratio(target_clean, candidate_clean)
        if score > best_score:
            best_score = score
            best_match = sp

    # Require at least 75% similarity threshold
    if best_score >= 75 and best_match:
        return best_match
    return None


class CitationCrossChecker:
    """Engine to perform the cross-reference check between Scopus and Scholar/OpenAlex."""

    def __init__(
        self,
        scopus_client: ScopusClient,
        scholar_client: Optional[ScholarClient] = None,
        openalex_client: Optional[OpenAlexClient] = None,
        author_last_name: Optional[str] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ):
        self.scopus_client = scopus_client
        self.scholar_client = scholar_client
        self.openalex_client = openalex_client
        self.author_last_name = author_last_name
        self.progress_callback = progress_callback

    def check(
        self,
        scopus_papers: List[ScopusPaper],
        scholar_papers: List[ScholarPaper],
        max_papers: Optional[int] = None,
    ) -> List[CitationRecord]:
        """Perform cross-check across all publications."""
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
            matched_scholar = match_scholar_paper(scopus_paper, scholar_papers) if scholar_papers else None

            # 2. Get known Scopus citing documents for this paper (if refeid enabled)
            scopus_citing_eids = set()
            try:
                scopus_citing_eids = self.scopus_client.get_citing_eids_for_paper(scopus_paper.eid)
                scopus_paper.scopus_citing_eids = scopus_citing_eids
            except Exception as e:
                logger.debug(f"Could not retrieve Scopus citing EIDs for {scopus_paper.eid}: {e}")

            # 3. Retrieve citing papers from Scholar
            citing_candidates: List[ScholarCitation] = []
            seen_titles = set()

            if self.scholar_client and matched_scholar and matched_scholar.cites_id:
                try:
                    scholar_citings = self.scholar_client.get_citing_papers(
                        cites_id=matched_scholar.cites_id,
                        max_citations=150,
                    )
                    for c in scholar_citings:
                        norm = normalize_title(c.title)
                        if norm not in seen_titles:
                            seen_titles.add(norm)
                            citing_candidates.append(c)
                except Exception as e:
                    logger.debug(f"Scholar citing retrieval for '{scopus_paper.title}': {e}")

            # Also augment with OpenAlex if available
            if self.openalex_client and scopus_paper.doi:
                try:
                    openalex_citings = self.openalex_client.get_citing_papers_by_doi(scopus_paper.doi)
                    for c in openalex_citings:
                        norm = normalize_title(c.title)
                        if norm not in seen_titles:
                            seen_titles.add(norm)
                            citing_candidates.append(c)
                except Exception as e:
                    logger.debug(f"OpenAlex citing retrieval for '{scopus_paper.title}': {e}")

            if not citing_candidates:
                continue

            # 4. Compare each citing paper
            for citing in citing_candidates:
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
        citing_eid = citing_scopus_paper.eid
        clean_citing_eid = citing_eid.replace("2-s2.0-", "")
        clean_known_eids = {e.replace("2-s2.0-", "") for e in known_scopus_citing_eids}

        is_tracked = False
        if clean_known_eids:
            is_tracked = clean_citing_eid in clean_known_eids
        else:
            # Fallback to direct reference verification
            author_last = self.author_last_name
            if not author_last and cited_paper.authors:
                author_last = cited_paper.authors.split(",")[0].strip().split()[-1]
            if author_last:
                is_tracked = self.scopus_client.is_citation_tracked(citing_eid, author_last)

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
