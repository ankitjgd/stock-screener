"""Basic screener: revenue, PAT, EBITDA, EPS, OCF quality."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml


_FINANCIAL_KEYWORDS = ("financial", "bank", "nbfc", "insurance", "lending", "housing finance", "asset management")

# Sectors where Ind AS 116 lease accounting dominates — depreciation/interest are lease repayments,
# not capex. OCF/PAT is meaningless; OCF/EBITDA is the correct cash quality metric.
_LEASE_HEAVY_KEYWORDS = ("cinema", "multiplex", "film", "aviation", "airline", "hotel", "hospitality",
                         "retail", "quick service", "restaurant", "telecom", "tower", "media",
                         "entertainment", "communication")


def _is_financial(sector: Optional[str]) -> bool:
    if not sector:
        return False
    s = sector.lower()
    return any(kw in s for kw in _FINANCIAL_KEYWORDS)


def _is_lease_heavy(sector: Optional[str], industry: Optional[str] = None) -> bool:
    """Detect Ind AS 116 lease-heavy companies by sector/industry label."""
    for text in [sector, industry]:
        if text and any(kw in text.lower() for kw in _LEASE_HEAVY_KEYWORDS):
            return True
    return False


def _is_lease_heavy_by_data(
    si_ocf_ebitda_ratio: Optional[float],
    si_ocf_pat_ratio: Optional[float],
) -> bool:
    """Math-based fallback: detect Ind AS 116 distortion from the numbers themselves.

    If OCF/EBITDA is healthy (> 0.5) but OCF/PAT is wildly negative (< -5),
    the gap is almost certainly lease depreciation eating into PAT.
    """
    if si_ocf_ebitda_ratio is None or si_ocf_pat_ratio is None:
        return False
    return si_ocf_ebitda_ratio > 0.5 and si_ocf_pat_ratio < -5


def _load_cfg() -> dict:
    return yaml.safe_load(
        (Path(__file__).parent.parent.parent / "config" / "thresholds.yaml").read_text()
    )


class FlagLevel(str, Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"


@dataclass
class ScreenFlag:
    level: FlagLevel
    category: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.value}] {self.category}: {self.message}"


@dataclass
class BasicScreenResult:
    symbol: str
    # Growth metrics
    revenue_qoq_pct: Optional[float] = None
    revenue_yoy_pct: Optional[float] = None       # avg YoY over 5Y
    revenue_yoy_3y_pct: Optional[float] = None    # avg YoY over 3Y
    pat_qoq_pct: Optional[float] = None
    pat_yoy_pct: Optional[float] = None
    pat_yoy_3y_pct: Optional[float] = None
    pat_yoy_periods: int = 5           # actual periods used (5 or 4 if fallback)
    pat_yoy_3y_periods: int = 3        # actual periods used (3 or 2 if fallback)
    pat_qoq_suppressed: bool = False   # True when QoQ is None due to majority-negative-base quarters
    eps_qoq_pct: Optional[float] = None
    eps_yoy_pct: Optional[float] = None
    eps_yoy_3y_pct: Optional[float] = None
    eps_yoy_periods: int = 5           # actual periods used (5 or 4 if fallback)
    eps_yoy_3y_periods: int = 3        # actual periods used (3 or 2 if fallback)
    pat_cagr_3y: Optional[float] = None        # 3Y PAT CAGR (endpoint-to-endpoint, used for PEG)
    # Margin
    ebitda_margin_latest_pct: Optional[float] = None
    ebitda_margin_qoq_pp: Optional[float] = None    # QoQ change in EBITDA margin (pp)
    ebitda_margin_3y_pp: Optional[float] = None     # 3Y change in EBITDA margin (pp, ~12Q)
    ebitda_margin_5y_pp: Optional[float] = None     # 5Y change in EBITDA margin (pp, ~20Q)
    ebitda_margin_trend: Optional[str] = None  # improving | stable | deteriorating
    # Cash quality (yfinance quarterly — fallback)
    ocf_pat_ratio: Optional[float] = None
    ocf_trend: Optional[str] = None  # improving | stable | deteriorating
    # Absolute latest values
    revenue_latest: Optional[float] = None
    pat_latest: Optional[float] = None
    eps_latest: Optional[float] = None
    latest_quarter: Optional[str] = None   # label of the most recent quarter, e.g. "Dec 2024"
    ocf_latest: Optional[float] = None
    # Annual cash flows from screener.in (primary, in Crores)
    si_ocf_annual: Optional[float] = None   # Cash from Operating Activity
    si_icf_annual: Optional[float] = None   # Cash from Investing Activity
    si_fcf_annual: Optional[float] = None   # FCF = OCF + ICF
    si_cff_annual: Optional[float] = None   # Cash from Financing Activity
    si_pat_annual: Optional[float] = None      # Annual PAT (used in OCF/PAT ratio)
    si_net_cf_annual: Optional[float] = None  # Net Cash Flow
    si_net_cf_1y_pct: Optional[float] = None  # Net Cash Flow 1Y % change
    si_net_cf_3y_pct: Optional[float] = None  # Net Cash Flow 3Y % change
    si_net_cf_5y_pct: Optional[float] = None  # Net Cash Flow 5Y % change
    si_ocf_trend: Optional[str] = None      # 5yr trend of annual OCF
    si_ocf_pat_ratio: Optional[float] = None  # annual OCF / annual PAT
    si_ebitda_annual: Optional[float] = None  # annual Operating Profit (Cr) — for OCF/EBITDA
    si_ocf_ebitda_ratio: Optional[float] = None  # annual OCF / annual EBITDA (Ind AS 116 sectors)
    # Asset quality — financial sector only
    gross_npa_pct: Optional[float] = None
    gross_npa_1y_chg: Optional[float] = None   # pp change vs 1 year ago
    gross_npa_2y_chg: Optional[float] = None   # pp change vs 2 years ago
    gross_npa_3y_chg: Optional[float] = None   # pp change vs 3 years ago
    net_npa_pct: Optional[float] = None
    net_npa_1y_chg: Optional[float] = None
    net_npa_2y_chg: Optional[float] = None
    net_npa_3y_chg: Optional[float] = None
    # Flags and score
    flags: list[ScreenFlag] = field(default_factory=list)
    score: int = 0
    score_breakdown: dict = field(default_factory=dict)  # section → points


def _safe_pct_change(series: pd.Series, periods: int = 1) -> Optional[float]:
    """Safe percentage change, handles NaN/zero."""
    try:
        s = series.dropna()
        if len(s) < periods + 1:
            return None
        prev = s.iloc[-(periods + 1)]
        curr = s.iloc[-1]
        if prev == 0 or pd.isna(prev) or pd.isna(curr):
            return None
        return round(((curr - prev) / abs(prev)) * 100, 2)
    except Exception:
        return None


def _avg_qoq_pct(series: pd.Series, n: int = 5) -> Optional[float]:
    """Average period-over-period % change over the last n periods.

    Skips transitions where the base period is negative (e.g. loss year to
    profit year) — pct_change() gives a meaningless sign-flip in those cases.
    Returns None if fewer than 2 valid transitions remain after filtering.
    """
    try:
        s = series.dropna()
        if len(s) < n + 1:
            return None
        # Take the last n+1 values so we have n transitions
        window = s.iloc[-(n + 1):]
        changes = []
        for i in range(len(window) - 1):
            prev, curr = float(window.iloc[i]), float(window.iloc[i + 1])
            if prev == 0 or pd.isna(prev) or pd.isna(curr):
                continue
            if prev < 0 or curr < 0:
                # Skip transitions involving a negative value on either side:
                # negative base → sign-flip % is meaningless; positive→negative → equally distorting
                continue
            changes.append(((curr - prev) / abs(prev)) * 100)
        if not changes:
            return None
        # If more than half the transitions were skipped (chronic losses),
        # the average is based on too few data points to be meaningful.
        total_transitions = len(window) - 1
        if len(changes) < total_transitions / 2:
            return None
        return round(sum(changes) / len(changes), 2)
    except Exception:
        return None


def _is_chronic_loss_suppressed(series: pd.Series, n: int = 5) -> bool:
    """Returns True if _avg_qoq_pct would return None due to majority-negative-base suppression.

    Distinguishes "no data" (False) from "data exists but mostly loss quarters" (True).
    """
    try:
        s = series.dropna()
        if len(s) < n + 1:
            return False  # insufficient data — not a suppression case
        window = s.iloc[-(n + 1):]
        total_transitions = len(window) - 1
        neg_base_count = sum(1 for i in range(total_transitions) if float(window.iloc[i]) < 0)
        return neg_base_count >= total_transitions / 2
    except Exception:
        return False


def _adjust_eps_for_exceptional(eps: pd.Series, raw_pat: pd.Series, adj_pat: pd.Series) -> pd.Series:
    """Scale EPS by the same ratio as the PAT adjustment (exceptional items removed).
    adjusted_EPS = EPS × (adj_PAT / raw_PAT) — mathematically correct since
    EPS = PAT / shares and shares are unchanged within a year.
    """
    if raw_pat is None or raw_pat.dropna().empty:
        return eps
    adjusted = eps.copy().astype(float)
    for idx in eps.index:
        raw_p = float(raw_pat.get(idx, float("nan")))
        adj_p = float(adj_pat.get(idx, float("nan")))
        if pd.isna(raw_p) or pd.isna(adj_p) or raw_p == 0:
            continue
        adjusted[idx] = float(eps.get(idx, float("nan"))) * (adj_p / raw_p)
    return adjusted


def _adjust_pat_for_exceptional(pat: pd.Series, exceptional: pd.Series) -> pd.Series:
    """Subtract actual exceptional items from PAT for each year they appear.
    `exceptional` is the 'Exceptional Items' sub-row fetched from screener.in's
    schedules AJAX API — so values are exact, not estimated.
    """
    if exceptional is None or exceptional.dropna().empty:
        return pat
    exc = exceptional.reindex(pat.index).fillna(0).astype(float)
    adjusted = pat.copy().astype(float)
    for idx in pat.index:
        exc_val = exc.get(idx, 0.0)
        if exc_val != 0.0 and not pd.isna(exc_val):
            adjusted[idx] = float(pat.get(idx, float("nan"))) - exc_val
    return adjusted


def _cagr_pct(series: pd.Series, n: int) -> Optional[float]:
    """Compound Annual Growth Rate over n periods using start/end annual values.
    Requires a positive base value. Returns None if insufficient data or base <= 0."""
    try:
        s = series.dropna()
        if len(s) < n + 1:
            return None
        prev = float(s.iloc[-(n + 1)])
        curr = float(s.iloc[-1])
        if prev <= 0:
            return None
        return round(((curr / prev) ** (1.0 / n) - 1) * 100, 2)
    except Exception:
        return None


def _avg_qoq_pct_with_fallback(series: pd.Series, n: int) -> tuple[Optional[float], int]:
    """Try _avg_qoq_pct(series, n); if None, fall back to n-1.

    Returns (value, actual_periods_used).
    Fallback is only attempted once (n → n-1) and only when n >= 2.
    """
    val = _avg_qoq_pct(series, n)
    if val is not None or n < 2:
        return val, n
    val = _avg_qoq_pct(series, n - 1)
    return val, (n - 1 if val is not None else n)


def _avg_yoy_pct(series: pd.Series, n: int = 5) -> Optional[float]:
    """Average of the last n YoY % changes (each quarter vs same quarter 1 year prior)."""
    try:
        s = series.dropna()
        if len(s) < n + 4:
            return None
        changes = []
        for i in range(n):
            curr = s.iloc[-(1 + i)]
            prev = s.iloc[-(5 + i)]   # 4 quarters back = same quarter last year
            if prev == 0 or pd.isna(prev) or pd.isna(curr):
                continue
            changes.append(((curr - prev) / abs(prev)) * 100)
        if not changes:
            return None
        return round(sum(changes) / len(changes), 2)
    except Exception:
        return None


def _trend(series: pd.Series, window: int = 4) -> str:
    """Determine trend of last N values: improving/stable/deteriorating."""
    try:
        s = series.dropna().tail(window)
        if len(s) < 3:
            return "insufficient_data"
        diffs = s.diff().dropna()
        pos = (diffs > 0).sum()
        neg = (diffs < 0).sum()
        if pos >= len(diffs) * 0.6:
            return "improving"
        elif neg >= len(diffs) * 0.6:
            return "deteriorating"
        return "stable"
    except Exception:
        return "unknown"


def _find_col(df: pd.DataFrame, keywords: list[str]) -> Optional[str]:
    """Find column containing any of the keywords (case-insensitive)."""
    for col in df.columns:
        col_lower = str(col).lower()
        if any(kw.lower() in col_lower for kw in keywords):
            return col
    return None


def _col_as_series(df: pd.DataFrame, col: str) -> pd.Series:
    """Return a numeric Series for col, safely handling duplicate column names."""
    result = df[col]
    if isinstance(result, pd.DataFrame):
        result = result.iloc[:, 0]  # duplicate columns → take first
    return result.apply(pd.to_numeric, errors="coerce")


def _si_clean(val: str) -> float:
    """Parse screener.in cell values: '2,008', '2%', '16.94', '-', etc."""
    s = str(val).strip().replace(",", "").replace("%", "").replace("₹", "").replace("Cr.", "")
    if not s or s in ("-", "", "NA", "N/A", "--"):
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _si_row_series(si_df: pd.DataFrame, keywords: list[str], skip_ttm: bool = False) -> Optional[pd.Series]:
    """
    Extract a time series from screener.in DataFrame.
    Structure: rows = metrics, cols = [label_col, period1, period2, ..., periodN]
    Returns a numeric Series indexed 0..N-1 (chronological, oldest→newest).
    skip_ttm=True drops the last column if its header is 'TTM'.
    """
    cols = list(si_df.columns)
    # Determine which column indices to include (skip label col 0, optionally skip TTM)
    end_idx = len(cols)
    if skip_ttm and str(cols[-1]).strip().upper() == "TTM":
        end_idx -= 1

    for _, row in si_df.iterrows():
        label = str(row.iloc[0]).lower().strip()
        if any(kw.lower() in label for kw in keywords):
            vals = [_si_clean(row.iloc[i]) for i in range(1, end_idx)]
            return pd.Series(vals, dtype=float)
    return None


def _si_pct_change(series: pd.Series, periods: int) -> Optional[float]:
    """% change between the latest value and `periods` years ago in a screener.in series."""
    clean = series.dropna()
    if len(clean) < periods + 1:
        return None
    prev, curr = clean.iloc[-(periods + 1)], clean.iloc[-1]
    if prev == 0 or pd.isna(prev) or pd.isna(curr):
        return None
    return round(((curr - prev) / abs(prev)) * 100, 2)


def _patch_stub_annual(si_annual: pd.DataFrame, si_quarterly: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Drop stub annual columns (e.g. 'Mar 2026 9m') that cover less than a full year.

    A stub column has a header matching '<Month> <Year> <N>m' (e.g. 'Mar 2026 9m').
    Including partial-year data in YoY comparisons produces misleading growth numbers
    (e.g. 9-month revenue vs previous 12-month revenue). Dropping it means we fall back
    to the last complete fiscal year, which gives accurate like-for-like comparisons.
    TTM columns are kept — they represent a full rolling 12-month period.
    """
    import re
    stub_pat = re.compile(r'\b\d{1,2}m\b', re.IGNORECASE)
    keep = [c for c in si_annual.columns if not stub_pat.search(str(c))]
    return si_annual[keep] if len(keep) < len(si_annual.columns) else si_annual


class BasicScreener:
    """Analyses quarterly income/cashflow for basic quality signals."""

    def __init__(self):
        self.cfg = _load_cfg()

    def screen(
        self,
        symbol: str,
        si_quarterly_df: Optional[pd.DataFrame] = None,
        si_annual_df: Optional[pd.DataFrame] = None,
        si_cashflow_df: Optional[pd.DataFrame] = None,
        sector: Optional[str] = None,
        industry: Optional[str] = None,
    ) -> BasicScreenResult:
        """All financial data from screener.in exclusively."""
        result = BasicScreenResult(symbol=symbol)
        cfg_g = self.cfg["growth"]
        cfg_p = self.cfg["profitability"]

        si_ok = si_quarterly_df is not None and not si_quarterly_df.empty
        ann_ok = si_annual_df is not None and not si_annual_df.empty

        # Capture the latest quarter label from column headers (e.g. "Dec 2024")
        if si_ok:
            q_cols = [c for c in si_quarterly_df.columns[1:] if str(c).strip()]
            if q_cols:
                result.latest_quarter = str(q_cols[-1]).strip()

        if not si_ok:
            result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Data", "No screener.in quarterly data available"))
            result.score = 0
            return result

        financial = _is_financial(sector)
        # lease_heavy is initially sector/industry based; updated after OCF/EBITDA is computed
        lease_heavy = _is_lease_heavy(sector, industry)

        # ── Revenue ────────────────────────────────────────────────────────
        # Banks use "Interest Earned" / "Revenue from operations" instead of "Sales"
        rev_keys = ["Sales", "Revenue from operations", "Revenue"]
        if financial:
            rev_keys = ["Interest Earned", "Interest Income", "Revenue from operations", "Total Income", "Sales", "Revenue"]
        rev = _si_row_series(si_quarterly_df, rev_keys)
        if rev is not None and not rev.dropna().empty:
            result.revenue_latest = float(rev.dropna().iloc[-1]) * 1e7  # Cr → INR
            result.revenue_qoq_pct = _avg_qoq_pct(rev, 5)
            ann_rev = _si_row_series(si_annual_df, rev_keys, skip_ttm=True) if ann_ok else None
            result.revenue_yoy_pct = _avg_qoq_pct(ann_rev, 5) if (ann_rev is not None and not ann_rev.dropna().empty) else _avg_yoy_pct(rev, 5)
            result.revenue_yoy_3y_pct = _avg_qoq_pct(ann_rev, 3) if (ann_rev is not None and not ann_rev.dropna().empty) else _avg_yoy_pct(rev, 3)

        # ── PAT / Net Profit ───────────────────────────────────────────────
        pat_keys = ["Net Profit", "PAT", "Profit after tax"]
        pat = _si_row_series(si_quarterly_df, pat_keys)
        if pat is not None and not pat.dropna().empty:
            result.pat_latest = float(pat.dropna().iloc[-1]) * 1e7  # Cr → INR
            result.pat_qoq_pct = _avg_qoq_pct(pat, 5)
            if result.pat_qoq_pct is None:
                result.pat_qoq_suppressed = _is_chronic_loss_suppressed(pat, 5)
            ann_pat = _si_row_series(si_annual_df, pat_keys, skip_ttm=True) if ann_ok else None
            ann_pat_norm = None  # normalised PAT (exceptional items removed) — also used for EPS
            if ann_pat is not None and not ann_pat.dropna().empty:
                ann_exc = _si_row_series(si_annual_df, ["Exceptional items", "Exceptional Items", "Exceptional item"], skip_ttm=True)
                ann_pat_norm = _adjust_pat_for_exceptional(ann_pat, ann_exc)
                result.pat_yoy_pct, result.pat_yoy_periods = _avg_qoq_pct_with_fallback(ann_pat_norm, 5)
                result.pat_yoy_3y_pct, result.pat_yoy_3y_periods = _avg_qoq_pct_with_fallback(ann_pat_norm, 3)
                result.pat_cagr_3y = _cagr_pct(ann_pat, 3)  # raw PAT (not exceptional-adjusted) — matches screener.in's "Profit Var 3Yrs"
            else:
                result.pat_yoy_pct = _avg_yoy_pct(pat, 5)
                result.pat_yoy_3y_pct = _avg_yoy_pct(pat, 3)

        # ── EPS ────────────────────────────────────────────────────────────
        eps = _si_row_series(si_quarterly_df, ["EPS in Rs", "EPS"])
        if eps is not None and not eps.dropna().empty:
            result.eps_latest = float(eps.dropna().iloc[-1])
            result.eps_qoq_pct = _avg_qoq_pct(eps, 5)
            ann_eps = _si_row_series(si_annual_df, ["EPS in Rs", "EPS"], skip_ttm=True) if ann_ok else None
            if ann_eps is not None and not ann_eps.dropna().empty:
                if ann_pat_norm is not None and ann_pat is not None:
                    ann_eps_norm = _adjust_eps_for_exceptional(ann_eps, ann_pat, ann_pat_norm)
                else:
                    ann_eps_norm = ann_eps
                result.eps_yoy_pct, result.eps_yoy_periods = _avg_qoq_pct_with_fallback(ann_eps_norm, 5)
                result.eps_yoy_3y_pct, result.eps_yoy_3y_periods = _avg_qoq_pct_with_fallback(ann_eps_norm, 3)
            else:
                result.eps_yoy_pct = _avg_yoy_pct(eps, 5)
                result.eps_yoy_3y_pct = _avg_yoy_pct(eps, 3)

        # ── EBITDA / Operating margin — screener.in OPM% ──────────────────
        # For sectors with lumpy quarterly revenue (real estate, construction,
        # capital goods) use annual OPM% — a single bad quarter skews the latest value.
        _LUMPY_SECTORS = ("real estate", "construction", "infrastructure", "capital goods", "engineering")
        _use_annual_opm = sector and any(kw in sector.lower() for kw in _LUMPY_SECTORS)
        opm_src = si_annual_df if (_use_annual_opm and ann_ok) else si_quarterly_df
        opm_skip_ttm = _use_annual_opm
        opm_pct = _si_row_series(opm_src, ["OPM %", "OPM%", "OPM"], skip_ttm=opm_skip_ttm)
        if opm_pct is not None and not opm_pct.dropna().empty:
            _opm_clean = opm_pct.dropna()
            result.ebitda_margin_latest_pct = round(float(_opm_clean.iloc[-1]), 2)
            result.ebitda_margin_trend = _trend(opm_pct, window=8)
            if len(_opm_clean) >= 2:
                result.ebitda_margin_qoq_pp = round(float(_opm_clean.iloc[-1]) - float(_opm_clean.iloc[-2]), 2)
            if len(_opm_clean) >= 13:
                result.ebitda_margin_3y_pp = round(float(_opm_clean.iloc[-1]) - float(_opm_clean.iloc[-13]), 2)
            if len(_opm_clean) >= 21:
                result.ebitda_margin_5y_pp = round(float(_opm_clean.iloc[-1]) - float(_opm_clean.iloc[-21]), 2)

        # ── Annual cash flows — screener.in ───────────────────────────────
        if si_cashflow_df is not None and not si_cashflow_df.empty:
            ocf_s = _si_row_series(si_cashflow_df, ["Cash from Operating", "Operating Activity", "operating"])
            icf_s = _si_row_series(si_cashflow_df, ["Cash from Investing", "Investing Activity", "investing"])
            cff_s = _si_row_series(si_cashflow_df, ["Cash from Financing", "Financing Activity", "financing"])
            ncf_s = _si_row_series(si_cashflow_df, ["Net Cash Flow", "Net Cash", "net cash"])

            if ocf_s is not None and not ocf_s.dropna().empty:
                result.si_ocf_annual = float(ocf_s.dropna().iloc[-1])
                result.si_ocf_trend = _trend(ocf_s, window=5)
            if icf_s is not None and not icf_s.dropna().empty:
                result.si_icf_annual = float(icf_s.dropna().iloc[-1])
            if cff_s is not None and not cff_s.dropna().empty:
                result.si_cff_annual = float(cff_s.dropna().iloc[-1])
            if ncf_s is not None and not ncf_s.dropna().empty:
                result.si_net_cf_annual = float(ncf_s.dropna().iloc[-1])
                result.si_net_cf_1y_pct = _si_pct_change(ncf_s, 1)
                result.si_net_cf_3y_pct = _si_pct_change(ncf_s, 3)
                result.si_net_cf_5y_pct = _si_pct_change(ncf_s, 5)
            if result.si_ocf_annual is not None and result.si_icf_annual is not None:
                result.si_fcf_annual = result.si_ocf_annual + result.si_icf_annual

            # OCF/PAT ratio using annual data — more reliable than quarterly
            if ann_ok and result.si_ocf_annual is not None:
                ann_pat = _si_row_series(si_annual_df, ["Net Profit", "PAT", "Profit after tax"], skip_ttm=True)
                if ann_pat is not None and not ann_pat.dropna().empty:
                    ann_pat_latest = float(ann_pat.dropna().iloc[-1])
                    if ann_pat_latest != 0:
                        result.si_pat_annual = ann_pat_latest
                        result.si_ocf_pat_ratio = round(result.si_ocf_annual / ann_pat_latest, 2)
                        # Prefer annual OCF/PAT ratio over quarterly
                        result.ocf_pat_ratio = result.si_ocf_pat_ratio

                # OCF/EBITDA — valid for all sectors, essential for Ind AS 116 lease-heavy companies
                ann_op = _si_row_series(si_annual_df, ["Operating Profit", "EBITDA"], skip_ttm=True)
                if ann_op is not None and not ann_op.dropna().empty:
                    ebitda = float(ann_op.dropna().iloc[-1])
                    result.si_ebitda_annual = ebitda
                    if ebitda != 0:
                        result.si_ocf_ebitda_ratio = round(result.si_ocf_annual / ebitda, 2)

        # Math-based Ind AS 116 detection: healthy OCF/EBITDA but wildly negative OCF/PAT
        # catches companies like Devyani (sector="Consumer Cyclical") missed by keyword matching
        if not lease_heavy:
            lease_heavy = _is_lease_heavy_by_data(result.si_ocf_ebitda_ratio, result.si_ocf_pat_ratio)

        # ── NPA (financial sector only) ────────────────────────────────────
        if financial:
            def _npa_chg(series: pd.Series, periods: int) -> Optional[float]:
                """Absolute pp change: latest minus N quarters ago (4Q = 1Y)."""
                s = series.dropna()
                idx = periods * 4  # quarters per year
                if len(s) < idx + 1:
                    return None
                curr, prev = float(s.iloc[-1]), float(s.iloc[-(idx + 1)])
                return round(curr - prev, 2)

            gnpa = _si_row_series(si_quarterly_df, ["Gross NPA"])
            nnpa = _si_row_series(si_quarterly_df, ["Net NPA"])
            if gnpa is not None and not gnpa.dropna().empty:
                result.gross_npa_pct = float(gnpa.dropna().iloc[-1])
                result.gross_npa_1y_chg = _npa_chg(gnpa, 1)
                result.gross_npa_2y_chg = _npa_chg(gnpa, 2)
                result.gross_npa_3y_chg = _npa_chg(gnpa, 3)
            if nnpa is not None and not nnpa.dropna().empty:
                result.net_npa_pct = float(nnpa.dropna().iloc[-1])
                result.net_npa_1y_chg = _npa_chg(nnpa, 1)
                result.net_npa_2y_chg = _npa_chg(nnpa, 2)
                result.net_npa_3y_chg = _npa_chg(nnpa, 3)

        # --- Flags ---
        self._apply_flags(result, cfg_g, cfg_p, sector=sector, lease_heavy=lease_heavy)
        result.score = self._compute_score(result, cfg_g, cfg_p, sector=sector, lease_heavy=lease_heavy)
        return result

    def _apply_flags(
        self,
        result: BasicScreenResult,
        cfg_g: dict,
        cfg_p: dict,
        sector: Optional[str] = None,
        lease_heavy: bool = False,
    ) -> None:
        financial = _is_financial(sector)
        # Revenue growth
        if result.revenue_yoy_pct is not None:
            if result.revenue_yoy_pct < 0:
                result.flags.append(ScreenFlag(FlagLevel.RED, "Growth", f"Revenue declining YoY: {result.revenue_yoy_pct:.1f}%"))
            elif result.revenue_yoy_pct < cfg_g["revenue_yoy_min_pct"]:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Growth", f"Weak revenue growth YoY: {result.revenue_yoy_pct:.1f}% (min {cfg_g['revenue_yoy_min_pct']}%)"))
            else:
                result.flags.append(ScreenFlag(FlagLevel.GREEN, "Growth", f"Revenue growth YoY: {result.revenue_yoy_pct:.1f}%"))

        # PAT growth
        if result.pat_yoy_pct is not None:
            if result.pat_yoy_pct < 0:
                result.flags.append(ScreenFlag(FlagLevel.RED, "Growth", f"PAT declining YoY: {result.pat_yoy_pct:.1f}%"))
            elif result.pat_yoy_pct < cfg_g["pat_yoy_min_pct"]:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Growth", f"Weak PAT growth YoY: {result.pat_yoy_pct:.1f}%"))
            else:
                result.flags.append(ScreenFlag(FlagLevel.GREEN, "Growth", f"PAT growth YoY: {result.pat_yoy_pct:.1f}%"))

        # PAT QoQ suppressed — majority of recent 5 quarters had losses or negative base
        if result.pat_qoq_suppressed:
            result.flags.append(ScreenFlag(FlagLevel.RED, "Growth",
                "PAT QoQ trend unavailable — majority of recent quarters had losses (chronic PAT weakness)"))

        # EPS growth
        if result.eps_yoy_pct is not None:
            if result.eps_yoy_pct < 0:
                result.flags.append(ScreenFlag(FlagLevel.RED, "EPS", f"EPS declining YoY: {result.eps_yoy_pct:.1f}%"))
            elif result.eps_yoy_pct < cfg_g["eps_yoy_min_pct"]:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "EPS", f"EPS growth weak: {result.eps_yoy_pct:.1f}%"))
            else:
                result.flags.append(ScreenFlag(FlagLevel.GREEN, "EPS", f"EPS growth YoY: {result.eps_yoy_pct:.1f}%"))

        # EBITDA margin
        if result.ebitda_margin_latest_pct is not None:
            if result.ebitda_margin_latest_pct < cfg_p["ebitda_margin_min_pct"]:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Margin", f"Low EBITDA margin: {result.ebitda_margin_latest_pct:.1f}%"))
        if result.ebitda_margin_trend == "deteriorating":
            result.flags.append(ScreenFlag(FlagLevel.RED, "Margin", "EBITDA margin deteriorating over 8 quarters"))
        elif result.ebitda_margin_trend == "improving":
            result.flags.append(ScreenFlag(FlagLevel.GREEN, "Margin", "EBITDA margin improving trend"))

        # NPA quality — financial sector only
        if financial:
            cfg_fin = self.cfg["financial_sector"] if hasattr(self, 'cfg') else {}
            gnpa_green = cfg_fin.get("gross_npa_green_pct", 3.0)
            gnpa_red   = cfg_fin.get("gross_npa_red_pct", 7.0)
            nnpa_green = cfg_fin.get("net_npa_green_pct", 1.0)
            nnpa_red   = cfg_fin.get("net_npa_red_pct", 3.0)
            if result.gross_npa_pct is not None:
                if result.gross_npa_pct > gnpa_red:
                    result.flags.append(ScreenFlag(FlagLevel.RED, "AssetQuality", f"High Gross NPA: {result.gross_npa_pct:.2f}% (red > {gnpa_red}%)"))
                elif result.gross_npa_pct > gnpa_green:
                    result.flags.append(ScreenFlag(FlagLevel.YELLOW, "AssetQuality", f"Elevated Gross NPA: {result.gross_npa_pct:.2f}% (green < {gnpa_green}%)"))
                else:
                    result.flags.append(ScreenFlag(FlagLevel.GREEN, "AssetQuality", f"Healthy Gross NPA: {result.gross_npa_pct:.2f}%"))
            if result.net_npa_pct is not None:
                if result.net_npa_pct > nnpa_red:
                    result.flags.append(ScreenFlag(FlagLevel.RED, "AssetQuality", f"High Net NPA: {result.net_npa_pct:.2f}% (red > {nnpa_red}%)"))
                elif result.net_npa_pct > nnpa_green:
                    result.flags.append(ScreenFlag(FlagLevel.YELLOW, "AssetQuality", f"Elevated Net NPA: {result.net_npa_pct:.2f}% (green < {nnpa_green}%)"))
                else:
                    result.flags.append(ScreenFlag(FlagLevel.GREEN, "AssetQuality", f"Well provisioned Net NPA: {result.net_npa_pct:.2f}%"))

        # OCF quality — not applicable for financial sector (lending = negative OCF by nature)
        if financial:
            result.flags.append(ScreenFlag(FlagLevel.GREEN, "CashQuality", "Financial sector — OCF/FCF checks not applicable (loan disbursements are operating cash outflows)"))
        elif lease_heavy and result.si_ocf_ebitda_ratio is not None:
            # Ind AS 116 sector: OCF/PAT is distorted by lease depreciation — use OCF/EBITDA
            r = result.si_ocf_ebitda_ratio
            if r >= 1.0:
                result.flags.append(ScreenFlag(FlagLevel.GREEN, "CashQuality", f"Strong cash conversion: OCF/EBITDA {r:.2f}x (Ind AS 116 sector — lease depreciation distorts PAT)"))
            elif r >= 0.7:
                result.flags.append(ScreenFlag(FlagLevel.GREEN, "CashQuality", f"Good cash conversion: OCF/EBITDA {r:.2f}x"))
            elif r >= 0:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "CashQuality", f"Weak cash conversion: OCF/EBITDA {r:.2f}x (min 0.7x)"))
            else:
                result.flags.append(ScreenFlag(FlagLevel.RED, "CashQuality", f"Negative OCF despite positive EBITDA: OCF/EBITDA {r:.2f}x"))
        else:
            if result.ocf_pat_ratio is not None:
                ocf_trend_check = result.si_ocf_trend or result.ocf_trend
                if result.ocf_pat_ratio < 0:
                    result.flags.append(ScreenFlag(FlagLevel.RED, "CashQuality", f"Negative OCF despite PAT: OCF/PAT = {result.ocf_pat_ratio:.2f}"))
                    if ocf_trend_check == "stable":
                        result.flags.append(ScreenFlag(FlagLevel.RED, "CashQuality", "Chronic negative OCF — has been negative for years, not a temporary dip"))
                elif result.ocf_pat_ratio < cfg_p["ocf_pat_ratio_min"]:
                    result.flags.append(ScreenFlag(FlagLevel.YELLOW, "CashQuality", f"Low OCF/PAT ratio: {result.ocf_pat_ratio:.2f} (min {cfg_p['ocf_pat_ratio_min']})"))
                else:
                    result.flags.append(ScreenFlag(FlagLevel.GREEN, "CashQuality", f"Strong OCF quality: {result.ocf_pat_ratio:.2f}x"))

            # PAT rising + OCF declining = earnings quality concern
            if result.pat_yoy_pct is not None and result.pat_yoy_pct > 10:
                ocf_trend_check = result.si_ocf_trend or result.ocf_trend
                if ocf_trend_check == "deteriorating":
                    result.flags.append(ScreenFlag(FlagLevel.RED, "CashQuality", "PAT rising but OCF declining — earnings quality concern"))

            # Negative FCF flag
            if result.si_fcf_annual is not None and result.si_fcf_annual < 0:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "CashQuality", f"Negative FCF: ₹{result.si_fcf_annual:,.0f} Cr — investing more than operating cash generated"))

    def _compute_score(self, result: BasicScreenResult, cfg_g: dict, cfg_p: dict, sector: Optional[str] = None, lease_heavy: bool = False) -> int:
        financial = _is_financial(sector)
        score = 50
        bd: dict = {"growth": 0, "profitability": 0, "cash_quality": 0, "asset_quality": 0, "penalties": 0}
        _gd: list = []   # growth detail: [label, pts]
        _pd: list = []   # profitability detail
        _cd: list = []   # cash quality detail
        _ad: list = []   # asset quality detail

        # Per-factor scale: YAML weight / built-in default. 0.0 when factor is disabled.
        _fcts = self.cfg.get("scoring", {}).get("factors", {})

        def _sf(name: str) -> float:
            f = _fcts.get(name, {})
            if not f.get("enabled", True):
                return 0.0
            dw = float(f["default_weight"])
            return float(f.get("weight", dw)) / dw

        def _growth_pts(pct5y, pct3y, threshold, factor_name):
            """Score growth using the worse of 3Y and 5Y averages.

            Exception: if both are available and the gap between them is large
            (> 40 pp), the two periods are telling very different stories (e.g.
            one bad loss year distorting the shorter window while the long-term
            trend is fine). In that case use the average so neither extreme
            dominates.
            """
            sf = _sf(factor_name)
            if not sf:
                return None
            candidates = [p for p in (pct5y, pct3y) if p is not None]
            if not candidates:
                return None
            if len(candidates) == 2 and abs(candidates[0] - candidates[1]) > 40:
                pct = sum(candidates) / 2  # average when gap is too wide
            else:
                pct = min(candidates)  # penalise if either period is bad
            raw = (15 if pct >= threshold * 2 else
                    8 if pct >= threshold else
                    2 if pct >= 0 else -15)
            return round(raw * sf)

        # Revenue growth (default max ±15)
        rev_pts = _growth_pts(result.revenue_yoy_pct, result.revenue_yoy_3y_pct, cfg_g["revenue_yoy_min_pct"], "revenue_growth")
        if rev_pts is not None:
            score += rev_pts
            bd["growth"] += rev_pts
            _rv = result.revenue_yoy_pct or result.revenue_yoy_3y_pct
            _gd.append([f"Rev {_rv:.1f}%" if _rv is not None else "Rev", rev_pts])

        # PAT growth (default max ±15)
        pat_pts = _growth_pts(result.pat_yoy_pct, result.pat_yoy_3y_pct, cfg_g["pat_yoy_min_pct"], "pat_growth")
        if pat_pts is not None:
            score += pat_pts
            bd["growth"] += pat_pts
            _pv = result.pat_yoy_pct or result.pat_yoy_3y_pct
            _gd.append([f"PAT {_pv:.1f}%" if _pv is not None else "PAT", pat_pts])

        # Chronic loss penalty: PAT QoQ suppressed because majority of recent quarters were losses
        # This fires only when pat_pts is not already penalising — a safety net for companies
        # that show positive multi-year YoY averages but have been loss-making recently.
        if result.pat_qoq_suppressed:
            chronic_pen = round(10 * _sf("pat_growth"))
            score -= chronic_pen
            bd["growth"] -= chronic_pen
            _gd.append(["Chronic loss pen.", -chronic_pen])

        # EBITDA margin (default max ±10) — not applicable for financial sector
        em_sf = _sf("ebitda_margin")
        if em_sf and not financial and result.ebitda_margin_qoq_pp is not None:
            _qoq_thr = cfg_p.get("ebitda_margin_qoq_expand_pp", 1.0)
            raw = (4 if result.ebitda_margin_qoq_pp >= _qoq_thr else
                   2 if result.ebitda_margin_qoq_pp >= 0 else
                  -2 if result.ebitda_margin_qoq_pp >= -_qoq_thr else -4)
            pts = round(raw * em_sf)
            score += pts
            bd["profitability"] += pts
            _pd.append([f"EBITDA QoQ {result.ebitda_margin_qoq_pp:+.2f}pp", pts])
        if em_sf and not financial and result.ebitda_margin_trend == "improving":
            pts = round(5 * em_sf)
            score += pts
            bd["profitability"] += pts
            _pd.append(["EBITDA trend ↑", pts])
        elif em_sf and not financial and result.ebitda_margin_trend == "deteriorating":
            pts = round(-10 * em_sf)
            score += pts
            bd["profitability"] += pts
            _pd.append(["EBITDA trend ↓", pts])

        # NPA scoring — financial sector only (replaces EBITDA margin)
        # Scored into bd["asset_quality"] to keep it separate from general profitability.
        npa_sf = _sf("npa_quality")
        if npa_sf and financial:
            cfg_fin = self.cfg["financial_sector"]
            gnpa_green = cfg_fin.get("gross_npa_green_pct", 3.0)
            gnpa_red   = cfg_fin.get("gross_npa_red_pct", 7.0)
            nnpa_green = cfg_fin.get("net_npa_green_pct", 1.0)
            nnpa_red   = cfg_fin.get("net_npa_red_pct", 3.0)

            if result.gross_npa_pct is not None:
                g = result.gross_npa_pct
                # Gradient: very clean → good → caution → elevated → red
                raw = (15 if g <= gnpa_green / 2 else
                       10 if g <= gnpa_green else
                       -5 if g <= (gnpa_green + gnpa_red) / 2 else
                      -10 if g <= gnpa_red else -15)
                pts = round(raw * npa_sf)
                score += pts
                bd["asset_quality"] += pts
                _ad.append([f"Gross NPA {g:.1f}%", pts])

            if result.net_npa_pct is not None:
                n = result.net_npa_pct
                raw = (10 if n <= nnpa_green / 2 else
                        5 if n <= nnpa_green else
                       -5 if n <= (nnpa_green + nnpa_red) / 2 else
                      -10 if n <= nnpa_red else -15)
                pts = round(raw * npa_sf)
                score += pts
                bd["asset_quality"] += pts
                _ad.append([f"Net NPA {n:.1f}%", pts])

            # 1Y trend bonus/penalty — improving NPA trend is a strong forward signal
            if result.gross_npa_1y_chg is not None:
                raw = (5 if result.gross_npa_1y_chg < -1.0 else
                       2 if result.gross_npa_1y_chg < 0 else
                      -5 if result.gross_npa_1y_chg > 1.0 else
                      -2 if result.gross_npa_1y_chg > 0 else 0)
                pts = round(raw * npa_sf)
                score += pts
                bd["asset_quality"] += pts
                if pts != 0:
                    _ad.append([f"NPA 1Y trend {result.gross_npa_1y_chg:+.1f}pp", pts])

        # OCF quality (default max ±15) — skipped for financial sector
        ocf_sf = _sf("ocf_quality")
        if ocf_sf and not financial:
            if lease_heavy and result.si_ocf_ebitda_ratio is not None:
                # Ind AS 116 sector: score OCF/EBITDA — PAT is distorted by lease depreciation
                r = result.si_ocf_ebitda_ratio
                raw = (15 if r >= 1.0 else 10 if r >= 0.85 else 5 if r >= 0.7 else -5 if r >= 0 else -15)
                pts = round(raw * ocf_sf)
                score += pts
                bd["cash_quality"] += pts
                _cd.append([f"OCF/EBITDA {r:.2f}", pts])
            elif result.ocf_pat_ratio is not None:
                raw = (10 if result.ocf_pat_ratio >= 1.0 else
                        5 if result.ocf_pat_ratio >= cfg_p["ocf_pat_ratio_min"] else
                       -5 if result.ocf_pat_ratio >= 0 else -15)
                pts = round(raw * ocf_sf)
                score += pts
                bd["cash_quality"] += pts
                _cd.append([f"OCF/PAT {result.ocf_pat_ratio:.2f}", pts])
                # Extra penalty for chronic negative OCF (not just a one-off dip)
                ocf_trend_check = result.si_ocf_trend or result.ocf_trend
                if result.ocf_pat_ratio < 0 and ocf_trend_check == "stable":
                    pen = round(5 * ocf_sf)
                    score -= pen
                    bd["cash_quality"] -= pen
                    _cd.append(["Chronic neg. OCF", -pen])

        # Red flag penalties — only for categories NOT already captured in numeric scoring above.
        # Growth (revenue/PAT) and CashQuality (OCF) and Margin are already scored numerically,
        # so we skip their red flags here to avoid double-counting.
        rfp_sf = _sf("red_flag_penalty")
        _ALREADY_SCORED = {"Growth", "Margin", "CashQuality", "AssetQuality"}
        red_flags = [f for f in result.flags if f.level == FlagLevel.RED and f.category not in _ALREADY_SCORED]
        penalty = round(len(red_flags) * 5 * rfp_sf)
        score -= penalty
        bd["penalties"] = -penalty
        bd["penalty_flags"] = [f.message for f in red_flags]

        bd["growth_detail"]       = _gd
        bd["profitability_detail"] = _pd
        bd["cash_quality_detail"] = _cd
        bd["asset_quality_detail"] = _ad

        result.score_breakdown = bd
        return max(0, min(100, score))
