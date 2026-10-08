import glob
import logging
import os
import random
import re
import shutil
import sqlite3
import tempfile
import time
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from scholarly import scholarly

from citation_tracker.cache import DiskCache
from citation_tracker.models import AuthorProfile, ScholarCitation, ScholarPaper

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def auto_detect_scholar_cookies() -> Optional[str]:
    """Attempt to detect Google session cookies from local browser profiles (Firefox)."""
    patterns = [
        os.path.expanduser("~/.mozilla/firefox/*/cookies.sqlite"),
        os.path.expanduser("~/snap/firefox/common/.mozilla/firefox/*/cookies.sqlite"),
        os.path.expanduser("~/.var/app/org.mozilla.firefox/.mozilla/firefox/*/cookies.sqlite"),
    ]
    for pattern in patterns:
        for db_path in glob.glob(pattern):
            if not os.path.isfile(db_path):
                continue
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
                    tmp_path = tmp_file.name
                shutil.copy2(db_path, tmp_path)
                conn = sqlite3.connect(tmp_path)
                cur = conn.cursor()
                cur.execute("SELECT name, value FROM moz_cookies WHERE host LIKE '%google.com%'")
                rows = cur.fetchall()
                conn.close()
                if rows:
                    cookie_str = "; ".join(f"{k}={v}" for k, v in rows)
                    logger.info("Automatically detected Google session cookies from Firefox.")
                    return cookie_str
            except Exception as e:
                logger.debug(f"Could not read Firefox cookies from {db_path}: {e}")
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
    return None


class ScholarBlockedError(Exception):
    """Raised when Google Scholar returns a CAPTCHA or blocks requests."""
    pass


class ScholarClient:
    """Client for Google Scholar with polite rate limiting and disk caching."""

    def __init__(
        self,
        delay: float = 2.5,
        cookie: Optional[str] = None,
        cache: Optional[DiskCache] = None,
    ):
        self.delay = delay
        self.cookie = cookie or os.getenv("SCHOLAR_COOKIE") or auto_detect_scholar_cookies()
        self.cache = cache or DiskCache()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        if self.cookie:
            self.session.headers["Cookie"] = self.cookie

    def _polite_sleep(self) -> None:
        """Sleep with random jitter to avoid predictable bot patterns."""
        sleep_time = self.delay + random.uniform(0.5, 1.5)
        time.sleep(sleep_time)

    def search_author_by_name(self, name: str) -> List[AuthorProfile]:
        """Search Google Scholar for author profiles matching a name."""
        cache_key = f"scholar_search_{name.strip().lower()}"
        cached = self.cache.get("scholar_authors", cache_key)
        if cached is not None:
            return [AuthorProfile(**item) for item in cached]

        authors: List[AuthorProfile] = []
        try:
            search_query = scholarly.search_author(name)
            # Fetch up to 5 author suggestions
            for _ in range(5):
                author = next(search_query, None)
                if not author:
                    break
                scholar_id = author.get("scholar_id", "")
                authors.append(
                    AuthorProfile(
                        name=author.get("name"),
                        scholar_id=scholar_id,
                        affiliation=author.get("affiliation"),
                    )
                )
        except Exception as e:
            logger.warning(f"Error searching author on Google Scholar: {e}")

        self.cache.set("scholar_authors", cache_key, [a.model_dump() for a in authors])
        return authors

    def get_author_papers(self, scholar_id: str) -> List[ScholarPaper]:
        """Retrieve publications listed on a researcher's Google Scholar profile."""
        clean_id = scholar_id.strip()
        cache_key = f"profile_papers_{clean_id}"
        cached = self.cache.get("scholar_papers", cache_key)
        if cached is not None:
            return [ScholarPaper(**item) for item in cached]

        papers: List[ScholarPaper] = []
        cstart = 0
        pagesize = 100

        while True:
            url = f"https://scholar.google.com/citations?user={clean_id}&hl=en&cstart={cstart}&pagesize={pagesize}"
            resp = self._get_html(url)
            soup = BeautifulSoup(resp, "html.parser")

            rows = soup.select("#gsc_a_b .gsc_a_tr")
            if not rows:
                break

            for row in rows:
                title_elem = row.select_one(".gsc_a_at")
                if not title_elem:
                    continue
                title = title_elem.get_text(strip=True)
                url_path = title_elem.get("href")
                paper_url = f"https://scholar.google.com{url_path}" if url_path else None

                grays = row.select(".gs_gray")
                authors = grays[0].get_text(strip=True) if len(grays) > 0 else None
                venue = grays[1].get_text(strip=True) if len(grays) > 1 else None

                year_elem = row.select_one(".gsc_a_y .gsc_a_h")
                year_text = year_elem.get_text(strip=True) if year_elem else ""
                year = int(year_text) if year_text.isdigit() else None

                cite_elem = row.select_one(".gsc_a_c .gsc_a_ac")
                cites_id = None
                cited_by_count = 0
                if cite_elem:
                    cite_text = cite_elem.get_text(strip=True)
                    if cite_text.isdigit():
                        cited_by_count = int(cite_text)
                    cite_href = cite_elem.get("href", "")
                    if "cites=" in cite_href:
                        parsed = parse_qs(urlparse(cite_href).query)
                        cites_list = parsed.get("cites", [])
                        if cites_list:
                            cites_id = cites_list[0]

                papers.append(
                    ScholarPaper(
                        title=title,
                        authors=authors,
                        year=year,
                        venue=venue,
                        cites_id=cites_id,
                        cited_by_count=cited_by_count,
                        url=paper_url,
                    )
                )

            # Check if there is a 'show more' or next page
            if len(rows) < pagesize:
                break
            cstart += pagesize
            self._polite_sleep()

        self.cache.set("scholar_papers", cache_key, [p.model_dump() for p in papers])
        return papers

    def get_citing_papers(self, cites_id: str, max_citations: int = 100) -> List[ScholarCitation]:
        """Retrieve the papers citing a specific Google Scholar citation ID."""
        clean_cites_id = cites_id.strip()
        cache_key = f"cites_{clean_cites_id}"
        cached = self.cache.get("scholar_citations", cache_key)
        if cached is not None:
            return [ScholarCitation(**item) for item in cached]

        citations: List[ScholarCitation] = []
        start = 0

        while start < max_citations:
            url = f"https://scholar.google.com/scholar?cites={clean_cites_id}&hl=en&start={start}"
            try:
                time.sleep(5)
                resp = self._get_html(url)
            except ScholarBlockedError:
                # If blocked, log and return what we have so far
                logger.warning(f"Google Scholar rate-limited when fetching cites={clean_cites_id}")
                break
            soup = BeautifulSoup(resp, "html.parser")
            entries = soup.select(".gs_r.gs_or.gs_scl")
            if not entries:
                break

            for entry in entries:
                title_elem = entry.select_one(".gs_rt")
                if not title_elem:
                    continue
                # Remove [PDF], [HTML], [BOOK], etc. prefixes
                for badge in title_elem.select(".gs_ct1, .gs_ct2"):
                    badge.decompose()
                title = title_elem.get_text(separator=" ", strip=True)

                a_tag = title_elem.select_one("a")
                paper_url = a_tag.get("href") if a_tag else None

                # Extract authors, venue, year from .gs_a
                authors_str = None
                venue_str = None
                year_val = None
                gs_a = entry.select_one(".gs_a")
                if gs_a:
                    meta_text = gs_a.get_text(strip=True)
                    parts = meta_text.split(" - ")
                    if len(parts) >= 1:
                        authors_str = parts[0].strip()
                    if len(parts) >= 2:
                        venue_candidate = parts[1].strip()
                        # Extract 4-digit year if present
                        year_match = re.search(r"\b(19\d\d|20\d\d)\b", venue_candidate)
                        if year_match:
                            year_val = int(year_match.group(1))
                        venue_str = venue_candidate

                snippet_elem = entry.select_one(".gs_rs")
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else None

                citations.append(
                    ScholarCitation(
                        title=title,
                        authors=authors_str,
                        year=year_val,
                        venue=venue_str,
                        url=paper_url,
                        snippet=snippet,
                    )
                )

            start += 10
            self._polite_sleep()

        # Only cache if citations were retrieved
        if citations:
            self.cache.set("scholar_citations", cache_key, [c.model_dump() for c in citations])
        return citations

    def _get_html(self, url: str) -> str:
        """Fetch HTML content with error detection for Google CAPTCHA and soft-blocks."""
        try:
            resp = self.session.get(url, timeout=20)
        except requests.RequestException as e:
            raise ScholarBlockedError(f"Network error connecting to Google Scholar: {e}")

        lower_body = resp.text.lower()
        if (
            resp.status_code in (403, 429)
            or "recaptcha" in lower_body
            or "unusual traffic" in lower_body
            or "can't perform the operation" in lower_body
            or "system can't perform" in lower_body
        ):
            raise ScholarBlockedError(
                "Google Scholar has temporarily rate-limited citing requests from this IP address "
                "('The system can't perform the operation now').\n"
                "To resolve this, you can:\n"
                "  1. Pass your browser's Google Scholar cookie with --scholar-cookie 'YOUR_COOKIE'\n"
                "  2. Increase the delay with --scholar-delay 5.0\n"
                "  3. Or use --source all to automatically augment with OpenAlex academic citations."
            )

        resp.raise_for_status()
        return resp.text

