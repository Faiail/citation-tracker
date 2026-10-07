"""CLI interface for citation-tracker."""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from citation_tracker.cache import DiskCache
from citation_tracker.crosscheck import CitationCrossChecker
from citation_tracker.models import ScholarPaper, ScopusPaper
from citation_tracker.reporter import (
    generate_support_cover_letter,
    print_rich_summary,
    write_csv_report,
)
from citation_tracker.scopus.client import ScopusAPIError, ScopusClient
from citation_tracker.scopus.csv_parser import parse_scopus_csv
from citation_tracker.scholar.client import ScholarBlockedError, ScholarClient

# Load environment variables from .env
load_dotenv()

app = typer.Typer(
    help="Cross-check researcher citations between Google Scholar and Scopus to find missing Scopus citations."
)
console = Console()


@app.command()
def check(
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Author full name (e.g. 'Mario Rossi')"
    ),
    scopus_id: Optional[str] = typer.Option(
        None, "--scopus-id", help="Author Scopus ID (e.g. '57201234567')"
    ),
    scholar_id: Optional[str] = typer.Option(
        None, "--scholar-id", help="Author Google Scholar profile ID (from profile URL user=...)"
    ),
    orcid: Optional[str] = typer.Option(
        None, "--orcid", help="Author ORCID (e.g. '0000-0002-1825-0097')"
    ),
    scopus_csv: Optional[Path] = typer.Option(
        None, "--scopus-csv", help="Path to exported CSV file from Scopus containing your publications"
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", help="Elsevier API Key (defaults to ELSEVIER_API_KEY environment variable)"
    ),
    scholar_delay: float = typer.Option(
        2.5, "--scholar-delay", help="Polite delay between Google Scholar requests (in seconds)"
    ),
    scholar_cookie: Optional[str] = typer.Option(
        None, "--scholar-cookie", help="Browser Cookie header string for Google Scholar (bypasses CAPTCHA)"
    ),
    output: Path = typer.Option(
        Path("citations_report.csv"), "--output", "-o", help="Path for full citations CSV report"
    ),
    missing_output: Path = typer.Option(
        Path("missing_citations_for_scopus.csv"), "--missing-output", "-m", help="Path for missing citations only CSV"
    ),
    cover_letter: Path = typer.Option(
        Path("scopus_support_letter.txt"), "--cover-letter", help="Path for pre-drafted support letter"
    ),
    max_papers: Optional[int] = typer.Option(
        None, "--max-papers", help="Limit number of papers to check (useful for quick testing)"
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Disable query caching"
    ),
    clear_cache: bool = typer.Option(
        False, "--clear-cache", help="Clear disk cache before running"
    ),
):
    """Cross-check citations and export a CSV for Scopus Support."""
    console.print(
        Panel.fit(
            "[bold cyan]Scopus & Google Scholar Citation Tracker[/bold cyan]\n"
            "[dim]Cross-referencing citations to identify and recover untracked citations in Scopus[/dim]",
            border_style="cyan",
        )
    )

    cache = DiskCache(enabled=not no_cache)
    if clear_cache:
        cache.clear()
        console.print("[yellow]Disk cache cleared.[/yellow]")

    # Setup Scopus client
    scopus_client = ScopusClient(api_key=api_key, cache=cache)
    scholar_client = ScholarClient(delay=scholar_delay, cookie=scholar_cookie, cache=cache)

    # 1. Resolve Scopus Papers
    scopus_papers = []
    author_display_name = name or ""

    if scopus_csv:
        if not scopus_csv.exists():
            console.print(f"[bold red]Error:[/bold red] Scopus CSV file not found: {scopus_csv}")
            raise typer.Exit(code=1)
        console.print(f"[green]✓[/green] Loading Scopus publications from CSV: {scopus_csv}")
        scopus_papers = parse_scopus_csv(scopus_csv)
        if not scopus_papers:
            console.print("[bold red]Error:[/bold red] No valid papers found in the provided CSV.")
            raise typer.Exit(code=1)
    else:
        # Check Scopus credentials
        if not scopus_client.api_key:
            console.print(
                "[bold red]Error: Elsevier API Key not found.[/bold red]\n"
                "To search Scopus directly, provide an API key via:\n"
                "  1. [bold]--api-key YOUR_KEY[/bold]\n"
                "  2. In a [bold].env[/bold] file: [code]ELSEVIER_API_KEY=your_key[/code]\n"
                "  3. Or export your publications from scopus.com and pass [bold]--scopus-csv file.csv[/bold]\n\n"
                "You can get a free Elsevier API key in 1 minute at: [link=https://dev.elsevier.com/apikey/create]https://dev.elsevier.com/apikey/create[/link]"
            )
            raise typer.Exit(code=1)

        # Resolve Scopus Author ID
        if not scopus_id:
            if orcid:
                console.print(f"[cyan]Searching Scopus Author by ORCID: {orcid}...[/cyan]")
                try:
                    profile = scopus_client.search_author_by_orcid(orcid)
                    if profile and profile.scopus_id:
                        scopus_id = profile.scopus_id
                        author_display_name = profile.name or author_display_name
                        console.print(f"[green]✓[/green] Found Scopus Author: [bold]{profile.name}[/bold] (ID: {scopus_id})")
                    else:
                        console.print(f"[bold red]Error:[/bold red] No Scopus author found with ORCID {orcid}")
                        raise typer.Exit(code=1)
                except ScopusAPIError as e:
                    console.print(f"[bold red]Scopus API Error:[/bold red] {e}")
                    raise typer.Exit(code=1)
            elif name:
                console.print(f"[cyan]Searching Scopus Author by name: '{name}'...[/cyan]")
                try:
                    candidates = scopus_client.search_author_by_name(name)
                    if not candidates:
                        console.print(f"[bold red]Error:[/bold red] No Scopus author found matching '{name}'.")
                        raise typer.Exit(code=1)
                    if len(candidates) == 1:
                        scopus_id = candidates[0].scopus_id
                        author_display_name = candidates[0].name or author_display_name
                        console.print(f"[green]✓[/green] Matched Scopus Author: [bold]{candidates[0].name}[/bold] (ID: {scopus_id})")
                    else:
                        table = Table(title="Select Scopus Author")
                        table.add_column("#", justify="right")
                        table.add_column("Name")
                        table.add_column("Scopus ID")
                        table.add_column("Affiliation")
                        for idx, cand in enumerate(candidates, start=1):
                            table.add_row(str(idx), cand.name, cand.scopus_id, cand.affiliation or "N/A")
                        console.print(table)
                        choice = Prompt.ask("Enter number of your Scopus profile", default="1")
                        selected = candidates[int(choice) - 1]
                        scopus_id = selected.scopus_id
                        author_display_name = selected.name or author_display_name
                except ScopusAPIError as e:
                    console.print(f"[bold red]Scopus API Error:[/bold red] {e}")
                    raise typer.Exit(code=1)
            else:
                console.print(
                    "[bold red]Error:[/bold red] Please specify --scopus-id, --orcid, --name, or --scopus-csv."
                )
                raise typer.Exit(code=1)

        # Fetch author papers from Scopus API
        console.print(f"[cyan]Fetching publications for Scopus Author ID {scopus_id}...[/cyan]")
        try:
            scopus_papers = scopus_client.get_author_papers(scopus_id)
        except ScopusAPIError as e:
            console.print(f"[bold red]Scopus API Error:[/bold red] {e}")
            raise typer.Exit(code=1)

    console.print(f"[green]✓[/green] Found [bold]{len(scopus_papers)}[/bold] Scopus publications.")

    # 2. Resolve Google Scholar Profile
    scholar_papers = []
    if not scholar_id:
        if name:
            console.print(f"[cyan]Searching Google Scholar profiles for '{name}'...[/cyan]")
            candidates = scholar_client.search_author_by_name(name)
            if not candidates:
                console.print(
                    "[bold yellow]Warning:[/bold yellow] Could not auto-detect Google Scholar profile by name.\n"
                    "Please provide your Scholar profile ID directly using [bold]--scholar-id YOUR_ID[/bold]\n"
                    "(Found in your Google Scholar URL: scholar.google.com/citations?user=YOUR_ID)"
                )
                raise typer.Exit(code=1)
            if len(candidates) == 1:
                scholar_id = candidates[0].scholar_id
                console.print(f"[green]✓[/green] Matched Scholar Profile: [bold]{candidates[0].name}[/bold] (ID: {scholar_id})")
            else:
                table = Table(title="Select Google Scholar Profile")
                table.add_column("#", justify="right")
                table.add_column("Name")
                table.add_column("Scholar ID")
                table.add_column("Affiliation")
                for idx, cand in enumerate(candidates, start=1):
                    table.add_row(str(idx), cand.name, cand.scholar_id, cand.affiliation or "N/A")
                console.print(table)
                choice = Prompt.ask("Enter number of your Scholar profile", default="1")
                scholar_id = candidates[int(choice) - 1].scholar_id
        else:
            console.print(
                "[bold red]Error:[/bold red] Please provide --scholar-id (e.g. from your profile URL ?user=...)"
            )
            raise typer.Exit(code=1)

    console.print(f"[cyan]Fetching publications from Google Scholar profile ({scholar_id})...[/cyan]")
    try:
        scholar_papers = scholar_client.get_author_papers(scholar_id)
    except ScholarBlockedError as e:
        console.print(f"[bold red]Google Scholar Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    console.print(f"[green]✓[/green] Found [bold]{len(scholar_papers)}[/bold] publications on Google Scholar.")

    # 3. Cross-Check Citations
    console.print(
        Panel("[bold]Starting Cross-Check between Google Scholar citations and Scopus...[/bold]\n"
              f"Delay between Scholar calls: {scholar_delay}s\n"
              "Checking citing papers against Scopus index...",
              border_style="blue")
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Cross-checking citations...", total=len(scopus_papers))

        def update_progress(desc: str, current: int, total: int):
            progress.update(task, description=f"[cyan]{desc}", completed=current, total=total)

        checker = CitationCrossChecker(
            scopus_client=scopus_client,
            scholar_client=scholar_client,
            progress_callback=update_progress,
        )

        records = checker.check(
            scopus_papers=scopus_papers,
            scholar_papers=scholar_papers,
            max_papers=max_papers,
        )

    # 4. Generate Reports
    write_csv_report(records, output, only_missing=False)
    missing_count = write_csv_report(records, missing_output, only_missing=True)

    # Cover letter
    missing_records = [r for r in records if r.status.value == "MISSING_IN_SCOPUS"]
    letter_text = generate_support_cover_letter(missing_records, author_name=author_display_name)
    with open(cover_letter, "w", encoding="utf-8") as f:
        f.write(letter_text)

    # Display Rich summary
    print_rich_summary(records, author_name=author_display_name)

    console.print(
        Panel(
            f"[bold green]Analysis Complete![/bold green]\n\n"
            f"• Full report saved to: [bold]{output.resolve()}[/bold]\n"
            f"• Actionable Missing Citations CSV: [bold]{missing_output.resolve()}[/bold] ({missing_count} lost citations)\n"
            f"• Scopus Support Cover Letter: [bold]{cover_letter.resolve()}[/bold]\n\n"
            f"[bold cyan]How to submit to Scopus Support:[/bold cyan]\n"
            f"1. Open Elsevier Scopus Support / Missing Citation webform:\n"
            f"   [link=https://service.elsevier.com/app/answers/detail/a_id/28221/supporthub/scopus/]https://service.elsevier.com/app/answers/detail/a_id/28221/supporthub/scopus/[/link]\n"
            f"2. Attach the generated [bold]{missing_output.name}[/bold] file.\n"
            f"3. Copy the pre-drafted text from [bold]{cover_letter.name}[/bold] into your request.",
            border_style="green",
        )
    )


@app.command()
def search_author(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Author name to search"),
    orcid: Optional[str] = typer.Option(None, "--orcid", help="Author ORCID to search"),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="Elsevier API Key"),
):
    """Search for researcher profiles on Scopus and Google Scholar to find IDs."""
    if not name and not orcid:
        console.print("[bold red]Please specify either --name or --orcid.[/bold red]")
        raise typer.Exit(code=1)

    scopus_client = ScopusClient(api_key=api_key)
    scholar_client = ScholarClient()

    console.print(Panel(f"[bold cyan]Searching researcher profiles for:[/bold cyan] {name or orcid}"))

    # Scopus search
    if scopus_client.api_key:
        console.print("[bold]Scopus Author Search Results:[/bold]")
        try:
            if orcid:
                prof = scopus_client.search_author_by_orcid(orcid)
                scopus_results = [prof] if prof else []
            else:
                scopus_results = scopus_client.search_author_by_name(name)

            if scopus_results:
                t = Table()
                t.add_column("Name", style="bold")
                t.add_column("Scopus Author ID", style="cyan")
                t.add_column("Affiliation", style="dim")
                t.add_column("ORCID", style="green")
                for p in scopus_results:
                    t.add_row(p.name, p.scopus_id, p.affiliation or "N/A", p.orcid or "N/A")
                console.print(t)
            else:
                console.print("[yellow]No Scopus authors found.[/yellow]")
        except Exception as e:
            console.print(f"[red]Error searching Scopus:[/red] {e}")
    else:
        console.print("[dim]Skipping Scopus search (ELSEVIER_API_KEY not configured).[/dim]")

    # Scholar search
    if name:
        console.print("\n[bold]Google Scholar Profile Search Results:[/bold]")
        try:
            scholar_results = scholar_client.search_author_by_name(name)
            if scholar_results:
                t = Table()
                t.add_column("Name", style="bold")
                t.add_column("Scholar Profile ID", style="magenta")
                t.add_column("Affiliation", style="dim")
                for p in scholar_results:
                    t.add_row(p.name, p.scholar_id, p.affiliation or "N/A")
                console.print(t)
            else:
                console.print("[yellow]No Google Scholar profiles found.[/yellow]")
        except Exception as e:
            console.print(f"[red]Error searching Google Scholar:[/red] {e}")


@app.command()
def setup():
    """Interactive assistant to set up your Elsevier API key in a .env file."""
    console.print(
        Panel.fit(
            "[bold cyan]Elsevier API Key Configuration[/bold cyan]\n"
            "An Elsevier API key allows programmatic querying of Scopus documents and citations.\n\n"
            "1. Visit [link=https://dev.elsevier.com/apikey/create]https://dev.elsevier.com/apikey/create[/link]\n"
            "2. Log in with your Elsevier / university account (free).\n"
            "3. Enter a label (e.g. 'citation-tracker') and check the agreement.\n"
            "4. Copy your API Key.",
            border_style="cyan",
        )
    )

    env_path = Path(".env")
    current_key = os.getenv("ELSEVIER_API_KEY", "")

    new_key = Prompt.ask("Enter your Elsevier API Key", default=current_key)
    if new_key:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"ELSEVIER_API_KEY={new_key.strip()}\n")
        console.print(f"[bold green]✓ Saved API key to {env_path.resolve()}[/bold green]")
    else:
        console.print("[yellow]No key entered. Configuration unchanged.[/yellow]")


@app.command()
def test_api(
    api_key: Optional[str] = typer.Option(None, "--api-key", help="Elsevier API Key to test")
):
    """Test and validate connection to the Elsevier Scopus API."""
    client = ScopusClient(api_key=api_key)
    if not client.api_key:
        console.print("[bold red]No API key found. Run 'citation-tracker setup' or set ELSEVIER_API_KEY.[/bold red]")
        raise typer.Exit(code=1)

    console.print("[cyan]Testing Elsevier API credentials...[/cyan]")
    try:
        # Test author search
        results = client.search_author_by_name("Einstein")
        console.print(
            Panel(
                f"[bold green]✓ Elsevier API Key is VALID![/bold green]\n"
                f"Successfully queried Scopus author search (found {len(results)} sample entries).",
                border_style="green",
            )
        )
    except ScopusAPIError as e:
        console.print(f"[bold red]✗ Elsevier API Error:[/bold red] {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

