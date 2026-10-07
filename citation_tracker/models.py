"""Data models for citation-tracker."""

from enum import Enum
from typing import Optional, Set
from pydantic import BaseModel, Field


class DiscrepancyStatus(str, Enum):
    MISSING_IN_SCOPUS = "MISSING_IN_SCOPUS"
    TRACKED_IN_SCOPUS = "TRACKED_IN_SCOPUS"
    CITING_NOT_IN_SCOPUS = "CITING_NOT_IN_SCOPUS"
    AMBIGUOUS = "AMBIGUOUS"


class ScopusPaper(BaseModel):
    """Represents a publication indexed in Scopus."""
    eid: str
    title: str
    doi: Optional[str] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    authors: Optional[str] = None
    url: Optional[str] = None
    cited_by_count: int = 0
    scopus_citing_eids: Set[str] = Field(default_factory=set)

    @property
    def scopus_url(self) -> str:
        if self.url:
            return self.url
        clean_eid = self.eid
        if not clean_eid.startswith("2-s2.0-") and clean_eid.isdigit():
            clean_eid = f"2-s2.0-{clean_eid}"
        return f"https://www.scopus.com/record/display.uri?eid={clean_eid}&origin=resultslist"


class ScholarPaper(BaseModel):
    """Represents a publication from a researcher's Google Scholar profile."""
    title: str
    authors: Optional[str] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    cites_id: Optional[str] = None  # Google Scholar's internal citation cluster ID
    cited_by_count: int = 0
    url: Optional[str] = None


class ScholarCitation(BaseModel):
    """Represents a citing work retrieved from Google Scholar."""
    title: str
    authors: Optional[str] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    url: Optional[str] = None
    snippet: Optional[str] = None


class AuthorProfile(BaseModel):
    """Represents researcher profile metadata across systems."""
    name: Optional[str] = None
    scopus_id: Optional[str] = None
    scholar_id: Optional[str] = None
    orcid: Optional[str] = None
    affiliation: Optional[str] = None


class CitationRecord(BaseModel):
    """A cross-checked citation comparison result."""
    cited_paper: ScopusPaper
    scholar_citation: ScholarCitation
    citing_scopus_paper: Optional[ScopusPaper] = None
    status: DiscrepancyStatus
    notes: Optional[str] = None

    def support_request_summary(self) -> str:
        """Pre-formatted summary suitable for Elsevier / Scopus Support."""
        if self.status != DiscrepancyStatus.MISSING_IN_SCOPUS:
            return ""

        cited_doi = f" (DOI: {self.cited_paper.doi})" if self.cited_paper.doi else ""
        citing_doi = ""
        citing_eid = "Unknown"
        citing_title = self.scholar_citation.title

        if self.citing_scopus_paper:
            citing_eid = self.citing_scopus_paper.eid
            citing_title = self.citing_scopus_paper.title
            if self.citing_scopus_paper.doi:
                citing_doi = f" (DOI: {self.citing_scopus_paper.doi})"

        return (
            f"Please link missing citation from citing document EID: {citing_eid}{citing_doi} "
            f"to cited document EID: {self.cited_paper.eid}{cited_doi}. "
            f"Citing paper '{citing_title}' references '{self.cited_paper.title}', "
            f"verified on Google Scholar."
        )

