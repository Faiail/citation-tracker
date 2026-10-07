"""Parser for CSV files exported directly from Scopus."""

import csv
import logging
from pathlib import Path
from typing import List, Optional
from citation_tracker.models import ScopusPaper

logger = logging.getLogger(__name__)


def parse_scopus_csv(file_path: Path) -> List[ScopusPaper]:
    """Parse author publications from a Scopus CSV export file.
    
    Tolerates column name variations and handles BOM encodings.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Scopus CSV file not found: {file_path}")

    papers: List[ScopusPaper] = []
    
    # Try reading with utf-8-sig (handles Excel UTF-8 BOM), fallback to latin-1
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
        raise ValueError(f"Could not decode {file_path} with supported encodings.")

    reader = csv.DictReader(content.splitlines())
    if not reader.fieldnames:
        return papers

    # Map lowercased headers
    header_map = {col.strip().lower(): col for col in reader.fieldnames}

    def get_val(row, *aliases) -> Optional[str]:
        for alias in aliases:
            orig_col = header_map.get(alias.lower())
            if orig_col and orig_col in row and row[orig_col].strip():
                return row[orig_col].strip()
        return None

    for row in reader:
        title = get_val(row, "Title", "Document Title", "Article Title")
        if not title:
            continue

        eid = get_val(row, "EID", "Scopus ID", "Identifier")
        if not eid:
            # Fallback identifier if EID not present
            doi_val = get_val(row, "DOI")
            eid = f"doi:{doi_val}" if doi_val else f"scopus_csv_{len(papers)}"

        doi = get_val(row, "DOI")
        venue = get_val(row, "Source title", "Source Title", "Publication Name", "Journal")
        authors = get_val(row, "Authors", "Author full names")
        url = get_val(row, "Link", "Scopus Link", "URL")
        
        year_str = get_val(row, "Year", "Publication Year")
        year = None
        if year_str and year_str.isdigit():
            year = int(year_str)

        cited_by_str = get_val(row, "Cited by", "Cited by count", "Citations")
        cited_by_count = 0
        if cited_by_str and cited_by_str.isdigit():
            cited_by_count = int(cited_by_str)

        papers.append(
            ScopusPaper(
                eid=eid,
                title=title,
                doi=doi,
                year=year,
                venue=venue,
                authors=authors,
                url=url,
                cited_by_count=cited_by_count,
            )
        )

    logger.info(f"Parsed {len(papers)} papers from Scopus CSV export {file_path.name}")
    return papers

