"""Rich tables + CSV export for stock screening results."""
from __future__ import annotations

import csv
import dataclasses
from pathlib import Path
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from screener.analysis.basic_screen import BasicScreenResult, FlagLevel, ScreenFlag
from screener.analysis.advanced_screen import AdvancedScreenResult
from screener.data.pdf_scanner import AuditScanResult

console = Console()

_SCORE_LABELS = {
    (80, 101): ("STRONG BUY", "bold green"),
    (60, 80): ("BUY", "green"),
    (40, 60): ("WATCH", "yellow"),
    (20, 40): ("AVOID", "red"),
    (0, 20): ("SELL", "bold red"),
}


def _score_label(score: int) -> tuple[str, str]:
    for (lo, hi), (label, style) in _SCORE_LABELS.items():
        if lo <= score < hi:
            return label, style
    return "N/A", "white"


_INR_CR = 1e7  # 1 Crore = 10 million


def _fmt(val: Optional[float], suffix: str = "", decimals: int = 2) -> str:
    if val is None:
        return "[dim]-[/dim]"
    return f"{val:.{decimals}f}{suffix}"


def _fmt_inr(val: Optional[float]) -> str:
    """Format a raw-INR total (from yfinance) as human-readable Crores."""
    if val is None:
        return "[dim]-[/dim]"
    cr = val / _INR_CR
    if abs(cr) >= 10_000:
        return f"₹{cr:,.0f} Cr"
    elif abs(cr) >= 100:
        return f"₹{cr:,.1f} Cr"
    else:
        return f"₹{cr:.2f} Cr"


def _flag_style(level: FlagLevel) -> str:
    return {"RED": "bold red", "YELLOW": "yellow", "GREEN": "green"}.get(level.value, "white")


def _combined_score(basic: BasicScreenResult, advanced: AdvancedScreenResult) -> int:
    """Blend basic (40%) + advanced (60%) scores."""
    return round(basic.score * 0.4 + advanced.score * 0.6)


def _trend_color(pct: Optional[float]) -> str:
    if pct is None:
        return "dim"
    return "green" if pct >= 0 else "red"


def _ma_signal(price: Optional[float], ma: Optional[float]) -> str:
    if price is None or ma is None:
        return "[dim]-[/dim]"
    if price > ma:
        return f"[green]₹{ma:,.1f} ↑[/green]"
    return f"[red]₹{ma:,.1f} ↓[/red]"


def print_stock_report(
    basic: BasicScreenResult,
    advanced: AdvancedScreenResult,
    price_info: Optional[dict] = None,
    price_trend: Optional[dict] = None,
) -> None:
    """Print full single-stock report with rich tables."""
    total_score = _combined_score(basic, advanced)
    label, label_style = _score_label(total_score)

    symbol = basic.symbol
    company_name = (price_info or {}).get("company_name", symbol)
    sector = (price_info or {}).get("sector", "")
    current_price = (price_info or {}).get("current_price")
    market_cap = (price_info or {}).get("market_cap")

    # ---- Header Panel ----
    header_lines = [
        f"[bold cyan]{company_name}[/bold cyan]  [dim]({symbol})[/dim]",
    ]
    if sector:
        header_lines.append(f"[dim]Sector: {sector}[/dim]")
    if current_price:
        header_lines.append(f"Price: [bold]₹{current_price:,.2f}[/bold]", )
    if market_cap:
        cap_cr = market_cap / 1e7  # Convert to crores
        header_lines.append(f"Market Cap: ₹{cap_cr:,.0f} Cr")

    header_lines.append(f"\nScore: [{label_style}]{total_score}/100 — {label}[/{label_style}]")
    console.print(Panel("\n".join(header_lines), title="[bold]Stock Analysis Report[/bold]", border_style="cyan"))

    # ---- Section 1: Growth Metrics ----
    growth_table = Table(title="Growth Metrics", box=box.SIMPLE_HEAVY, show_header=True)
    growth_table.add_column("Metric", style="dim")
    growth_table.add_column("Avg QoQ % (5Q)", justify="right")
    growth_table.add_column("Avg YoY % (5Y)", justify="right")
    growth_table.add_column("Latest Value", justify="right")

    def _growth_style(val: Optional[float], threshold: float = 0) -> str:
        if val is None:
            return "dim"
        return "green" if val >= threshold else "red"

    growth_table.add_row(
        "Revenue",
        Text(_fmt(basic.revenue_qoq_pct, "%"), style=_growth_style(basic.revenue_qoq_pct)),
        Text(_fmt(basic.revenue_yoy_pct, "%"), style=_growth_style(basic.revenue_yoy_pct, 10)),
        _fmt_inr(basic.revenue_latest),
    )
    growth_table.add_row(
        "PAT / Net Income",
        Text(_fmt(basic.pat_qoq_pct, "%"), style=_growth_style(basic.pat_qoq_pct)),
        Text(_fmt(basic.pat_yoy_pct, "%"), style=_growth_style(basic.pat_yoy_pct, 10)),
        _fmt_inr(basic.pat_latest),
    )
    growth_table.add_row(
        "EPS",
        Text(_fmt(basic.eps_qoq_pct, "%"), style=_growth_style(basic.eps_qoq_pct)),
        Text(_fmt(basic.eps_yoy_pct, "%"), style=_growth_style(basic.eps_yoy_pct, 10)),
        _fmt(basic.eps_latest, " ₹"),
    )
    console.print(growth_table)

    # ---- Section 2: Profitability ----
    prof_table = Table(title="Profitability & Cash Quality", box=box.SIMPLE_HEAVY)
    prof_table.add_column("Metric", style="dim")
    prof_table.add_column("Value", justify="right")
    prof_table.add_column("Signal", justify="center")

    def _signal(flag_val: bool) -> Text:
        return Text("✓", style="green") if flag_val else Text("✗", style="red")

    prof_table.add_row("EBITDA Margin", _fmt(basic.ebitda_margin_latest_pct, "%"), basic.ebitda_margin_trend or "-")
    if basic.ocf_pat_ratio is not None:
        prof_table.add_row("OCF/PAT Ratio", _fmt(basic.ocf_pat_ratio, "x"), "✓" if basic.ocf_pat_ratio >= 0.75 else "✗")
    if basic.ocf_trend:
        prof_table.add_row("OCF Trend", "-", basic.ocf_trend)
    prof_table.add_row("ROE", _fmt(advanced.roe_pct, "%"), "✓" if (advanced.roe_pct or 0) >= 15 else "✗")
    prof_table.add_row("ROCE", _fmt(advanced.roce_pct, "%"), "✓" if (advanced.roce_pct or 0) >= 12 else "✗")
    console.print(prof_table)

    # ---- Section 3: Debt Health ----
    debt_table = Table(title="Debt Health", box=box.SIMPLE_HEAVY)
    debt_table.add_column("Metric", style="dim")
    debt_table.add_column("Value", justify="right")
    debt_table.add_column("Threshold", justify="right", style="dim")

    debt_table.add_row("D/E Ratio", _fmt(advanced.de_ratio, "x"), "≤ 1.0")
    debt_table.add_row("Interest Coverage", _fmt(advanced.interest_coverage, "x"), "≥ 3.0")
    debt_table.add_row("Net Debt/EBITDA", _fmt(advanced.net_debt_to_ebitda, "x"), "≤ 3.0")
    debt_table.add_row("FCF (Latest Qtr)", _fmt_inr(advanced.fcf_latest), "Positive")
    console.print(debt_table)

    # ---- Section 4: Shareholding ----
    hold_table = Table(title="Shareholding Pattern", box=box.SIMPLE_HEAVY)
    hold_table.add_column("Holder", style="dim")
    hold_table.add_column("Current %", justify="right")
    hold_table.add_column("QoQ Change", justify="right")
    hold_table.add_column("6Q Change", justify="right")

    def _delta_text(delta: Optional[float]) -> Text:
        if delta is None:
            return Text("-", style="dim")
        if delta > 0:
            return Text(f"+{delta:.2f}%", style="green")
        elif delta < 0:
            return Text(f"{delta:.2f}%", style="red")
        return Text("0.00%", style="dim")

    hold_table.add_row("Promoters",       _fmt(advanced.promoter_holding_pct, "%"), _delta_text(advanced.promoter_holding_delta), _delta_text(advanced.promoter_holding_6q_delta))
    hold_table.add_row("Promoter Pledge", _fmt(advanced.promoter_pledge_pct, "%"),  _delta_text(advanced.pledge_delta),           _delta_text(advanced.pledge_6q_delta))
    hold_table.add_row("FII/FPI",         _fmt(advanced.fii_holding_pct, "%"),      _delta_text(advanced.fii_holding_delta),      _delta_text(advanced.fii_holding_6q_delta))
    hold_table.add_row("DII",             _fmt(advanced.dii_holding_pct, "%"),      _delta_text(advanced.dii_holding_delta),      _delta_text(advanced.dii_holding_6q_delta))
    hold_table.add_row("Public",          _fmt(advanced.public_holding_pct, "%"),   _delta_text(advanced.public_holding_delta),   _delta_text(advanced.public_holding_6q_delta))
    console.print(hold_table)

    # ---- Section 5: Valuation ----
    val_table = Table(title="Valuation Ratios", box=box.SIMPLE_HEAVY)
    val_table.add_column("Metric", style="dim")
    val_table.add_column("Value", justify="right")
    val_table.add_column("Note", justify="left", style="dim")

    current_pe = advanced.pe_ratio
    pe_note = ""
    if current_pe and current_pe > 0 and advanced.pe_mean_historical:
        pct = (current_pe - advanced.pe_mean_historical) / advanced.pe_mean_historical * 100
        if pct > 25:
            pe_note = Text(f"▲ {pct:.0f}% above 1yr mean — expensive", style="red")
        elif pct < -15:
            pe_note = Text(f"▼ {abs(pct):.0f}% below 1yr mean — cheap", style="green")
        else:
            pe_note = Text(f"≈ near 1yr mean ({pct:+.0f}%)", style="yellow")
    val_table.add_row("P/E Ratio", _fmt(current_pe, "x"), pe_note or "")
    val_table.add_row("P/B Ratio", _fmt(advanced.pb_ratio, "x"), "")
    val_table.add_row("EV/EBITDA", _fmt(advanced.ev_ebitda, "x"), "")
    console.print(val_table)

    # ---- Historical P/E Context table ----
    _pe_rows = [
        ("1 Year",  advanced.pe_mean_historical, advanced.pe_min_historical, advanced.pe_max_historical),
        ("5 Year",  advanced.pe_mean_5y,          advanced.pe_min_5y,         advanced.pe_max_5y),
        ("10 Year", advanced.pe_mean_10y,          advanced.pe_min_10y,        advanced.pe_max_10y),
    ]
    if any(mean is not None for _, mean, _, _ in _pe_rows):
        pe_table = Table(
            title=f"Historical P/E Context  [dim](current: {_fmt(current_pe, 'x')})[/dim]",
            box=box.SIMPLE_HEAVY,
        )
        pe_table.add_column("Period",   style="dim",  min_width=8)
        pe_table.add_column("Mean P/E", justify="right")
        pe_table.add_column("Low – High",  justify="center", style="dim")
        pe_table.add_column("vs Current",  justify="right")

        for period, mean, lo, hi in _pe_rows:
            if mean is None:
                continue
            range_str = f"{_fmt(lo, 'x')} – {_fmt(hi, 'x')}" if lo and hi else "-"
            if current_pe and current_pe > 0:
                pct = (current_pe - mean) / mean * 100
                if pct > 25:
                    vs = Text(f"▲ {pct:.0f}% above — expensive", style="red")
                elif pct < -15:
                    vs = Text(f"▼ {abs(pct):.0f}% below — cheap", style="green")
                else:
                    vs = Text(f"{pct:+.0f}% — near mean", style="yellow")
            else:
                vs = Text("-", style="dim")
            pe_table.add_row(period, _fmt(mean, "x"), range_str, vs)
        console.print(pe_table)

    # ---- Section 7: Working Capital ----
    wc_table = Table(title="Working Capital Efficiency", box=box.SIMPLE_HEAVY)
    wc_table.add_column("Metric", style="dim")
    wc_table.add_column("Days", justify="right")

    wc_table.add_row("Debtor Days", _fmt(advanced.debtor_days, " days", 0))
    wc_table.add_row("Inventory Days", _fmt(advanced.inventory_days, " days", 0))
    wc_table.add_row("Days Payable", _fmt(advanced.days_payable, " days", 0))
    wc_table.add_row("Cash Conversion Cycle", _fmt(advanced.cash_conversion_cycle, " days", 0))
    console.print(wc_table)

    # ---- Flags Panel ----
    all_flags = basic.flags + advanced.flags
    if all_flags:
        flags_text = []
        for flag in sorted(all_flags, key=lambda f: (f.level.value != "RED", f.level.value != "YELLOW")):
            style = _flag_style(flag.level)
            flags_text.append(f"[{style}][{flag.level.value}][/{style}] [{style}]{flag.category}[/{style}]: {flag.message}")

        console.print(Panel(
            "\n".join(flags_text),
            title="[bold]Screening Flags[/bold]",
            border_style="yellow",
        ))

    # ---- Final Score ----
    red_count = advanced.red_flag_count + sum(1 for f in basic.flags if f.level == FlagLevel.RED)
    console.print(Panel(
        f"[bold]Total Score: [{label_style}]{total_score}/100[/{label_style}][/bold]  "
        f"Rating: [{label_style}]{label}[/{label_style}]  "
        f"Red Flags: [red]{red_count}[/red]  "
        f"Basic: {basic.score}  Advanced: {advanced.score}",
        border_style=label_style.replace("bold ", ""),
    ))


def print_scan_summary(results: list[tuple[BasicScreenResult, AdvancedScreenResult, Optional[dict]]]) -> None:
    """Compact comparison table for batch scan."""
    table = Table(title="Scan Summary", box=box.DOUBLE_EDGE, show_header=True)
    table.add_column("Symbol", style="bold cyan", no_wrap=True)
    table.add_column("Company", max_width=20)
    table.add_column("Score", justify="center")
    table.add_column("Rating", justify="center")
    table.add_column("Rev YoY%", justify="right")
    table.add_column("PAT YoY%", justify="right")
    table.add_column("ROE%", justify="right")
    table.add_column("D/E", justify="right")
    table.add_column("P/E", justify="right")
    table.add_column("Pledge%", justify="right")
    table.add_column("Red Flags", justify="center")

    for basic, advanced, price_info in results:
        score = _combined_score(basic, advanced)
        label, style = _score_label(score)
        company = (price_info or {}).get("company_name", basic.symbol)[:20] if price_info else basic.symbol[:20]
        red_flags = advanced.red_flag_count + sum(1 for f in basic.flags if f.level == FlagLevel.RED)

        table.add_row(
            basic.symbol,
            company,
            Text(str(score), style=style),
            Text(label, style=style),
            _fmt(basic.revenue_yoy_pct, "%"),
            _fmt(basic.pat_yoy_pct, "%"),
            _fmt(advanced.roe_pct, "%"),
            _fmt(advanced.de_ratio, "x"),
            _fmt(advanced.pe_ratio, "x"),
            _fmt(advanced.promoter_pledge_pct, "%"),
            Text(str(red_flags), style="red" if red_flags > 2 else "yellow" if red_flags > 0 else "green"),
        )

    console.print(table)


def export_to_csv(
    results: list[tuple[BasicScreenResult, AdvancedScreenResult, Optional[dict]]],
    output_path: str,
) -> None:
    """Export all results as flat CSV."""
    rows = []
    for basic, advanced, price_info in results:
        score = _combined_score(basic, advanced)
        label, _ = _score_label(score)
        row = {
            "symbol": basic.symbol,
            "company": (price_info or {}).get("company_name", ""),
            "sector": (price_info or {}).get("sector", ""),
            "price": (price_info or {}).get("current_price", ""),
            "market_cap": (price_info or {}).get("market_cap", ""),
            "total_score": score,
            "rating": label,
            "basic_score": basic.score,
            "advanced_score": advanced.score,
            # Growth
            "revenue_qoq_pct": basic.revenue_qoq_pct,
            "revenue_yoy_pct": basic.revenue_yoy_pct,
            "pat_qoq_pct": basic.pat_qoq_pct,
            "pat_yoy_pct": basic.pat_yoy_pct,
            "eps_yoy_pct": basic.eps_yoy_pct,
            # Profitability
            "ebitda_margin_pct": basic.ebitda_margin_latest_pct,
            "ebitda_margin_trend": basic.ebitda_margin_trend,
            "ocf_pat_ratio": basic.ocf_pat_ratio,
            "roe_pct": advanced.roe_pct,
            "roce_pct": advanced.roce_pct,
            # Debt
            "de_ratio": advanced.de_ratio,
            "interest_coverage": advanced.interest_coverage,
            "net_debt_ebitda": advanced.net_debt_to_ebitda,
            # Shareholding
            "promoter_pct": advanced.promoter_holding_pct,
            "promoter_delta": advanced.promoter_holding_delta,
            "pledge_pct": advanced.promoter_pledge_pct,
            "pledge_delta": advanced.pledge_delta,
            "fii_pct": advanced.fii_holding_pct,
            "fii_delta": advanced.fii_holding_delta,
            # Valuation
            "pe_ratio": advanced.pe_ratio,
            "pb_ratio": advanced.pb_ratio,
            "ev_ebitda": advanced.ev_ebitda,
            # Working capital
            "debtor_days": advanced.debtor_days,
            "inventory_days": advanced.inventory_days,
            "ccc": advanced.cash_conversion_cycle,
            # FCF
            "fcf_latest": advanced.fcf_latest,
            "fcf_trend": advanced.fcf_trend,
            # Flags
            "red_flag_count": advanced.red_flag_count + sum(1 for f in basic.flags if f.level == FlagLevel.RED),
            "yellow_flag_count": sum(1 for f in basic.flags + advanced.flags if f.level == FlagLevel.YELLOW),
        }
        rows.append(row)

    if not rows:
        return

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    console.print(f"[green]Exported {len(rows)} results → {output_path}[/green]")


_VERDICT_STYLE = {
    "Bullish": "bold green",
    "Cautiously Bullish": "green",
    "Neutral": "yellow",
    "Cautiously Bearish": "red",
    "Bearish": "bold red",
}




def print_narrative_report(narrative: dict, symbol: str, horizon: str = "1Y") -> None:
    """Print AI narrative: historical analysis (selected horizon) + 6M prediction."""
    if not narrative:
        console.print("[yellow]Could not generate narrative — set ANTHROPIC_API_KEY.[/yellow]")
        return
    if "_error" in narrative:
        console.print(f"[red]Narrative generation failed: {narrative['_error']}[/red]")
        return

    confidence = narrative.get("confidence", "Medium")
    conf_style = {"High": "green", "Medium": "yellow", "Low": "dim"}.get(confidence, "dim")

    hist = narrative.get("historical", {})
    pred = narrative.get("prediction", {})
    vh = hist.get("verdict", "Neutral")
    vp = pred.get("verdict", "Neutral")

    console.print(Panel(
        f"[bold cyan]{symbol}[/bold cyan]  [dim](history: {horizon}  →  prediction: next 6M)[/dim]\n"
        f"  {horizon} trend verdict    : [{_VERDICT_STYLE.get(vh, 'white')}]{vh}[/{_VERDICT_STYLE.get(vh, 'white')}]\n"
        f"  Next 6M verdict     : [{_VERDICT_STYLE.get(vp, 'white')}]{vp}[/{_VERDICT_STYLE.get(vp, 'white')}]\n"
        f"  Confidence          : [{conf_style}]{confidence}[/{conf_style}]",
        title="[bold]AI Narrative Analysis[/bold]",
        border_style="magenta",
    ))

    # ── Historical block ──
    console.rule(f"[bold magenta]What happened in the last {horizon}?[/bold magenta]")
    t_hist = Table(box=box.SIMPLE_HEAVY)
    t_hist.add_column("", style="dim", no_wrap=True, min_width=14)
    t_hist.add_column("", ratio=1)
    t_hist.add_row("Root Cause", hist.get("trend_cause", "-"))
    for i, f in enumerate(hist.get("supporting_factors", []), 1):
        t_hist.add_row(f"Factor {i}", f)
    console.print(t_hist)

    # ── 6M Prediction block ──
    vstyle = _VERDICT_STYLE.get(vp, "white")
    console.rule(f"[bold magenta]Next 6-Month Prediction  [{vstyle}]{vp}[/{vstyle}][/bold magenta]")
    t_pred = Table(box=box.SIMPLE_HEAVY)
    t_pred.add_column("", style="dim", no_wrap=True, min_width=14)
    t_pred.add_column("", ratio=1)
    t_pred.add_row("Outlook", pred.get("outlook", "-"))
    for i, b in enumerate(pred.get("outlook_basis", []), 1):
        t_pred.add_row(f"Basis {i}", b)
    console.print(t_pred)

    # ── Risks & Catalysts ──
    console.rule("[bold magenta]Key Risks vs Catalysts[/bold magenta]")
    risks = narrative.get("key_risks", [])
    catalysts = narrative.get("key_catalysts", [])
    rc = Table(box=box.SIMPLE_HEAVY)
    rc.add_column("Key Risks", style="red", ratio=1)
    rc.add_column("Key Catalysts", style="green", ratio=1)
    for i in range(max(len(risks), len(catalysts), 1)):
        rc.add_row(
            risks[i] if i < len(risks) else "",
            catalysts[i] if i < len(catalysts) else "",
        )
    console.print(rc)


def print_audit_report(audit: AuditScanResult) -> None:
    """Print a rich-formatted audit scan report."""

    # ---- Header ----
    quarters_str = ", ".join(audit.quarters_scanned) if audit.quarters_scanned else "none"
    if audit.is_clean and not audit.errors:
        verdict = "[bold green]CLEAN — no issues found[/bold green]"
    elif audit.red_count > 0:
        verdict = f"[bold red]{audit.red_count} RED FLAG(S) DETECTED[/bold red]"
    else:
        verdict = f"[yellow]{audit.yellow_count} caution item(s)[/yellow]"

    strategy_note = (
        "[green]Claude AI (semantic)[/green]"
        if audit.strategy_used == "llm"
        else "[dim]Structural section detection[/dim]"
    )

    console.print(Panel(
        f"Symbol: [bold cyan]{audit.symbol}[/bold cyan]\n"
        f"Quarters scanned: [dim]{quarters_str}[/dim]\n"
        f"Strategy: {strategy_note}\n"
        f"Result: {verdict}",
        title="[bold]Quarterly Audit PDF Scan[/bold]",
        border_style="cyan",
    ))

    # ---- Download errors ----
    if audit.errors:
        for err in audit.errors:
            console.print(f"  [yellow]⚠ {err}[/yellow]")

    if not audit.flags:
        if audit.quarters_scanned:
            console.print("[green]  ✓ All scanned quarters appear clean.[/green]")
        return

    # ---- Flags table ----
    table = Table(title="Audit Flags", box=box.SIMPLE_HEAVY, show_header=True)
    table.add_column("Level", justify="center", no_wrap=True, min_width=6)
    table.add_column("Quarter", justify="center", no_wrap=True)
    table.add_column("Category", no_wrap=True)
    table.add_column("Keyword Found", no_wrap=True, style="dim")
    table.add_column("Context", max_width=60)

    # Sort: RED first, then YELLOW; within level sort by quarter
    sorted_flags = sorted(audit.flags, key=lambda f: (0 if f.level == "RED" else 1, f.quarter))

    for flag in sorted_flags:
        level_text = (
            Text("RED", style="bold red")
            if flag.level == "RED"
            else Text("YELLOW", style="yellow")
        )
        table.add_row(
            level_text,
            flag.quarter,
            flag.category,
            flag.keyword,
            flag.context,
        )

    console.print(table)

    # ---- Summary ----
    console.print(
        f"  Total: [red]{audit.red_count} RED[/red]  "
        f"[yellow]{audit.yellow_count} YELLOW[/yellow]  "
        f"across {len(audit.quarters_scanned)} quarter(s)\n"
    )
