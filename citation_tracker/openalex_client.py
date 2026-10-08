"""OpenAlex client for open, reliable academic citation retrieval."""

import logging
from typing import List, Optional
import requests

from citation_tracker.cache import DiskCache
from citation_tracker.models import ScholarCitation

logger = logging.getLogger(__name__)


class OpenAlexClient:
    """Client for querying open citations from OpenAlex (no CAPTCHAs, open REST API)."""

    def __init__(self, cache: Optional[DiskCache] = None):
        self.cache = cache or DiskCache()

    def get_citing_papers_by_doi(self, doi: str) -> List[ScholarCitation]:
        """Fetch all citing papers for a given DOI from OpenAlex."""
        clean_doi = doi.strip().replace("https://doi.org/", "")
        cache_key = f"openalex_cites_{clean_doi.replace('/', '_')}"
        cached = self.cache.get("openalex_citations", cache_key)
        if cached is not None:
            return [ScholarCitation(**item) for item in cached]

        citations: List[ScholarCitation] = []
        try:
            work_url = f"https://api.openalex.org/works/https://doi.org/{clean_doi}"
            resp = requests.get(work_url, timeout=15)
            if resp.status_code != 200:
                return citations
            work_data = resp.json()
            work_id = work_data.get("id", "").split("/")[-1]
            if not work_id:
                return citations

            cites_url = f"https://api.openalex.org/works?filter=cites:{work_id}&per_page=100"
            cites_resp = requests.get(cites_url, timeout=20)
            if cites_resp.status_code == 200:
                results = cites_resp.json().get("results", [])
                for item in results:
                    title = item.get("title", "")
                    if not title:
                        continue
                    authors_list = [
                        a.get("author", {}).get("display_name", "")
                        for a in item.get("authorships", [])
                        if a.get("author", {}).get("display_name")
                    ]
                    authors_str = ", ".join(authors_list[:4])
                    doi_str = item.get("doi")
                    year_val = item.get("publication_year")
                    venue_val = item.get("primary_location", {}).get("source", {}).get("display_name")

                    citations.append(
                        ScholarCitation(
                            title=title,
                            authors=authors_str,
                            year=year_val,
                            venue=venue_val,
                            url=doi_str,
                        )
                    )
        except Exception as e:
            logger.debug(f"Error fetching OpenAlex citations for {clean_doi}: {e}")

        self.cache.set("openalex_citations", cache_key, [c.model_dump() for c in citations])
        return citations

