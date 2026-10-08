"""Parser for CSV files exported from Harzing's Publish or Perish or Google Scholar."""

import csv
import logging
from pathlib import Path
from typing import List, Optional
from citation_tracker.models import ScholarCitation

logger = logging.getLogger(__name__)


def parse_scholar_citations_csv(file_path: Path) -> List[ScholarCitation]:
    """Parse citing publications from a CSV file (e.g. Publish or Perish export)."""
    if not file_path.exists():
        raise FileNotFoundError(f"Scholar CSV file not found: {file_path}")

    citations: List[ScholarCitation] = []
    
    encodings = ["utf-8-sig", "utf-8", "latin-1"]
    content = None
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue

    if content is None:
        raise ValueError(f"Could not read {file_path}")

    reader = csv.DictReader(content.splitlines())
    if not reader.fieldnames:
        return citations

    header_map = {col.strip().lower(): col for col in reader.fieldnames}

    def get_val(row, *aliases) -> Optional[str]:
        for alias in aliases:
            orig = header_map.get(alias.lower())
            if orig and orig in row and row[orig].strip():
                return row[orig].strip()
        return None

    for row in reader:
        title = get_val(row, "Title", "Article Title", "Paper Title")
        if not title:
            continue

        authors = get_val(row, "Authors", "Author")
        venue = get_val(row, "Source", "Publication", "Journal", "Publisher")
        url = get_val(row, "ArticleURL", "URL", "Link", "DOI")
        
        year_str = get_val(row, "Year", "PubYear")
        year = int(year_str) if year_str and year_str.isdigit() else None

        citations.append(
            ScholarCitation(
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                url=url,
            )
        )

    return citations

