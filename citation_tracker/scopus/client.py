"""Elsevier Scopus REST API client."""

import logging
import os
import re
import time
from typing import Dict, List, Optional, Set
from dotenv import load_dotenv
import requests
from rapidfuzz import fuzz

from citation_tracker.cache import DiskCache
from citation_tracker.models import AuthorProfile, ScopusPaper

load_dotenv()
logger = logging.getLogger(__name__)

SCOPUS_SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
AUTHOR_SEARCH_URL = "https://api.elsevier.com/content/search/author"


class ScopusAPIError(Exception):
    """Exception raised for Scopus API errors."""
    pass


class ScopusClient:
    """Client for interacting with Elsevier Scopus REST APIs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        inst_token: Optional[str] = None,
        cache: Optional[DiskCache] = None,
    ):
        self.api_key = api_key or os.getenv("ELSEVIER_API_KEY")
        self.inst_token = inst_token or os.getenv("ELSEVIER_INST_TOKEN")
        self.cache = cache or DiskCache()

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise ScopusAPIError(
                "Elsevier API Key is required. Set the ELSEVIER_API_KEY environment variable, "
                "add it to a .env file, or pass --api-key."
            )
        headers = {
            "X-ELS-APIKey": self.api_key,
            "Accept": "application/json",
        }
        if self.inst_token:
            headers["X-ELS-Insttoken"] = self.inst_token
        return headers

    def search_author_by_name(self, name: str) -> List[AuthorProfile]:
        """Search for authors by name (e.g. 'Mario Rossi' or 'Rossi, Mario')."""
        cache_key = f"author_name_{name.strip().lower()}"
        cached = self.cache.get("scopus_authors", cache_key)
        if cached is not None:
            return [AuthorProfile(**item) for item in cached]

        parts = name.strip().replace(",", " ").split()
        if len(parts) == 1:
            query = f"authlast({parts[0]})"
        else:
            first_name = parts[0]
            last_name = " ".join(parts[1:])
            query = f"authfirst({first_name}) and authlast({last_name})"

        params = {"query": query, "count": 10}
        headers = self._headers()
        try:
            resp = requests.get(AUTHOR_SEARCH_URL, headers=headers, params=params, timeout=20)
            if resp.status_code == 401:
                raise ScopusAPIError("Invalid Elsevier API Key or unauthorized access.")
            if resp.status_code == 429:
                raise ScopusAPIError("Elsevier API quota exceeded (Rate limit 429).")
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error(f"Error querying Scopus Author Search: {e}")
            raise ScopusAPIError(f"Network error querying Scopus: {e}")

        authors: List[AuthorProfile] = []
        entries = data.get("search-results", {}).get("entry", [])
        for entry in entries:
            auth_id_raw = entry.get("dc:identifier", "")
            auth_id = auth_id_raw.replace("AUTHOR_ID:", "") if "AUTHOR_ID:" in auth_id_raw else auth_id_raw
            pref = entry.get("preferred-name", {})
            surname = pref.get("surname", "")
            given = pref.get("given-name", "")
            full_name = f"{given} {surname}".strip() or entry.get("authname", "")
            affil = entry.get("affiliation-current", {}).get("affiliation-name", "")
            orcid = entry.get("orcid", None)

            authors.append(
                AuthorProfile(
                    name=full_name,
                    scopus_id=auth_id,
                    orcid=orcid,
                    affiliation=affil,
                )
            )

        self.cache.set("scopus_authors", cache_key, [a.model_dump() for a in authors])
        return authors

    def search_author_by_orcid(self, orcid: str) -> Optional[AuthorProfile]:
        """Search for an author using their ORCID (e.g. 0000-0002-1825-0097)."""
        clean_orcid = orcid.strip()
        cache_key = f"author_orcid_{clean_orcid}"
        cached = self.cache.get("scopus_authors", cache_key)
        if cached is not None:
            return AuthorProfile(**cached) if cached else None

        params = {"query": f"orcid({clean_orcid})", "count": 5}
        headers = self._headers()
        try:
            resp = requests.get(AUTHOR_SEARCH_URL, headers=headers, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise ScopusAPIError(f"Error querying Scopus by ORCID: {e}")

        entries = data.get("search-results", {}).get("entry", [])
        if not entries or "error" in entries[0]:
            self.cache.set("scopus_authors", cache_key, None)
            return None

        entry = entries[0]
        auth_id_raw = entry.get("dc:identifier", "")
        auth_id = auth_id_raw.replace("AUTHOR_ID:", "") if "AUTHOR_ID:" in auth_id_raw else auth_id_raw
        pref = entry.get("preferred-name", {})
        full_name = f"{pref.get('given-name', '')} {pref.get('surname', '')}".strip() or entry.get("authname", "")
        affil = entry.get("affiliation-current", {}).get("affiliation-name", "")

        profile = AuthorProfile(
            name=full_name,
            scopus_id=auth_id,
            orcid=clean_orcid,
            affiliation=affil,
        )
        self.cache.set("scopus_authors", cache_key, profile.model_dump())
        return profile

    def get_author_papers(self, scopus_author_id: str, max_results: int = 200) -> List[ScopusPaper]:
        """Fetch all documents in Scopus authored by this Scopus Author ID."""
        clean_id = scopus_author_id.strip()
        cache_key = f"papers_author_{clean_id}"
        cached = self.cache.get("scopus_papers", cache_key)
        if cached is not None:
            return [ScopusPaper(**item) for item in cached]

        papers: List[ScopusPaper] = []
        count = 25
        start = 0
        headers = self._headers()

        while True:
            params = {
                "query": f"AU-ID({clean_id})",
                "count": count,
                "start": start,
                "sort": "coverDate",
            }
            try:
                resp = requests.get(SCOPUS_SEARCH_URL, headers=headers, params=params, timeout=25)
                if resp.status_code == 429:
                    raise ScopusAPIError("Elsevier API quota exceeded (Rate limit 429).")
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                raise ScopusAPIError(f"Error fetching author papers: {e}")

            search_results = data.get("search-results", {})
            total_results = int(search_results.get("opensearch:totalResults", 0))
            entries = search_results.get("entry", [])

            if not entries or "error" in entries[0]:
                break

            for entry in entries:
                eid = entry.get("eid", "")
                if not eid:
                    continue
                title = entry.get("dc:title", "").strip()
                doi = entry.get("prism:doi")
                venue = entry.get("prism:publicationName")
                authors_str = entry.get("dc:creator")
                date_str = entry.get("prism:coverDate", "")
                year = int(date_str[:4]) if date_str and len(date_str) >= 4 and date_str[:4].isdigit() else None
                cited_by_count = int(entry.get("citedby-count", 0)) if entry.get("citedby-count") else 0
                url = None
                for link in entry.get("link", []):
                    if link.get("@ref") == "scopus":
                        url = link.get("@href")
                        break

                papers.append(
                    ScopusPaper(
                        eid=eid,
                        title=title,
                        doi=doi,
                        year=year,
                        venue=venue,
                        authors=authors_str,
                        url=url,
                        cited_by_count=cited_by_count,
                    )
                )

            start += count
            if start >= total_results or start >= max_results:
                break
            time.sleep(0.2)  # Polite pause between pages

        self.cache.set("scopus_papers", cache_key, [p.model_dump() for p in papers])
        return papers

    def get_citing_eids_for_paper(self, cited_eid: str) -> Set[str]:
        """Attempt to query Scopus for citing EIDs (via refeid query).
        
        Returns an empty set if the user's API key does not have entitlement for refeid.
        """
        clean_eid = cited_eid.strip()
        cache_key = f"citing_eids_{clean_eid}"
        cached = self.cache.get("scopus_citing_eids", cache_key)
        if cached is not None:
            return set(cached)

        citing_eids: Set[str] = set()
        count = 25
        start = 0
        headers = self._headers()
        query_val = clean_eid

        while True:
            params = {
                "query": f"refeid({query_val})",
                "count": count,
                "start": start,
            }
            try:
                resp = requests.get(SCOPUS_SEARCH_URL, headers=headers, params=params, timeout=25)
                if resp.status_code == 400:
                    # 'refeid' restriction not allowed for standard/personal keys
                    logger.debug("refeid query restricted for this API key. Falling back to reference checks.")
                    break
                if resp.status_code == 429:
                    raise ScopusAPIError("Elsevier API quota exceeded (Rate limit 429).")
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                logger.debug(f"refeid query unavailable: {e}")
                break

            search_results = data.get("search-results", {})
            total_results = int(search_results.get("opensearch:totalResults", 0))
            entries = search_results.get("entry", [])

            if not entries or "error" in entries[0]:
                break

            for entry in entries:
                eid = entry.get("eid")
                if eid:
                    citing_eids.add(eid)

            start += count
            if start >= total_results:
                break
            time.sleep(0.2)

        self.cache.set("scopus_citing_eids", cache_key, list(citing_eids))
        return citing_eids

    def is_citation_tracked(
        self,
        citing_eid: str,
        author_last_name: str,
    ) -> bool:
        """Check if a citing paper indexed in Scopus references the author's name.
        
        This works on standard/personal API keys without requiring refeid entitlements.
        """
        clean_eid = citing_eid.strip()
        clean_author = author_last_name.strip()
        cache_key = f"tracked_{clean_eid}_{clean_author.lower()}"
        cached = self.cache.get("scopus_citation_tracked", cache_key)
        if cached is not None:
            return bool(cached)

        headers = self._headers()
        query = f'EID({clean_eid}) and REF("{clean_author}")'
        params = {"query": query, "count": 1}
        try:
            resp = requests.get(SCOPUS_SEARCH_URL, headers=headers, params=params, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                total = int(data.get("search-results", {}).get("opensearch:totalResults", 0))
                is_tracked = total > 0
                self.cache.set("scopus_citation_tracked", cache_key, is_tracked)
                return is_tracked
        except Exception as e:
            logger.debug(f"Error checking citation reference in Scopus for {clean_eid}: {e}")

        return False

    def search_paper(self, doi: Optional[str] = None, title: Optional[str] = None) -> Optional[ScopusPaper]:
        """Search whether a document is indexed in Scopus by DOI or title."""
        if not doi and not title:
            return None

        cache_key = f"paper_{doi or ''}_{re.sub(r'[^a-zA-Z0-9]', '', (title or '').lower())[:60]}"
        cached = self.cache.get("scopus_search_paper", cache_key)
        if cached is not None:
            return ScopusPaper(**cached) if cached else None

        headers = self._headers()

        # 1. Search by DOI if available
        if doi:
            clean_doi = doi.strip()
            params = {"query": f'DOI("{clean_doi}")', "count": 1}
            try:
                resp = requests.get(SCOPUS_SEARCH_URL, headers=headers, params=params, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    entries = data.get("search-results", {}).get("entry", [])
                    if entries and "error" not in entries[0]:
                        paper = self._entry_to_paper(entries[0])
                        self.cache.set("scopus_search_paper", cache_key, paper.model_dump())
                        return paper
            except Exception as e:
                logger.debug(f"DOI search failed for {clean_doi}: {e}")

        # 2. Search by Title
        if title:
            clean_title = self._clean_title_for_query(title)
            if len(clean_title) >= 10:
                params = {"query": f'TITLE("{clean_title}")', "count": 5}
                try:
                    resp = requests.get(SCOPUS_SEARCH_URL, headers=headers, params=params, timeout=20)
                    if resp.status_code == 200:
                        data = resp.json()
                        entries = data.get("search-results", {}).get("entry", [])
                        for entry in entries:
                            if "error" in entry:
                                continue
                            candidate_paper = self._entry_to_paper(entry)
                            ratio = fuzz.token_sort_ratio(title.lower(), candidate_paper.title.lower())
                            if ratio >= 80:
                                self.cache.set("scopus_search_paper", cache_key, candidate_paper.model_dump())
                                return candidate_paper
                except Exception as e:
                    logger.debug(f"Title search failed for {title}: {e}")

        # Not found in Scopus
        self.cache.set("scopus_search_paper", cache_key, None)
        return None

    def _entry_to_paper(self, entry: Dict) -> ScopusPaper:
        eid = entry.get("eid", "")
        title = entry.get("dc:title", "").strip()
        doi = entry.get("prism:doi")
        venue = entry.get("prism:publicationName")
        authors_str = entry.get("dc:creator")
        date_str = entry.get("prism:coverDate", "")
        year = int(date_str[:4]) if date_str and len(date_str) >= 4 and date_str[:4].isdigit() else None
        cited_by_count = int(entry.get("citedby-count", 0)) if entry.get("citedby-count") else 0
        url = None
        for link in entry.get("link", []):
            if link.get("@ref") == "scopus":
                url = link.get("@href")
                break
        return ScopusPaper(
            eid=eid,
            title=title,
            doi=doi,
            year=year,
            venue=venue,
            authors=authors_str,
            url=url,
            cited_by_count=cited_by_count,
        )

    def _clean_title_for_query(self, title: str) -> str:
        """Strip punctuation and brackets that break Scopus query parser."""
        t = re.sub(r'["{}\[\]\(\)]', ' ', title)
        t = re.sub(r'\s+', ' ', t).strip()
        return t
