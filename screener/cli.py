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
    # yfinance: price data only
    yf_data = yf_fetcher.fetch_all(symbol)
    price_info = yf_data.get("price_info")
    historical_pe = yf_data.get("historical_pe")
    price_trend = yf_data.get("price_trend")

    # screener.in: all financial data
    si_data = si_fetcher.fetch_all(symbol)
    shareholding = si_data.get("shareholding")
    si_ratios = si_data.get("ratios")
    si_wc_ratios = si_data.get("wc_ratios")
    si_quarterly = si_data.get("quarterly_results")
    si_annual = si_data.get("annual_results")
    si_cashflow = si_data.get("cash_flow")
    si_balance = si_data.get("balance_sheet")

    # Patch stub annual year (e.g. 'Mar 2025 9m') → reconstructed full year
    # before both screeners receive the data so YoY comparisons are like-for-like.
    from screener.analysis.basic_screen import _patch_stub_annual
    if si_annual is not None:
        si_annual = _patch_stub_annual(si_annual, si_quarterly)

    sector = price_info.get("sector") if price_info else None
    industry = price_info.get("industry") if price_info else None
    basic = basic_screener.screen(
        symbol, si_quarterly_df=si_quarterly, si_annual_df=si_annual,
        si_cashflow_df=si_cashflow, sector=sector, industry=industry,
    )
    advanced = advanced_screener.screen(
        symbol, price_info, shareholding, si_ratios,
        historical_pe=historical_pe, si_wc_ratios=si_wc_ratios,
        si_balance_df=si_balance, si_annual_df=si_annual,
        sector=sector,
        eps_yoy_pct=basic.eps_yoy_pct, pat_yoy_pct=basic.pat_yoy_pct,
        eps_yoy_3y_pct=basic.eps_yoy_3y_pct, pat_yoy_3y_pct=basic.pat_yoy_3y_pct,
        pat_cagr_3y=basic.pat_cagr_3y,
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


@app.command("sync-sheet")
def sync_sheet(
    spreadsheet_id: str = typer.Argument(..., help="Google Sheets ID (from the URL)"),
    credentials: str = typer.Option(..., "--credentials", "-c", envvar="GOOGLE_SHEETS_CREDENTIALS", help="Path to service account JSON key file"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass cache and fetch fresh data"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print what would be written without updating the sheet"),
) -> None:
    """Scan stocks from a Google Sheet and write scores back to column C.

    Symbols are read from column B. Scores are written to column C in the
    format '42 - WATCH' (first run) or '42 (+7) - WATCH' (subsequent runs).

    Example:
        python -m screener sync-sheet 1BZ3aQjsJXp8cK50SW_Shrs9Lsnt2UcQlaR_HVlpPFLY --credentials service_account.json
    """
    from screener.data.yfinance_fetcher import YFinanceFetcher, CacheManager
    from screener.data.screener_in import ScreenerInFetcher
    from screener.analysis.basic_screen import BasicScreener
    from screener.analysis.advanced_screen import AdvancedScreener
    from screener.reports.formatter import _combined_score, _score_label
    from screener.integrations.google_sheets import SheetSyncer, make_comment

    # ── Connect to sheet ────────────────────────────────────────────────
    console.print(f"[bold]Connecting to Google Sheet…[/bold]")
    try:
        syncer = SheetSyncer(credentials, spreadsheet_id)
        rows = syncer.read_rows()
    except Exception as e:
        console.print(f"[red]Failed to connect to Google Sheet: {e}[/red]")
        raise typer.Exit(1)

    if not rows:
        console.print("[yellow]No symbols found in column B.[/yellow]")
        raise typer.Exit(0)

    console.print(f"[green]Found {len(rows)} symbol(s) to scan.[/green]\n")

    # ── Screen each symbol ──────────────────────────────────────────────
    cache = CacheManager()
    yf_fetcher = YFinanceFetcher(cache)
    si_fetcher = ScreenerInFetcher(cache)
    basic_screener = BasicScreener()
    advanced_screener = AdvancedScreener()

    updates: list[tuple[int, int, str]] = []

    for sheet_row in rows:
        sym = sheet_row.ns_symbol
        if no_cache:
            cache.clear(sym)
        with Progress(SpinnerColumn(), TextColumn(f"[progress.description]Screening {sym}…"), transient=True) as progress:
            progress.add_task("", total=None)
            try:
                basic, advanced, _, _ = _screen_symbol(
                    sym, yf_fetcher, si_fetcher, basic_screener, advanced_screener
                )
                # Treat zero score with no data as a fetch failure
                if basic.score == 0 and not any(f for f in basic.flags if f.category != "Data"):
                    raise ValueError("No financial data returned from screener.in")
                score = int(_combined_score(basic, advanced))
                label, _ = _score_label(score)
                comment = make_comment(score, label, sheet_row.prev_score)
                updates.append((sheet_row.row_num, score, comment))

                change_str = ""
                if sheet_row.prev_score is not None and sheet_row.prev_score != score:
                    delta = score - sheet_row.prev_score
                    sign = "+" if delta > 0 else ""
                    change_str = f" [dim](was {sheet_row.prev_score}, {sign}{delta})[/dim]"

                console.print(f"  [cyan]{sheet_row.symbol:<16}[/cyan] → [bold]{score}[/bold]  {comment}{change_str}")
            except Exception as e:
                console.print(f"\n[red]ERROR screening {sym}: {e}[/red]")
                console.print(f"[red]Aborting — no scores written to sheet.[/red]")
                raise typer.Exit(1)

    # ── Write back ──────────────────────────────────────────────────────
    if dry_run:
        console.print(f"\n[yellow]Dry run — {len(updates)} update(s) not written to sheet.[/yellow]")
    elif updates:
        console.print(f"\n[bold]Writing {len(updates)} score(s) to Google Sheet…[/bold]")
        try:
            syncer.write_scores(updates)
            console.print(f"[green]Done. {len(updates)} score(s) written.[/green]")
        except Exception as e:
            console.print(f"[red]Failed to write to sheet: {e}[/red]")
            raise typer.Exit(1)



@app.command()
def version() -> None:
    """Show version."""
    console.print(f"Indian Stock Screener v{__version__}")


if __name__ == "__main__":
    app()
