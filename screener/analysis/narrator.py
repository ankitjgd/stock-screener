"""AI-powered narrative: explains WHY a stock moved and predicts the future.

Analyses TWO time horizons (based on user selection):
  • 6 months  — recent quarter-level drivers + next 6M prediction
  • 1 year    — broader trend + next 1Y prediction
  • 2 years   — multi-year trend + next 1Y prediction
  • 3 years   — long-term structural trend + next 1Y prediction

Data used:
  • 6M & 1Y price action (sparkline, MA signals, high/low/change)
  • Financial metrics (revenue, PAT, EBITDA, ROE, ROCE, D/E, FCF, shareholding)
  • Valuation vs historical mean P/E
  • Audit findings from quarterly PDF scans (up to 13 quarters)
  • Screening flags (RED / YELLOW / GREEN)

Requires ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

try:
    import anthropic
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

from screener.analysis.basic_screen import BasicScreenResult, FlagLevel
from screener.analysis.advanced_screen import AdvancedScreenResult
from screener.data.pdf_scanner import AuditScanResult


_SYSTEM = (
    "You are a senior equity research analyst specialising in Indian listed companies. "
    "You combine fundamental analysis, technical price action, and audit quality assessment. "
    "You are data-driven, precise, and intellectually honest about uncertainty. "
    "Respond only with valid JSON — no markdown fences, no extra text."
)

_FOLLOWUP_SYSTEM = (
    "You are a senior equity research analyst specialising in Indian listed companies. "
    "You have just completed a detailed analysis of an Indian listed stock. "
    "The user is asking a follow-up question about your analysis. "
    "Answer clearly and concisely in 3–6 sentences, citing specific numbers from the data. "
    "Be honest when the data is insufficient to draw a firm conclusion. "
    "Do NOT use JSON — respond in plain conversational English."
)

_PROMPT = """\
Analyse the stock data below for the selected historical period, then give a 6-month forward prediction.

Selected historical period: {horizon} ({audit_label} of audit data)

Rules:
- Focus ONLY on the last {horizon} of price & fundamental history.
- Cite specific numbers from the data to support every claim.
- Do NOT invent news events or macro reasons not reflected in the data.
- If data is insufficient, say so and lower confidence accordingly.
- The prediction is ALWAYS for the next 6 months regardless of horizon.

═══════════════════════════════════════════════════
STOCK DATA
═══════════════════════════════════════════════════
{data_block}
═══════════════════════════════════════════════════

Return ONLY this JSON:
{{
  "historical": {{
    "period": "{horizon}",
    "trend_cause": "<2-4 sentences: primary reason(s) the stock moved the way it did over the last {horizon}, citing specific numbers>",
    "supporting_factors": ["<factor + evidence>", "<factor + evidence>", "<factor + evidence>"],
    "verdict": "<Bullish|Cautiously Bullish|Neutral|Cautiously Bearish|Bearish>"
  }},
  "prediction": {{
    "period": "6M",
    "outlook": "<2-4 sentences: next 6-month prediction with price targets or ranges where possible>",
    "outlook_basis": ["<key assumption or driver 1>", "<key assumption or driver 2>", "<key assumption or driver 3>"],
    "verdict": "<Bullish|Cautiously Bullish|Neutral|Cautiously Bearish|Bearish>"
  }},
  "key_risks": ["<specific risk 1>", "<specific risk 2>", "<specific risk 3>"],
  "key_catalysts": ["<specific catalyst 1>", "<specific catalyst 2>", "<specific catalyst 3>"],
  "confidence": "<High|Medium|Low>"
}}
"""

# Horizon metadata
_HORIZON_META = {
    "6M":  {"quarters": 2,  "audit_label": "~6 months",  "long_label": "6M"},
    "1Y":  {"quarters": 4,  "audit_label": "~1 year",    "long_label": "1Y"},
    "2Y":  {"quarters": 8,  "audit_label": "~2 years",   "long_label": "2Y"},
    "3Y":  {"quarters": 13, "audit_label": "~3 years",   "long_label": "3Y"},
}


def _fmt(val: Optional[float], suffix: str = "", decimals: int = 1) -> str:
    return f"{val:.{decimals}f}{suffix}" if val is not None else "N/A"


def _delta(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    return f"{val:+.2f}%"


def build_data_block(
    symbol: str,
    price_info: Optional[dict],
    price_trend: Optional[dict],
    basic: BasicScreenResult,
    advanced: AdvancedScreenResult,
    audit: Optional[AuditScanResult],
) -> str:
    """Build the text data block fed to Claude. Exported for reuse in follow-up Q&A."""
    lines: list[str] = []
    pt = price_trend or {}
    pi = price_info or {}

    current_price = pi.get("current_price")

    # ── Identity ────────────────────────────────────────────────────────
    lines += [
        f"Company : {pi.get('company_name', symbol)} ({symbol})",
        f"Sector  : {pi.get('sector', 'N/A')}",
        f"Price   : ₹{current_price:,.2f}" if current_price else "Price: N/A",
        f"Mkt Cap : ₹{pi['market_cap'] / 1e7:,.0f} Cr" if pi.get("market_cap") else "",
    ]

    # ── Price action ─────────────────────────────────────────────────────
    lines.append("\n── Price Action ──")

    chg6 = pt.get("change_6m_pct")
    hi6, lo6 = pt.get("high_6m"), pt.get("low_6m")
    pfh6 = pt.get("pct_from_high")
    lines += [
        f"  6M:  {_delta(chg6)} change  |  High ₹{hi6:,.0f}  Low ₹{lo6:,.0f}  |  {pfh6:+.1f}% from 6M high"
        if hi6 and lo6 and pfh6 is not None else "  6M: N/A",
        f"  6M Sparkline: {pt.get('sparkline', '')}  [{pt.get('date_start', '')} → {pt.get('date_end', '')}]",
    ]

    chg1 = pt.get("change_1y_pct")
    hi1, lo1 = pt.get("high_1y"), pt.get("low_1y")
    pfh1 = pt.get("pct_from_high_1y")
    lines += [
        f"  1Y:  {_delta(chg1)} change  |  High ₹{hi1:,.0f}  Low ₹{lo1:,.0f}  |  {pfh1:+.1f}% from 1Y high"
        if hi1 and lo1 and pfh1 is not None else "  1Y: N/A",
        f"  1Y Sparkline: {pt.get('sparkline_1y', '')}  [{pt.get('date_start_1y', '')} → {pt.get('date_end', '')}]",
    ]

    ma50, ma200 = pt.get("ma50"), pt.get("ma200")
    if ma50 and current_price:
        sig = "ABOVE ↑" if current_price > ma50 else "BELOW ↓"
        lines.append(f"  50D MA  ₹{ma50:,.1f}: price {sig}")
    if ma200 and current_price:
        sig = "ABOVE ↑" if current_price > ma200 else "BELOW ↓"
        lines.append(f"  200D MA ₹{ma200:,.1f}: price {sig}")

    # ── Financials ───────────────────────────────────────────────────────
    lines.append("\n── Financial Performance (quarterly) ──")
    lines += [
        f"  Revenue  QoQ/YoY : {_delta(basic.revenue_qoq_pct)} / {_delta(basic.revenue_yoy_pct)}",
        f"  PAT      QoQ/YoY : {_delta(basic.pat_qoq_pct)} / {_delta(basic.pat_yoy_pct)}",
        f"  EPS      QoQ/YoY : {_delta(basic.eps_qoq_pct)} / {_delta(basic.eps_yoy_pct)}",
        f"  EBITDA Margin    : {_fmt(basic.ebitda_margin_latest_pct, '%')}  (trend: {basic.ebitda_margin_trend or 'N/A'})",
    ]
    if basic.ocf_pat_ratio is not None:
        lines.append(f"  OCF/PAT Ratio    : {_fmt(basic.ocf_pat_ratio, 'x')}  (≥0.75 = healthy cash quality)")
    if basic.ocf_trend:
        lines.append(f"  OCF Trend        : {basic.ocf_trend}")

    lines.append("\n── Profitability ──")
    lines += [
        f"  ROE  : {_fmt(advanced.roe_pct, '%')}  (≥15% good)",
        f"  ROCE : {_fmt(advanced.roce_pct, '%')}  (≥12% good)",
    ]

    lines.append("\n── Debt ──")
    lines += [
        f"  D/E Ratio         : {_fmt(advanced.de_ratio, 'x')}  (≤1.0 safe)",
        f"  Interest Coverage : {_fmt(advanced.interest_coverage, 'x')}  (≥3x safe)",
        f"  Net Debt/EBITDA   : {_fmt(advanced.net_debt_to_ebitda, 'x')}  (≤3x safe)",
    ]

    lines.append("\n── Shareholding (latest QoQ / 6Q change) ──")
    lines += [
        f"  Promoters : {_fmt(advanced.promoter_holding_pct, '%')}  QoQ {_delta(advanced.promoter_holding_delta)}  6Q {_delta(advanced.promoter_holding_6q_delta)}",
        f"  Pledge    : {_fmt(advanced.promoter_pledge_pct, '%')}  QoQ {_delta(advanced.pledge_delta)}  6Q {_delta(advanced.pledge_6q_delta)}",
        f"  FII/FPI   : {_fmt(advanced.fii_holding_pct, '%')}  QoQ {_delta(advanced.fii_holding_delta)}  6Q {_delta(advanced.fii_holding_6q_delta)}",
        f"  DII       : {_fmt(advanced.dii_holding_pct, '%')}  QoQ {_delta(advanced.dii_holding_delta)}  6Q {_delta(advanced.dii_holding_6q_delta)}",
        f"  Public    : {_fmt(advanced.public_holding_pct, '%')}  QoQ {_delta(advanced.public_holding_delta)}  6Q {_delta(advanced.public_holding_6q_delta)}",
    ]

    lines.append("\n── Valuation ──")
    lines.append(f"  P/E current : {_fmt(advanced.pe_ratio, 'x')}")

    def _pe_hist_line(label: str, mean: Optional[float], lo: Optional[float], hi: Optional[float]) -> None:
        if mean is None:
            return
        range_str = f"  range {_fmt(lo, 'x')} – {_fmt(hi, 'x')}" if lo and hi else ""
        vs = ""
        if advanced.pe_ratio and advanced.pe_ratio > 0 and mean > 0:
            r = advanced.pe_ratio / mean
            vs = f"  → {'expensive' if r > 1.3 else 'cheap' if r < 0.8 else 'near mean'} ({r:.2f}x)"
        lines.append(f"  P/E mean ({label}): {_fmt(mean, 'x')}{range_str}{vs}")

    _pe_hist_line("1yr",  advanced.pe_mean_historical, advanced.pe_min_historical, advanced.pe_max_historical)
    _pe_hist_line("5yr",  advanced.pe_mean_5y,          advanced.pe_min_5y,         advanced.pe_max_5y)
    _pe_hist_line("10yr", advanced.pe_mean_10y,          advanced.pe_min_10y,        advanced.pe_max_10y)
    lines += [
        f"  P/B       : {_fmt(advanced.pb_ratio, 'x')}",
        f"  EV/EBITDA : {_fmt(advanced.ev_ebitda, 'x')}",
    ]

    # ── Screening flags ──────────────────────────────────────────────────
    all_flags = basic.flags + advanced.flags
    lines.append("\n── Screening Flags ──")
    if all_flags:
        for f in all_flags:
            lines.append(f"  [{f.level.value}] {f.category}: {f.message}")
    else:
        lines.append("  (none)")

    # ── Audit findings ───────────────────────────────────────────────────
    lines.append("\n── Audit Report Findings ──")
    if audit is None or not audit.quarters_scanned:
        lines.append("  (not scanned)")
    elif audit.is_clean:
        lines.append(f"  {len(audit.quarters_scanned)} quarters scanned — ALL CLEAN (no flags)")
    else:
        lines.append(f"  Quarters scanned: {', '.join(audit.quarters_scanned)}")
        for f in audit.flags:
            lines.append(f"  [{f.level}] {f.quarter} — {f.category}: {f.context[:140]}")

    # ── Score ────────────────────────────────────────────────────────────
    from screener.reports.formatter import _combined_score, _score_label
    score = _combined_score(basic, advanced)
    label, _ = _score_label(score)
    lines.append(f"\n── Screening Score: {score}/100 ({label}) ──")

    return "\n".join(l for l in lines if l is not None)


def generate_narrative(
    symbol: str,
    price_info: Optional[dict],
    price_trend: Optional[dict],
    basic: BasicScreenResult,
    advanced: AdvancedScreenResult,
    audit: Optional[AuditScanResult] = None,
    horizon: str = "1Y",
    data_block: Optional[str] = None,
) -> tuple[Optional[dict], str]:
    """
    Call Claude to generate dual-horizon narrative analysis.

    Returns (narrative_dict, data_block_str).
    narrative_dict keys:
        six_month  (trend_cause, supporting_factors, outlook, outlook_basis, verdict)
        one_year   (same structure — covers the selected horizon for medium-term)
        key_risks, key_catalysts, confidence
    Returns (None, data_block) if API unavailable or call fails.
    """
    if data_block is None:
        data_block = build_data_block(symbol, price_info, price_trend, basic, advanced, audit)

    if not _AVAILABLE or not os.environ.get("ANTHROPIC_API_KEY"):
        return None, data_block

    meta = _HORIZON_META.get(horizon, _HORIZON_META["1Y"])
    model = os.environ.get("SCREENER_NARRATOR_MODEL", "claude-opus-4-6")
    prompt = _PROMPT.format(
        data_block=data_block,
        horizon=horizon,
        audit_quarters=meta["quarters"],
        audit_label=meta["audit_label"],
    )

    try:
        client = anthropic.Anthropic()
        with client.messages.stream(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            response = stream.get_final_message()

        raw = next(
            (b.text for b in response.content if getattr(b, "type", "") == "text"),
            "",
        ).strip()

        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None, data_block
        return json.loads(m.group()), data_block
    except Exception as e:
        return {"_error": str(e)}, data_block


def answer_followup(
    question: str,
    data_block: str,
    narrative: dict,
) -> str:
    """
    Answer a counter/follow-up question about the narrative analysis.

    Returns plain text response (not JSON).
    """
    if not _AVAILABLE or not os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY not set."

    model = os.environ.get("SCREENER_NARRATOR_MODEL", "claude-opus-4-6")
    narr_str = json.dumps(narrative, indent=2)

    context = (
        "STOCK DATA ANALYSED:\n"
        f"{data_block}\n\n"
        "YOUR PREVIOUS ANALYSIS (JSON):\n"
        f"{narr_str}\n\n"
        f"USER'S FOLLOW-UP QUESTION:\n{question}"
    )

    try:
        client = anthropic.Anthropic()
        with client.messages.stream(
            model=model,
            max_tokens=2048,
            thinking={"type": "adaptive"},
            system=_FOLLOWUP_SYSTEM,
            messages=[{"role": "user", "content": context}],
        ) as stream:
            response = stream.get_final_message()

        return next(
            (b.text for b in response.content if getattr(b, "type", "") == "text"),
            "No response generated.",
        ).strip()
    except Exception as e:
        return f"Error generating response: {e}"
