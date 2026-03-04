"""Typer CLI for the Indian Stock Screener."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from screener import __version__

app = typer.Typer(
    name="screener",
    help="Indian Stock Screener — quarterly analysis CLI",
    add_completion=False,
)
console = Console()


def _screen_symbol(
    symbol: str,
    yf_fetcher,
    si_fetcher,
    basic_screener,
    advanced_screener,
) -> tuple:
    """Fetch + screen a single symbol. Returns (basic, advanced, price_info, price_trend)."""
    # Fetch yfinance data
    yf_data = yf_fetcher.fetch_all(symbol)
    price_info = yf_data.get("price_info")
    income_df = yf_data.get("quarterly_income")
    balance_df = yf_data.get("quarterly_balance")
    cashflow_df = yf_data.get("quarterly_cashflow")
    historical_pe = yf_data.get("historical_pe")
    price_trend = yf_data.get("price_trend")

    # Fetch screener.in data (graceful degradation on failure)
    si_data = si_fetcher.fetch_all(symbol)
    shareholding = si_data.get("shareholding")
    si_ratios = si_data.get("ratios")
    si_wc_ratios = si_data.get("wc_ratios")
    si_quarterly = si_data.get("quarterly_results")
    si_annual = si_data.get("annual_results")

    basic = basic_screener.screen(symbol, income_df, cashflow_df, si_quarterly_df=si_quarterly, si_annual_df=si_annual)
    advanced = advanced_screener.screen(
        symbol, price_info, balance_df, income_df, cashflow_df, shareholding, si_ratios,
        historical_pe=historical_pe, si_wc_ratios=si_wc_ratios,
    )
    return basic, advanced, price_info, price_trend


@app.command()
def screen(
    symbol: str = typer.Argument(..., help="Stock symbol e.g. RELIANCE.NS"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Export results to CSV file"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass cache and fetch fresh data"),
    ai: bool = typer.Option(False, "--ai", help="Enable AI: PDF audit scan + narrative (requires ANTHROPIC_API_KEY)"),
) -> None:
    """Screen a stock: fetch financials and display report. Add --ai for PDF audit + AI narrative."""
    import os
    from screener.data.yfinance_fetcher import YFinanceFetcher, CacheManager
    from screener.data.screener_in import ScreenerInFetcher
    from screener.analysis.basic_screen import BasicScreener
    from screener.analysis.advanced_screen import AdvancedScreener
    from screener.reports.formatter import print_stock_report, export_to_csv

    cache = CacheManager()
    if no_cache:
        cache.clear(symbol)

    yf_fetcher = YFinanceFetcher(cache)
    si_fetcher = ScreenerInFetcher(cache)
    basic_screener = BasicScreener()
    advanced_screener = AdvancedScreener()

    # ── Step 1: fetch & screen ──────────────────────────────────────────
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task(f"Fetching financials for {symbol}…", total=None)
        try:
            basic, advanced, price_info, price_trend = _screen_symbol(
                symbol, yf_fetcher, si_fetcher, basic_screener, advanced_screener
            )
        except Exception as e:
            console.print(f"[red]Error screening {symbol}: {e}[/red]")
            console.print_exception(show_locals=False)
            raise typer.Exit(1)

    print_stock_report(basic, advanced, price_info, price_trend)

    if output:
        export_to_csv([(basic, advanced, price_info)], output)

    if not ai:
        console.print("\n[dim]Tip: run with --ai to add PDF audit scan + AI narrative.[/dim]")
        return

    # ── Step 2: horizon selection ───────────────────────────────────────
    import questionary
    _HORIZON_MAP = {
        "6 months  — 2 quarters of audit data":   ("6M",  2,  "~6 months"),
        "1 year    — 4 quarters":                  ("1Y",  4,  "~1 year"),
        "2 years   — 8 quarters":                  ("2Y",  8,  "~2 years"),
        "3 years   — 13 quarters (max)":           ("3Y", 13,  "~3 years"),
    }
    selected = questionary.select(
        "Select analysis horizon:",
        choices=list(_HORIZON_MAP.keys()),
        default="1 year    — 4 quarters",
        style=questionary.Style([
            ("selected", "fg:cyan bold"),
            ("pointer",  "fg:cyan bold"),
            ("highlighted", "fg:cyan"),
            ("question", "bold"),
        ]),
    ).ask()
    if selected is None:  # user pressed Ctrl-C
        raise typer.Exit(0)
    horizon, max_quarters, horizon_desc = _HORIZON_MAP[selected]

    # ── Step 3: audit PDF scan ──────────────────────────────────────────
    audit_result = None
    pdf_links = si_fetcher.get_quarterly_pdf_links(symbol, max_quarters=max_quarters)
    if pdf_links:
        from screener.data.pdf_scanner import PDFAuditScanner
        console.print(
            f"\n[bold cyan]Scanning {len(pdf_links)} quarterly audit report(s) ({horizon_desc})…[/bold cyan]"
        )
        scanner = PDFAuditScanner()
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
            progress.add_task("Downloading & analysing PDFs…", total=None)
            audit_result = scanner.scan_symbol(symbol, pdf_links)
        if audit_result.errors:
            for err in audit_result.errors:
                console.print(f"  [dim yellow]⚠ {err}[/dim yellow]")
    else:
        console.print("[dim]No quarterly audit PDFs found on screener.in for this symbol.[/dim]")

    # ── Step 4: AI narrative (requires ANTHROPIC_API_KEY) ──────────────
    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]ANTHROPIC_API_KEY not set — skipping AI narrative.[/red]")
        return

    from screener.analysis.narrator import generate_narrative, answer_followup
    from screener.reports.formatter import print_narrative_report
    console.print(f"\n[bold magenta]Generating AI narrative ({horizon} horizon)…[/bold magenta]")
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task("Claude is analysing trend & predictions…", total=None)
        narrative, data_block = generate_narrative(
            symbol, price_info, price_trend, basic, advanced, audit_result,
            horizon=horizon,
        )
    print_narrative_report(narrative, symbol, horizon=horizon)

    # ── Step 5: counter-question loop ──────────────────────────────────
    if not narrative or "_error" in narrative:
        return

    from rich.panel import Panel
    _q_style = questionary.Style([
        ("question",    "bold magenta"),
        ("answer",      "fg:white"),
        ("instruction", "fg:gray italic"),
    ])
    console.print(
        "\n[dim]Follow-up Q&A — type your question and press Enter. "
        "Ctrl+C cancels current input. Empty line exits.[/dim]"
    )

    while True:
        try:
            question = questionary.text(
                "Ask Claude:",
                style=_q_style,
                instruction="(paste or type — Ctrl+C to cancel, Enter blank to exit)",
            ).ask()
        except KeyboardInterrupt:
            console.print("[dim]  Cancelled.[/dim]")
            continue   # re-prompt, don't exit

        if question is None or question.strip() == "":
            console.print("[dim]Exiting Q&A.[/dim]")
            break

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
            progress.add_task("Claude is thinking…", total=None)
            answer = answer_followup(question.strip(), data_block, narrative)

        console.print(Panel(answer, title="[bold magenta]AI Response[/bold magenta]", border_style="magenta"))


@app.command()
def scan(
    watchlist: Optional[str] = typer.Option(None, "--watchlist", "-w", help="Path to file with symbols (one per line)"),
    symbols: Optional[str] = typer.Option(None, "--symbols", "-s", help="Comma-separated symbols e.g. TCS.NS,INFY.NS"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Export results to CSV"),
    min_score: Optional[int] = typer.Option(None, "--min-score", help="Only show stocks with score >= N"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass cache"),
) -> None:
    """Screen multiple stocks and show comparison table."""
    from screener.data.yfinance_fetcher import YFinanceFetcher, CacheManager
    from screener.data.screener_in import ScreenerInFetcher
    from screener.analysis.basic_screen import BasicScreener
    from screener.analysis.advanced_screen import AdvancedScreener
    from screener.reports.formatter import print_scan_summary, export_to_csv, _combined_score

    # Build symbol list
    symbol_list: list[str] = []
    if watchlist:
        wl_path = Path(watchlist)
        if not wl_path.exists():
            console.print(f"[red]Watchlist file not found: {watchlist}[/red]")
            raise typer.Exit(1)
        symbol_list = [s.strip() for s in wl_path.read_text().splitlines() if s.strip() and not s.startswith("#")]
    elif symbols:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        console.print("[red]Provide --watchlist or --symbols[/red]")
        raise typer.Exit(1)

    if not symbol_list:
        console.print("[red]No symbols found.[/red]")
        raise typer.Exit(1)

    cache = CacheManager()
    yf_fetcher = YFinanceFetcher(cache)
    si_fetcher = ScreenerInFetcher(cache)
    basic_screener = BasicScreener()
    advanced_screener = AdvancedScreener()

    results = []
    for sym in symbol_list:
        if no_cache:
            cache.clear(sym)
        with Progress(SpinnerColumn(), TextColumn(f"[progress.description]Screening {sym}..."), transient=True) as progress:
            progress.add_task("", total=None)
            try:
                basic, advanced, price_info, _ = _screen_symbol(
                    sym, yf_fetcher, si_fetcher, basic_screener, advanced_screener
                )
                results.append((basic, advanced, price_info))
            except Exception as e:
                console.print(f"[yellow]Warning: Could not screen {sym}: {e}[/yellow]")

    if not results:
        console.print("[red]No results to display.[/red]")
        raise typer.Exit(1)

    # Filter by min score
    if min_score is not None:
        results = [(b, a, p) for b, a, p in results if _combined_score(b, a) >= min_score]
        if not results:
            console.print(f"[yellow]No stocks with score >= {min_score}[/yellow]")
            raise typer.Exit(0)

    print_scan_summary(results)

    if output:
        export_to_csv(results, output)


@app.command("clear-cache")
def clear_cache(
    symbol: Optional[str] = typer.Argument(None, help="Symbol to clear (omit to clear all)"),
) -> None:
    """Clear cached data files."""
    from screener.data.yfinance_fetcher import CacheManager

    cache = CacheManager()
    count = cache.clear(symbol)
    if symbol:
        console.print(f"[green]Cleared {count} cached file(s) for {symbol}[/green]")
    else:
        console.print(f"[green]Cleared {count} cached file(s)[/green]")


@app.command()
def version() -> None:
    """Show version."""
    console.print(f"Indian Stock Screener v{__version__}")


if __name__ == "__main__":
    app()
