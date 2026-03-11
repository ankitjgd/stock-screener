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

from screener.analysis.basic_screen import BasicScreenResult, FlagLevel, ScreenFlag, _is_financial, _is_lease_heavy, _is_lease_heavy_by_data
from screener.analysis.advanced_screen import AdvancedScreenResult, _is_real_estate
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

    bbd = basic.score_breakdown
    abd = advanced.score_breakdown

    def _pts(val: int) -> str:
        """Format a score contribution as a coloured label for table titles."""
        if val > 0:
            return f"  [dim green](+{val} pts)[/dim green]"
        elif val < 0:
            return f"  [dim red]({val} pts)[/dim red]"
        return "  [dim](0 pts)[/dim]"

    def _subtitle(reasons: list) -> str:
        """Return a dimmed reason line for table titles, empty string if no reasons."""
        if not reasons:
            return ""
        return "\n  [dim]↳ " + "  ·  ".join(reasons) + "[/dim]"

    # ---- Score Breakdown Panel ----
    def _eff(raw: int, w: float) -> int:
        return round(raw * w)

    def _row_str(label: str, raw: int, weight: str, final: int) -> str:
        color = "green" if final > 0 else "red" if final < 0 else "dim"
        raw_str = f"{raw:+d} pts"
        final_str = f"{final:+d} pts"
        return f"  {label:<32} {raw_str:>8}   {weight:>5}   [{color}]{final_str:>8}[/{color}]"

    BW, AW = 0.4, 0.6
    base_final = round(50 * BW) + round(50 * AW)  # = 50
    def _penalty_flag_lines(flags: list, weight: float) -> list[str]:
        lines = []
        for msg in flags:
            short = msg[:60] + "…" if len(msg) > 60 else msg
            lines.append(f"    [dim red]↳ −5 pts × {weight}: {short}[/dim red]")
        return lines

    bd_rows = [
        f"  {'Component':<32} {'Raw':>7}        {'Wt':>5}   {'→ Score':>8}",
        "  " + "─" * 58,
        f"  {'Base (start of both screeners)':<32} {'50':>7}        {'  —':>5}   [dim]+{base_final:>4} pts[/dim]",
        "  " + "─" * 58,
        f"  [dim]Basic Screener  (×{BW})[/dim]",
        _row_str("  Growth", bbd.get("growth", 0), f"×{BW}", _eff(bbd.get("growth", 0), BW)),
        _row_str("  Profitability", bbd.get("profitability", 0), f"×{BW}", _eff(bbd.get("profitability", 0), BW)),
        *([_row_str("  Asset Quality", bbd.get("asset_quality", 0), f"×{BW}", _eff(bbd.get("asset_quality", 0), BW))] if bbd.get("asset_quality", 0) != 0 else []),
        _row_str("  Cash Quality", bbd.get("cash_quality", 0), f"×{BW}", _eff(bbd.get("cash_quality", 0), BW)),
        _row_str("  Penalties", bbd.get("penalties", 0), f"×{BW}", _eff(bbd.get("penalties", 0), BW)),
        *_penalty_flag_lines(bbd.get("penalty_flags", []), BW),
        "  " + "─" * 58,
        f"  [dim]Advanced Screener  (×{AW})[/dim]",
        _row_str("  Profitability", abd.get("profitability", 0), f"×{AW}", _eff(abd.get("profitability", 0), AW)),
        _row_str("  Debt Health", abd.get("debt", 0), f"×{AW}", _eff(abd.get("debt", 0), AW)),
        _row_str("  Shareholding", abd.get("shareholding", 0), f"×{AW}", _eff(abd.get("shareholding", 0), AW)),
        _row_str("  Valuation", abd.get("valuation", 0), f"×{AW}", _eff(abd.get("valuation", 0), AW)),
        *([_row_str("  Real Estate", abd.get("real_estate", 0), f"×{AW}", _eff(abd.get("real_estate", 0), AW))] if "real_estate" in abd else []),
        _row_str("  Penalties", abd.get("penalties", 0), f"×{AW}", _eff(abd.get("penalties", 0), AW)),
        *_penalty_flag_lines(abd.get("penalty_flags", []), AW),
        "  " + "═" * 58,
        f"  {'TOTAL':<32} {'':>7}        {'':>5}   [bold {label_style}]+{total_score:>4} pts[/bold {label_style}]",
    ]
    console.print(Panel("\n".join(bd_rows), title="[bold]Score Breakdown[/bold]", border_style="dim"))

    sector = price_info.get("sector") if price_info else None
    is_fin = _is_financial(sector)

    # ---- Section 1: Growth Metrics ----
    growth_pts = bbd.get("growth", 0)
    growth_table = Table(title=f"Growth Metrics{_pts(growth_pts)}{_subtitle(bbd.get('growth_reasons', []))}", box=box.SIMPLE_HEAVY, show_header=True)
    growth_table.add_column("Metric", style="dim")
    growth_table.add_column("Avg QoQ % (5Q)", justify="right")
    growth_table.add_column("Avg YoY % (3Y)", justify="right")
    growth_table.add_column("Avg YoY % (5Y)", justify="right")
    growth_table.add_column("TTM", justify="right")

    def _growth_style(val: Optional[float], threshold: float = 0) -> str:
        if val is None:
            return "dim"
        return "green" if val >= threshold else "red"

    def _fmt_yoy_fallback(val: Optional[float], periods: int, nominal: int) -> Text:
        """Format a YoY % value, appending (nY) when a fallback period was used."""
        style = _growth_style(val, 10)
        label = _fmt(val, "%")
        if val is not None and periods != nominal:
            label = f"{label} ({periods}Y)"
        return Text(label, style=style)

    growth_table.add_row(
        "Revenue",
        Text(_fmt(basic.revenue_qoq_pct, "%"), style=_growth_style(basic.revenue_qoq_pct)),
        _fmt_yoy_fallback(basic.revenue_yoy_3y_pct, basic.revenue_yoy_3y_periods, 3),
        _fmt_yoy_fallback(basic.revenue_yoy_pct, basic.revenue_yoy_periods, 5),
        _fmt_inr(basic.revenue_latest),
    )

    growth_table.add_row(
        "PAT (Net Income)",
        Text(_fmt(basic.pat_qoq_pct, "%"), style=_growth_style(basic.pat_qoq_pct)),
        _fmt_yoy_fallback(basic.pat_yoy_3y_pct, basic.pat_yoy_3y_periods, 3),
        _fmt_yoy_fallback(basic.pat_yoy_pct, basic.pat_yoy_periods, 5),
        _fmt_inr(basic.pat_latest),
    )
    growth_table.add_row(
        "EPS",
        Text(_fmt(basic.eps_qoq_pct, "%"), style=_growth_style(basic.eps_qoq_pct)),
        _fmt_yoy_fallback(basic.eps_yoy_3y_pct, basic.eps_yoy_3y_periods, 3),
        _fmt_yoy_fallback(basic.eps_yoy_pct, basic.eps_yoy_periods, 5),
        _fmt(basic.eps_latest, " ₹"),
    )
    if not is_fin and basic.ebitda_margin_latest_pct is not None:
        def _pp_style(val: Optional[float]) -> str:
            if val is None:
                return "dim"
            return "green" if val >= 0.3 else "red" if val < 0 else "dim"
        def _margin_fmt(val: Optional[float]) -> str:
            return _fmt(val, "%") if val is not None else "-"
        def _pp_fmt(val: Optional[float]) -> str:
            return f"{val:+.2f}pp" if val is not None else "-"
        growth_table.add_row(
            "EBITDA Margin",
            Text(_pp_fmt(basic.ebitda_margin_qoq_pp), style=_pp_style(basic.ebitda_margin_qoq_pp)),
            Text(_pp_fmt(basic.ebitda_margin_3y_pp), style=_pp_style(basic.ebitda_margin_3y_pp)),
            Text(_pp_fmt(basic.ebitda_margin_5y_pp), style=_pp_style(basic.ebitda_margin_5y_pp)),
            _fmt(basic.ebitda_margin_latest_pct, "%"),
        )
    console.print(growth_table)

    # ---- Section 2: Profitability ----
    prof_pts = bbd.get("profitability", 0) + bbd.get("cash_quality", 0) + abd.get("profitability", 0)
    _prof_reasons = bbd.get("profitability_reasons", []) + bbd.get("cash_quality_reasons", []) + abd.get("profitability_reasons", [])
    prof_table = Table(title=f"Profitability & Cash Quality{_pts(prof_pts)}{_subtitle(_prof_reasons)}", box=box.SIMPLE_HEAVY)
    prof_table.add_column("Metric", style="dim")
    prof_table.add_column("Value", justify="right")
    prof_table.add_column("Signal", justify="center")

    def _signal(flag_val: bool) -> Text:
        return Text("✓", style="green") if flag_val else Text("✗", style="red")

    industry = price_info.get("industry") if price_info else None
    is_lease = _is_lease_heavy(sector, industry) or _is_lease_heavy_by_data(
        basic.si_ocf_ebitda_ratio, basic.si_ocf_pat_ratio
    )

    _lumpy = sector and any(k in sector.lower() for k in ("real estate", "construction", "infrastructure", "capital goods", "engineering"))
    _opm_label = "EBITDA Margin  [dim](annual)[/dim]" if _lumpy else "EBITDA Margin"
    _opm_qoq = f"  [dim]QoQ {basic.ebitda_margin_qoq_pp:+.2f}pp[/dim]" if basic.ebitda_margin_qoq_pp is not None else ""
    prof_table.add_row(_opm_label, f"{_fmt(basic.ebitda_margin_latest_pct, '%')}{_opm_qoq}", basic.ebitda_margin_trend or "-")

    # OCF/EBITDA — shown for all non-financial companies (extra row for lease-heavy, primary for others)
    if basic.si_ocf_ebitda_ratio is not None and not is_fin:
        r = basic.si_ocf_ebitda_ratio
        ebitda_val = f"  [dim](OCF {basic.si_ocf_annual:+.0f} / EBITDA {basic.si_ebitda_annual:.0f} Cr)[/dim]" \
            if basic.si_ocf_annual is not None and basic.si_ebitda_annual is not None else ""
        if r >= 1.0:
            sig = Text("✓ excellent  (> 1.0x)", style="green")
        elif r >= 0.7:
            sig = Text("✓ good  (> 0.7x)", style="green")
        elif r >= 0:
            sig = Text("⚠ weak  (< 0.7x)", style="yellow")
        else:
            sig = Text("✗ negative", style="red")
        if is_lease:
            ocf_row_label = f"OCF/EBITDA  [dim](primary — Ind AS 116)[/dim]{ebitda_val}"
        else:
            ocf_row_label = f"OCF/EBITDA{ebitda_val}"
        prof_table.add_row(ocf_row_label, _fmt(r, "x"), sig)

    ocf_ratio = basic.si_ocf_pat_ratio or basic.ocf_pat_ratio
    # For lease-heavy sectors OCF/PAT is meaningless — hide it to avoid confusion
    if ocf_ratio is not None and not is_fin and not is_lease:
        src = "[dim](annual)[/dim]" if basic.si_ocf_pat_ratio is not None else "[dim](qtrly)[/dim]"
        ocf_trend = basic.si_ocf_trend or basic.ocf_trend
        _trend_arrow = {"improving": "↑", "deteriorating": "↓", "stable": "→"}.get(ocf_trend or "", "")
        _pass = ocf_ratio >= 0.75
        _negative = ocf_ratio < 0
        # Quality label
        if _pass:
            _quality = "positive OCF"
            _quality_style = "green"
        elif _negative:
            _quality = "negative OCF"
            _quality_style = "red"
        else:
            _quality = "low OCF"
            _quality_style = "yellow"
        # Trend label and style
        if ocf_trend:
            _trend_label = ocf_trend
            if _negative and ocf_trend == "stable":
                _trend_style = "red"       # chronic negative = bad
            elif ocf_trend == "improving":
                _trend_style = "green"
            elif ocf_trend == "deteriorating":
                _trend_style = "red"
            else:
                _trend_style = "yellow"
        else:
            _trend_label, _trend_style = "", "dim"
        ocf_signal = Text()
        ocf_signal.append("✓ " if _pass else "✗ ", style="green" if _pass else "red")
        ocf_signal.append(_quality, style=_quality_style)
        if _trend_label:
            ocf_signal.append("  (trend: ", style="dim")
            ocf_signal.append(f"{_trend_label} {_trend_arrow}", style=_trend_style)
            ocf_signal.append(")", style="dim")
        ratio_label = f"OCF/PAT Ratio  {src}"
        if basic.si_ocf_pat_ratio is not None and basic.si_ocf_annual is not None and basic.si_pat_annual is not None:
            ratio_label += f"  [dim](OCF {basic.si_ocf_annual:+.0f} / PAT {basic.si_pat_annual:.0f} Cr)[/dim]"
        prof_table.add_row(ratio_label, _fmt(ocf_ratio, "x"), ocf_signal)
    prof_table.add_row("ROE", _fmt(advanced.roe_pct, "%"), "✓" if (advanced.roe_pct or 0) >= 15 else "✗")
    prof_table.add_row("ROCE", _fmt(advanced.roce_pct, "%"), "✓" if (advanced.roce_pct or 0) >= 12 else "✗")
    console.print(prof_table)

    # ---- Section 2a: Asset Quality (financial sector only) ----
    if is_fin and (basic.gross_npa_pct is not None or basic.net_npa_pct is not None):
        npa_pts = basic.score_breakdown.get("asset_quality", 0)
        npa_table = Table(title=f"Asset Quality{_pts(npa_pts)}{_subtitle(bbd.get('asset_quality_reasons', []))}", box=box.SIMPLE_HEAVY)
        npa_table.add_column("Metric", style="dim", min_width=14)
        npa_table.add_column("Latest", justify="right")
        npa_table.add_column("1Y Change", justify="right")
        npa_table.add_column("2Y Change", justify="right")
        npa_table.add_column("3Y Change", justify="right")
        npa_table.add_column("Signal", justify="center")

        def _npa_chg_fmt(chg: Optional[float]) -> Text:
            if chg is None:
                return Text("-", style="dim")
            sign = "+" if chg > 0 else ""
            style = "red" if chg > 0 else "green" if chg < 0 else "dim"
            return Text(f"{sign}{chg:.2f}pp", style=style)

        def _npa_signal(val, green_thresh, red_thresh) -> Text:
            if val is None:
                return Text("-", style="dim")
            if val <= green_thresh:
                return Text("✓ healthy", style="green")
            elif val <= red_thresh:
                return Text("✗ elevated", style="yellow")
            return Text("✗ high", style="red")

        npa_table.add_row(
            "Gross NPA %",
            _fmt(basic.gross_npa_pct, "%"),
            _npa_chg_fmt(basic.gross_npa_1y_chg),
            _npa_chg_fmt(basic.gross_npa_2y_chg),
            _npa_chg_fmt(basic.gross_npa_3y_chg),
            _npa_signal(basic.gross_npa_pct, 3.0, 7.0),
        )
        npa_table.add_row(
            "Net NPA %",
            _fmt(basic.net_npa_pct, "%"),
            _npa_chg_fmt(basic.net_npa_1y_chg),
            _npa_chg_fmt(basic.net_npa_2y_chg),
            _npa_chg_fmt(basic.net_npa_3y_chg),
            _npa_signal(basic.net_npa_pct, 1.0, 3.0),
        )
        console.print(npa_table)

    # ---- Section 2b: Annual Cash Flow (screener.in) ----
    has_si_cf = any(v is not None for v in [
        basic.si_ocf_annual, basic.si_icf_annual, basic.si_fcf_annual, basic.si_net_cf_annual
    ])
    if has_si_cf:
        cf_table = Table(title="Cash Flow Analysis  [dim](Annual, ₹ Cr)[/dim]", box=box.SIMPLE_HEAVY)
        cf_table.add_column("Activity", style="dim", min_width=22)
        cf_table.add_column("Latest Year", justify="right")
        cf_table.add_column("5Y Trend", justify="center")
        cf_table.add_column("Signal", justify="center")

        def _cf_val(val: Optional[float]) -> Text:
            if val is None:
                return Text("-", style="dim")
            style = "green" if val >= 0 else "red"
            return Text(f"₹{val:,.0f} Cr", style=style)

        def _cf_signal(val: Optional[float], want_positive: bool = True) -> Text:
            if val is None:
                return Text("-", style="dim")
            ok = val >= 0 if want_positive else val <= 0
            return Text("✓", style="green") if ok else Text("✗", style="red")

        cf_table.add_row(
            "Operating (OCF)",
            _cf_val(basic.si_ocf_annual),
            basic.si_ocf_trend or "-",
            _cf_signal(basic.si_ocf_annual, want_positive=True),
        )
        cf_table.add_row(
            "Investing (ICF)",
            _cf_val(basic.si_icf_annual),
            "-",
            _cf_signal(basic.si_icf_annual, want_positive=False),  # negative = investing = good
        )
        if basic.si_fcf_annual is not None:
            cf_table.add_row(
                "Free CF  [dim](OCF+ICF)[/dim]",
                _cf_val(basic.si_fcf_annual),
                "-",
                _cf_signal(basic.si_fcf_annual, want_positive=True),
            )
        cf_table.add_row(
            "Financing (CFF)",
            _cf_val(basic.si_cff_annual),
            "-",
            "-",
        )
        cf_table.add_row(
            "Net Cash Flow",
            _cf_val(basic.si_net_cf_annual),
            "-",
            "-",
        )
        console.print(cf_table)

    # ---- Section 3: Debt Health ----
    debt_table = Table(title=f"Debt Health{_pts(abd.get('debt', 0))}{_subtitle(abd.get('debt_reasons', []))}", box=box.SIMPLE_HEAVY)
    debt_table.add_column("Metric", style="dim")
    debt_table.add_column("Value", justify="right")
    debt_table.add_column("Threshold", justify="right", style="dim")

    debt_table.add_row("D/E Ratio", _fmt(advanced.de_ratio, "x"), "≤ 1.0")
    debt_table.add_row("Interest Coverage", _fmt(advanced.interest_coverage, "x"), "≥ 3.0")
    # Net Debt/EBITDA is not meaningful for RE (revenue recognition lumpy → EBITDA misleading)
    if not advanced.is_real_estate:
        debt_table.add_row("Net Debt/EBITDA", _fmt(advanced.net_debt_to_ebitda, "x"), "≤ 3.0")
    debt_table.add_row("FCF (Latest Qtr)", _fmt_inr(advanced.fcf_latest), "Positive")
    console.print(debt_table)

    # helpers shared by next two tables
    def _chg(val: Optional[float], good_direction: str = "up") -> Text:
        if val is None:
            return Text("-", style="dim")
        up_good = good_direction == "up"
        style = "green" if ((val >= 0) == up_good) else "red"
        sign = "+" if val >= 0 else ""
        return Text(f"{sign}{val:.1f}%", style=style)

    def _cr(val: Optional[float]) -> str:
        if val is None:
            return "[dim]-[/dim]"
        if abs(val) >= 10_000:
            return f"₹{val:,.0f} Cr"
        elif abs(val) >= 100:
            return f"₹{val:,.1f} Cr"
        return f"₹{val:.2f} Cr"

    # ---- Section 3b: Net Cash Flow vs Cash Equivalents ----
    has_cf_vs_cash = any(v is not None for v in [advanced.si_cash_equivalents, basic.si_net_cf_annual])
    if has_cf_vs_cash:
        cf_cash_table = Table(
            title="Net Cash Flow vs Cash Equivalents  [dim](annual, ₹ Cr)[/dim]",
            box=box.SIMPLE_HEAVY,
        )
        cf_cash_table.add_column("Metric", style="dim", min_width=22)
        cf_cash_table.add_column("Latest", justify="right")
        cf_cash_table.add_column("1Y Δ", justify="right")
        cf_cash_table.add_column("3Y Δ", justify="right")
        cf_cash_table.add_column("5Y Δ", justify="right")

        if advanced.si_cash_equivalents is not None:
            cash_cr = advanced.si_cash_equivalents  # already in Cr (from screener.in)
            cf_cash_table.add_row(
                "Cash Equivalents  [dim](in bank)[/dim]",
                Text(_cr(cash_cr), style="green" if cash_cr > 0 else "red"),
                _chg(advanced.si_cash_eq_1y_pct, "up"),
                _chg(advanced.si_cash_eq_3y_pct, "up"),
                _chg(advanced.si_cash_eq_5y_pct, "up"),
            )

        if basic.si_net_cf_annual is not None:
            ncf = basic.si_net_cf_annual
            ncf_style = "green" if ncf >= 0 else "red"
            cf_cash_table.add_row(
                "Net Cash Flow  [dim](annual)[/dim]",
                Text(f"{_cr(ncf)}", style=ncf_style),
                _chg(basic.si_net_cf_1y_pct, "up"),
                _chg(basic.si_net_cf_3y_pct, "up"),
                _chg(basic.si_net_cf_5y_pct, "up"),
            )

        # Burn runway: cash equivalents (Cr) vs net cash flow (Cr, from screener.in)
        cash_cr_for_runway = advanced.si_cash_equivalents or 0  # already in Cr
        if cash_cr_for_runway > 0 and (basic.si_net_cf_annual or 0) < 0:
            burn = abs(basic.si_net_cf_annual)
            months = round((cash_cr_for_runway / burn) * 12, 1)
            runway_style = "green" if months >= 12 else "yellow" if months >= 6 else "red"
            cf_cash_table.add_row(
                "Cash Runway",
                Text(f"{months:.1f} months at current burn", style=runway_style),
                "-", "-", "-",
            )

        console.print(cf_cash_table)

    # ---- Section 3c: Debt Quality ----
    has_dq = any(v is not None for v in [advanced.si_long_term_borrowings, advanced.si_short_term_borrowings, advanced.si_total_borrowings])
    if has_dq:
        dq_table = Table(
            title="Debt Quality  [dim](annual, ₹ Cr)[/dim]",
            box=box.SIMPLE_HEAVY,
        )
        dq_table.add_column("Metric", style="dim", min_width=22)
        dq_table.add_column("Amount", justify="right")
        dq_table.add_column("% of Total", justify="right")
        dq_table.add_column("Signal", justify="left")

        # Values are already in Cr (from screener.in)
        total = advanced.si_total_borrowings if advanced.si_total_borrowings else None
        lt    = advanced.si_long_term_borrowings if advanced.si_long_term_borrowings else None
        st    = advanced.si_short_term_borrowings if advanced.si_short_term_borrowings else None

        def _pct_of_total(val: Optional[float]) -> str:
            if val is None or not total or total == 0:
                return "[dim]-[/dim]"
            return f"{val / total * 100:.1f}%"

        if total is not None:
            dq_table.add_row(
                "Total Borrowings",
                _cr(total),
                "-",
                _chg(advanced.si_borrowings_1y_pct, "down"),
            )

        if lt is not None:
            dq_table.add_row(
                "Long-term  [dim](> 1 year)[/dim]",
                Text(_cr(lt), style="green"),
                _pct_of_total(lt),
                Text("✓ stable, predictable repayment", style="dim green"),
            )

        if st is not None:
            st_pct = (st / total * 100) if total and total > 0 else None
            if st_pct is not None and st_pct > 75:
                st_signal = Text("✗ very high — needs frequent renewal (risk)", style="bold red")
            elif st_pct is not None and st_pct > 50:
                st_signal = Text("⚠ ST > LT — refinancing pressure", style="yellow")
            else:
                st_signal = Text("✓ manageable", style="dim green")
            dq_table.add_row(
                "Short-term  [dim](< 1 year)[/dim]",
                Text(_cr(st), style="red" if (st_pct or 0) > 50 else "yellow"),
                _pct_of_total(st),
                st_signal,
            )

        # ST vs LT comparison note
        if lt is not None and st is not None and lt > 0:
            ratio = st / lt
            if ratio > 1:
                dq_table.add_row(
                    "ST / LT Ratio",
                    Text(f"{ratio:.1f}x", style="red"),
                    "-",
                    Text(f"Short-term debt is {ratio:.1f}x the long-term — banks can recall at any time", style="red"),
                )
            else:
                dq_table.add_row(
                    "ST / LT Ratio",
                    Text(f"{ratio:.1f}x", style="green"),
                    "-",
                    Text("Long-term dominant — lower refinancing risk", style="dim green"),
                )

        console.print(dq_table)

    # ---- Section 3d: Real Estate Metrics ----
    if advanced.is_real_estate and any(v is not None for v in [
        advanced.re_presales_coverage, advanced.re_net_debt_post_advances,
        advanced.re_inventory_cr, advanced.re_customer_advances_cr,
    ]):
        re_pts = abd.get("real_estate", 0)
        re_table = Table(
            title=f"Real Estate Metrics  [dim](₹ Cr)[/dim]{_pts(re_pts)}",
            box=box.SIMPLE_HEAVY,
        )
        re_table.add_column("Metric", style="dim", min_width=28)
        re_table.add_column("Value", justify="right")
        re_table.add_column("Threshold", justify="right", style="dim")
        re_table.add_column("Signal", justify="left")

        def _re_signal(val, green, red, lower_better: bool = False) -> Text:
            if val is None:
                return Text("-", style="dim")
            if lower_better:
                if val <= green:
                    return Text("✓ healthy", style="green")
                elif val <= red:
                    return Text("⚠ elevated", style="yellow")
                return Text("✗ high", style="red")
            else:
                if val >= green:
                    return Text("✓ healthy", style="green")
                elif val >= red:
                    return Text("⚠ moderate", style="yellow")
                return Text("✗ weak", style="red")

        # Raw balance sheet amounts
        if advanced.re_inventory_cr is not None:
            re_table.add_row(
                "Inventory  [dim](land bank + WIP)[/dim]",
                _cr(advanced.re_inventory_cr),
                "-",
                Text("", style="dim"),
            )
        if advanced.re_customer_advances_cr is not None:
            re_table.add_row(
                "Customer Advances  [dim](pre-sales collected)[/dim]",
                _cr(advanced.re_customer_advances_cr),
                "-",
                Text("", style="dim"),
            )
        if advanced.re_trade_receivables_cr is not None:
            re_table.add_row(
                "Trade Receivables",
                _cr(advanced.re_trade_receivables_cr),
                "-",
                Text("", style="dim"),
            )

        # Computed ratios
        if advanced.re_presales_coverage is not None:
            pc = advanced.re_presales_coverage
            re_table.add_row(
                "Pre-sales Coverage  [dim](Advances / Borrowings)[/dim]",
                f"{pc:.0%}",
                "≥ 75%",
                _re_signal(pc, 0.75, 0.25, lower_better=False),
            )
        if advanced.re_net_debt_post_advances is not None:
            nd = advanced.re_net_debt_post_advances
            nd_style = "green" if nd <= 0.5 else "yellow" if nd <= 1.5 else "red"
            re_table.add_row(
                "Net Debt post-Advances  [dim](÷ Equity)[/dim]",
                Text(f"{nd:.2f}x", style=nd_style),
                "≤ 0.5x",
                _re_signal(nd, 0.5, 1.5, lower_better=True),
            )
        if advanced.re_inventory_years is not None:
            iy = advanced.re_inventory_years
            re_table.add_row(
                "Inventory Velocity  [dim](years of revenue)[/dim]",
                f"{iy:.1f}y",
                "≤ 3y",
                _re_signal(iy, 3.0, 6.0, lower_better=True),
            )

        console.print(re_table)

    # ---- Section 4: Shareholding ----
    hold_table = Table(title=f"Shareholding Pattern{_pts(abd.get('shareholding', 0))}{_subtitle(abd.get('shareholding_reasons', []))}", box=box.SIMPLE_HEAVY)
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
    current_pe = advanced.pe_ratio
    _pe_rows = [
        ("1 Year",  advanced.pe_mean_historical, advanced.pe_min_historical, advanced.pe_max_historical),
        ("5 Year",  advanced.pe_mean_5y,          advanced.pe_min_5y,         advanced.pe_max_5y),
        ("10 Year", advanced.pe_mean_10y,          advanced.pe_min_10y,        advanced.pe_max_10y),
    ]
    val_table = Table(
        title=f"Valuation  [dim](P/E current: {_fmt(current_pe, 'x')})[/dim]{_pts(abd.get('valuation', 0))}{_subtitle(abd.get('valuation_reasons', []))}",
        box=box.SIMPLE_HEAVY,
    )
    val_table.add_column("Period / Metric", style="dim", min_width=14)
    val_table.add_column("Mean P/E", justify="right")
    val_table.add_column("Low – High", justify="center", style="dim")
    val_table.add_column("vs Current", justify="right")

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
        val_table.add_row(period, _fmt(mean, "x"), range_str, vs)

    # P/B and EV/EBITDA as extra rows (no historical range)
    val_table.add_row("─" * 14, "─" * 8, "─" * 16, "─" * 20, style="dim")
    val_table.add_row("P/B Ratio", _fmt(advanced.pb_ratio, "x"), "-", "-")
    val_table.add_row("EV/EBITDA", _fmt(advanced.ev_ebitda, "x"), "-", "-")
    if advanced.peg_ratio is not None:
        peg_style = "green" if advanced.peg_ratio < 1.0 else "yellow" if advanced.peg_ratio <= 1.5 else "red"
        val_table.add_row("PEG Ratio", Text(f"{advanced.peg_ratio:.2f}x", style=peg_style), "< 1.5", "-")
    console.print(val_table)

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
