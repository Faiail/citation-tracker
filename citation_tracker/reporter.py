"""Reporting module generating CSV outputs and Rich terminal summaries."""

import csv
import logging
from pathlib import Path
from typing import List

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from citation_tracker.models import CitationRecord, DiscrepancyStatus

logger = logging.getLogger(__name__)
console = Console()

CSV_HEADERS = [
    "Status",
    "Cited_Paper_Title",
    "Cited_Paper_DOI",
    "Cited_Paper_Scopus_EID",
    "Cited_Paper_Year",
    "Cited_Paper_Scopus_URL",
    "Citing_Paper_Title_Scholar",
    "Citing_Paper_Authors",
    "Citing_Paper_Year",
    "Citing_Paper_Venue",
    "Citing_Paper_Scholar_URL",
    "Citing_Paper_Scopus_EID",
    "Citing_Paper_Scopus_DOI",
    "Citing_Paper_Scopus_Title",
    "Citing_Paper_Scopus_URL",
    "Scopus_Support_Request",
    "Notes",
]


def write_csv_report(
    records: List[CitationRecord],
    output_path: Path,
    only_missing: bool = False,
) -> int:
    """Write comparison records to a CSV file.
    
    Returns the count of records written.
    """
    filtered = [
        r for r in records
        if not only_missing or r.status == DiscrepancyStatus.MISSING_IN_SCOPUS
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)

        for r in filtered:
            citing_eid = r.citing_scopus_paper.eid if r.citing_scopus_paper else ""
            citing_doi = r.citing_scopus_paper.doi if r.citing_scopus_paper else ""
            citing_title = r.citing_scopus_paper.title if r.citing_scopus_paper else ""
            citing_url = r.citing_scopus_paper.scopus_url if r.citing_scopus_paper else ""

            row = [
                r.status.value,
                r.cited_paper.title,
                r.cited_paper.doi or "",
                r.cited_paper.eid,
                r.cited_paper.year or "",
                r.cited_paper.scopus_url,
                r.scholar_citation.title,
                r.scholar_citation.authors or "",
                r.scholar_citation.year or "",
                r.scholar_citation.venue or "",
                r.scholar_citation.url or "",
                citing_eid,
                citing_doi,
                citing_title,
                citing_url,
                r.support_request_summary(),
                r.notes or "",
            ]
            writer.writerow(row)

    logger.info(f"Wrote {len(filtered)} records to {output_path}")
    return len(filtered)


def generate_support_cover_letter(missing_records: List[CitationRecord], author_name: str = "") -> str:
    """Generate a polite, clear cover letter text for Elsevier / Scopus Customer Support."""
    return f"""Subject: Request for Correction of Missing Citation Links - Author: {author_name or 'Researcher'}

Dear Scopus Support Team,

I am writing to request a citation correction for my author profile in Scopus.

Upon cross-checking citations indexed on Google Scholar with the Scopus database, I identified {len(missing_records)} publication(s) that are indexed in Scopus and cite my work, but the reference links are currently not tracked in Scopus.

Both the cited publications and the citing publications are already indexed in Scopus with valid EIDs. 
Please find attached the CSV file containing the complete details (including Scopus EIDs, DOIs, and titles) for each missing citation link.

Could you please verify and update the reference links in Scopus accordingly so that the citations are properly attributed?

Thank you very much for your time and assistance.

Best regards,
{author_name or 'Researcher'}
"""


def print_rich_summary(records: List[CitationRecord], author_name: str = "") -> None:
    """Display a rich, colorful summary table of the cross-checking results."""
    total = len(records)
    missing = [r for r in records if r.status == DiscrepancyStatus.MISSING_IN_SCOPUS]
    tracked = [r for r in records if r.status == DiscrepancyStatus.TRACKED_IN_SCOPUS]
    not_in_scopus = [r for r in records if r.status == DiscrepancyStatus.CITING_NOT_IN_SCOPUS]

    summary_table = Table(title=f"Citation Cross-Check Summary {f'({author_name})' if author_name else ''}")
    summary_table.add_column("Category", style="cyan", no_wrap=True)
    summary_table.add_column("Count", justify="right", style="bold")
    summary_table.add_column("Description", style="dim")

    summary_table.add_row(
        "Total Scholar Citations Inspected",
        str(total),
        "Total citations examined from Google Scholar",
    )
    summary_table.add_row(
        "Tracked in Scopus",
        f"[green]{len(tracked)}[/green]",
        "Citations already correctly linked in Scopus",
    )
    summary_table.add_row(
        "Citing Paper Not in Scopus",
        f"[yellow]{len(not_in_scopus)}[/yellow]",
        "Preprints, theses, or non-Scopus-indexed venues",
    )
    summary_table.add_row(
        "LOST CITATIONS IN SCOPUS",
        f"[bold red]{len(missing)}[/bold red]",
        "Citing paper IS in Scopus, but citation link is MISSING!",
    )

    console.print()
    console.print(summary_table)

    if missing:
        console.print()
        missing_table = Table(title="[bold red]Missing Citations in Scopus (Actionable)[/bold red]")
        missing_table.add_column("Cited Scopus Paper (Your Paper)", style="cyan", max_width=35)
        missing_table.add_column("Citing Scopus Paper (Missing Reference)", style="magenta", max_width=35)
        missing_table.add_column("Citing EID", style="green", no_wrap=True)
        missing_table.add_column("Citing DOI", style="blue")

        for r in missing[:15]:  # show top 15 in console
            citing_eid = r.citing_scopus_paper.eid if r.citing_scopus_paper else "N/A"
            citing_doi = r.citing_scopus_paper.doi if r.citing_scopus_paper else "N/A"
            missing_table.add_row(
                r.cited_paper.title,
                r.scholar_citation.title,
                citing_eid,
                citing_doi,
            )

        console.print(missing_table)
        if len(missing) > 15:
            console.print(f"[dim]... and {len(missing) - 15} more missing citations in the output CSV files.[/dim]")
    else:
        console.print(
            Panel("[bold green]No missing citations detected! All Scopus-indexed citations are properly tracked.[/bold green]")
        )

