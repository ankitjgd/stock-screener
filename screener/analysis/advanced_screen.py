"""Advanced screener: ROE, ROCE, debt health, promoter/FII activity, valuations."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from screener.analysis.basic_screen import FlagLevel, ScreenFlag


def _load_cfg() -> dict:
    return yaml.safe_load(
        (Path(__file__).parent.parent.parent / "config" / "thresholds.yaml").read_text()
    )


@dataclass
class AdvancedScreenResult:
    symbol: str
    # Profitability ratios
    roe_pct: Optional[float] = None
    roce_pct: Optional[float] = None
    # Debt health
    de_ratio: Optional[float] = None
    interest_coverage: Optional[float] = None
    net_debt_to_ebitda: Optional[float] = None
    # Valuation
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None
    # Shareholding
    promoter_holding_pct: Optional[float] = None
    promoter_pledge_pct: Optional[float] = None
    promoter_holding_delta: Optional[float] = None      # QoQ
    promoter_holding_6q_delta: Optional[float] = None  # 6-quarter change
    pledge_delta: Optional[float] = None
    pledge_6q_delta: Optional[float] = None
    fii_holding_pct: Optional[float] = None
    fii_holding_delta: Optional[float] = None           # QoQ
    fii_holding_6q_delta: Optional[float] = None       # 6-quarter change
    dii_holding_pct: Optional[float] = None
    dii_holding_delta: Optional[float] = None           # QoQ
    dii_holding_6q_delta: Optional[float] = None       # 6-quarter change
    public_holding_pct: Optional[float] = None
    public_holding_delta: Optional[float] = None        # QoQ
    public_holding_6q_delta: Optional[float] = None    # 6-quarter change
    # Working capital
    debtor_days: Optional[float] = None
    inventory_days: Optional[float] = None
    days_payable: Optional[float] = None
    cash_conversion_cycle: Optional[float] = None
    # FCF
    fcf_latest: Optional[float] = None
    fcf_trend: Optional[str] = None
    revenue_quality_score: Optional[float] = None  # 0-10
    # Historical PE — 1Y
    pe_mean_historical: Optional[float] = None
    pe_median_historical: Optional[float] = None
    pe_min_historical: Optional[float] = None
    pe_max_historical: Optional[float] = None
    pe_periods: Optional[int] = None
    # Historical PE — 5Y
    pe_mean_5y: Optional[float] = None
    pe_median_5y: Optional[float] = None
    pe_min_5y: Optional[float] = None
    pe_max_5y: Optional[float] = None
    pe_periods_5y: Optional[int] = None
    # Historical PE — 10Y
    pe_mean_10y: Optional[float] = None
    pe_median_10y: Optional[float] = None
    pe_min_10y: Optional[float] = None
    pe_max_10y: Optional[float] = None
    pe_periods_10y: Optional[int] = None
    # Flags
    flags: list[ScreenFlag] = field(default_factory=list)
    red_flag_count: int = 0
    score: int = 0


def _find_col(df: pd.DataFrame, keywords: list[str]) -> Optional[str]:
    for col in df.columns:
        col_lower = str(col).lower()
        if any(kw.lower() in col_lower for kw in keywords):
            return col
    return None


def _col_as_series(df: pd.DataFrame, col: str) -> pd.Series:
    """Return a numeric Series for col, safely handling duplicate column names."""
    result = df[col]
    if isinstance(result, pd.DataFrame):
        result = result.iloc[:, 0]
    return result.apply(pd.to_numeric, errors="coerce")


def _last_val(series: pd.Series) -> Optional[float]:
    s = series.apply(pd.to_numeric, errors="coerce").dropna()
    return float(s.iloc[-1]) if not s.empty else None


def _trend(series: pd.Series, window: int = 4) -> str:
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


def _consecutive_decline(series: pd.Series, n: int = 3) -> bool:
    """Returns True if last n values are consecutively declining."""
    try:
        s = series.apply(pd.to_numeric, errors="coerce").dropna().tail(n + 1)
        if len(s) < n + 1:
            return False
        diffs = s.diff().dropna().tail(n)
        return (diffs < 0).all()
    except Exception:
        return False


class AdvancedScreener:
    """Analyses debt, promoter/FII activity, valuations, working capital."""

    def __init__(self):
        self.cfg = _load_cfg()

    def screen(
        self,
        symbol: str,
        price_info: Optional[dict],
        balance_df: Optional[pd.DataFrame],
        income_df: Optional[pd.DataFrame],
        cashflow_df: Optional[pd.DataFrame],
        shareholding: Optional[dict],
        si_ratios: Optional[dict],
        historical_pe: Optional[dict] = None,
        si_wc_ratios: Optional[dict] = None,
    ) -> AdvancedScreenResult:
        result = AdvancedScreenResult(symbol=symbol)
        cfg_d = self.cfg["debt"]
        cfg_v = self.cfg["valuation"]
        cfg_s = self.cfg["shareholding"]

        self._fill_ratios(result, price_info, si_ratios)
        self._fill_debt(result, balance_df, income_df)
        self._fill_shareholding(result, shareholding)
        self._fill_working_capital(result, balance_df, income_df)
        self._fill_working_capital_from_si(result, si_wc_ratios)  # overrides with accurate data
        self._fill_fcf(result, cashflow_df)
        self._fill_historical_pe(result, historical_pe)
        self._apply_flags(result, cfg_d, cfg_v, cfg_s, income_df, cashflow_df)
        result.red_flag_count = sum(1 for f in result.flags if f.level == FlagLevel.RED)
        result.score = self._compute_score(result, cfg_d, cfg_v, cfg_s)
        return result

    def _fill_ratios(self, result: AdvancedScreenResult, price_info: Optional[dict], si_ratios: Optional[dict]) -> None:
        """Fill ratios from screener.in first, fall back to yfinance."""
        if si_ratios:
            result.roe_pct = si_ratios.get("roe")
            result.roce_pct = si_ratios.get("roce")
            result.pe_ratio = si_ratios.get("pe")
            result.pb_ratio = si_ratios.get("pb")
            result.de_ratio = si_ratios.get("de_ratio")

        # Fill gaps from price_info (yfinance)
        if price_info:
            if result.pe_ratio is None:
                result.pe_ratio = price_info.get("pe_ratio")
            if result.pb_ratio is None:
                result.pb_ratio = price_info.get("pb_ratio")

    def _fill_debt(
        self,
        result: AdvancedScreenResult,
        balance_df: Optional[pd.DataFrame],
        income_df: Optional[pd.DataFrame],
    ) -> None:
        if balance_df is None or balance_df.empty:
            return

        debt_col = _find_col(balance_df, ["Total_Debt", "Total Debt", "Borrowings"])
        equity_col = _find_col(balance_df, ["Equity", "Stockholders Equity", "Net Worth"])
        cash_col = _find_col(balance_df, ["Cash"])

        total_debt = _last_val(_col_as_series(balance_df, debt_col)) if debt_col else None
        equity = _last_val(_col_as_series(balance_df, equity_col)) if equity_col else None
        cash = _last_val(_col_as_series(balance_df, cash_col)) if cash_col else None

        if total_debt is not None and equity is not None and equity != 0:
            if result.de_ratio is None:
                result.de_ratio = round(total_debt / equity, 2)

        # Net debt to EBITDA
        if income_df is not None and not income_df.empty:
            ebitda_col = _find_col(income_df, ["EBITDA"])
            interest_col = _find_col(income_df, ["Interest_Expense", "Interest Expense"])

            if ebitda_col:
                ebitda = _col_as_series(income_df, ebitda_col)
                # Annualize (sum last 4 quarters)
                annual_ebitda = ebitda.dropna().tail(4).sum()
                if total_debt is not None and cash is not None and annual_ebitda != 0:
                    net_debt = total_debt - cash
                    result.net_debt_to_ebitda = round(net_debt / annual_ebitda, 2)

            if interest_col and ebitda_col:
                interest = _col_as_series(income_df, interest_col)
                ebitda_series = _col_as_series(income_df, ebitda_col)
                last_interest = _last_val(interest)
                last_ebitda = _last_val(ebitda_series)
                if last_interest and last_ebitda and last_interest != 0:
                    result.interest_coverage = round(abs(last_ebitda / last_interest), 2)

    def _fill_shareholding(self, result: AdvancedScreenResult, shareholding: Optional[dict]) -> None:
        if not shareholding:
            return
        result.promoter_holding_pct = shareholding.get("promoter_pct")
        result.promoter_holding_delta = shareholding.get("promoter_delta")
        result.promoter_holding_6q_delta = shareholding.get("promoter_6q_delta")
        result.promoter_pledge_pct = shareholding.get("promoter_pledge_pct")
        result.pledge_delta = shareholding.get("pledge_delta")
        result.pledge_6q_delta = shareholding.get("pledge_6q_delta")
        result.fii_holding_pct = shareholding.get("fii_pct")
        result.fii_holding_delta = shareholding.get("fii_delta")
        result.fii_holding_6q_delta = shareholding.get("fii_6q_delta")
        result.dii_holding_pct = shareholding.get("dii_pct")
        result.dii_holding_delta = shareholding.get("dii_delta")
        result.dii_holding_6q_delta = shareholding.get("dii_6q_delta")
        result.public_holding_pct = shareholding.get("public_pct")
        result.public_holding_delta = shareholding.get("public_delta")
        result.public_holding_6q_delta = shareholding.get("public_6q_delta")

    def _fill_working_capital(
        self,
        result: AdvancedScreenResult,
        balance_df: Optional[pd.DataFrame],
        income_df: Optional[pd.DataFrame],
    ) -> None:
        if balance_df is None or income_df is None:
            return

        # Balance sheet columns
        # Prefer "Net Receivables" / "Accounts Receivable" over "Other Receivables"
        receivables_col = (
            _find_col(balance_df, ["Net Receivable", "Trade Receivable"])
            or _find_col(balance_df, ["Accounts Receivable"])
            or _find_col(balance_df, ["Receivable"])
        )
        inventory_col = _find_col(balance_df, ["Inventory"])
        payables_col = _find_col(balance_df, ["Accounts Payable", "Payable"])

        # Income statement columns
        rev_col = _find_col(income_df, ["Revenue", "Sales", "Total Revenue"])
        # COGS for inventory/payable days (more accurate than revenue)
        cogs_col = _find_col(income_df, ["Cost Of Revenue", "Cost of Goods", "COGS", "Cost_Of_Revenue"])

        if not rev_col:
            return

        revenue = _col_as_series(income_df, rev_col).dropna()
        annual_rev = revenue.tail(4).sum() if len(revenue) >= 4 else revenue.sum()
        if annual_rev <= 0:
            return

        # Annualised COGS (fall back to revenue if unavailable)
        annual_cogs = annual_rev
        if cogs_col:
            cogs = _col_as_series(income_df, cogs_col).dropna()
            c = cogs.tail(4).sum() if len(cogs) >= 4 else cogs.sum()
            if c > 0:
                annual_cogs = c

        # Debtor Days = (Trade Receivables / Revenue) × 365
        if receivables_col:
            receivables = _last_val(_col_as_series(balance_df, receivables_col))
            if receivables is not None and receivables > 0:
                result.debtor_days = round((receivables / annual_rev) * 365, 1)

        # Inventory Days = (Inventory / COGS) × 365
        if inventory_col:
            inventory = _last_val(_col_as_series(balance_df, inventory_col))
            if inventory is not None and inventory > 0:
                result.inventory_days = round((inventory / annual_cogs) * 365, 1)

        # Days Payable = (Accounts Payable / COGS) × 365
        if payables_col:
            payables = _last_val(_col_as_series(balance_df, payables_col))
            if payables is not None and payables > 0:
                result.days_payable = round((payables / annual_cogs) * 365, 1)

        # CCC = Debtor Days + Inventory Days − Days Payable
        if result.debtor_days is not None and result.inventory_days is not None:
            dp = result.days_payable or 0
            result.cash_conversion_cycle = round(result.debtor_days + result.inventory_days - dp, 1)

    def _fill_working_capital_from_si(
        self, result: AdvancedScreenResult, si_wc: Optional[dict]
    ) -> None:
        """Override working capital fields with screener.in annual Ratios data (authoritative)."""
        if not si_wc:
            return
        if si_wc.get("debtor_days") is not None:
            result.debtor_days = si_wc["debtor_days"]
        if si_wc.get("inventory_days") is not None:
            result.inventory_days = si_wc["inventory_days"]
        if si_wc.get("days_payable") is not None:
            result.days_payable = si_wc["days_payable"]
        if si_wc.get("ccc") is not None:
            result.cash_conversion_cycle = si_wc["ccc"]

    def _fill_fcf(self, result: AdvancedScreenResult, cashflow_df: Optional[pd.DataFrame]) -> None:
        if cashflow_df is None or cashflow_df.empty:
            return
        fcf_col = _find_col(cashflow_df, ["FCF", "Free Cash Flow"])
        if fcf_col:
            fcf = _col_as_series(cashflow_df, fcf_col)
            result.fcf_latest = _last_val(fcf)
            result.fcf_trend = _trend(fcf, window=6)

    def _fill_historical_pe(self, result: AdvancedScreenResult, historical_pe: Optional[dict]) -> None:
        if not historical_pe:
            return
        result.pe_mean_historical = historical_pe.get("mean_pe")
        result.pe_median_historical = historical_pe.get("median_pe")
        result.pe_min_historical = historical_pe.get("min_pe")
        result.pe_max_historical = historical_pe.get("max_pe")
        result.pe_periods = historical_pe.get("periods")
        result.pe_mean_5y = historical_pe.get("mean_pe_5y")
        result.pe_median_5y = historical_pe.get("median_pe_5y")
        result.pe_min_5y = historical_pe.get("min_pe_5y")
        result.pe_max_5y = historical_pe.get("max_pe_5y")
        result.pe_periods_5y = historical_pe.get("periods_5y")
        result.pe_mean_10y = historical_pe.get("mean_pe_10y")
        result.pe_median_10y = historical_pe.get("median_pe_10y")
        result.pe_min_10y = historical_pe.get("min_pe_10y")
        result.pe_max_10y = historical_pe.get("max_pe_10y")
        result.pe_periods_10y = historical_pe.get("periods_10y")

    def _apply_flags(
        self,
        result: AdvancedScreenResult,
        cfg_d: dict,
        cfg_v: dict,
        cfg_s: dict,
        income_df: Optional[pd.DataFrame],
        cashflow_df: Optional[pd.DataFrame],
    ) -> None:
        # --- Debt flags ---
        if result.de_ratio is not None:
            if result.de_ratio > cfg_d["de_ratio_red"]:
                result.flags.append(ScreenFlag(FlagLevel.RED, "Debt", f"Very high D/E ratio: {result.de_ratio:.2f}x (alert > {cfg_d['de_ratio_red']}x)"))
            elif result.de_ratio > cfg_d["de_ratio_max"]:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Debt", f"Elevated D/E ratio: {result.de_ratio:.2f}x (max {cfg_d['de_ratio_max']}x)"))
            else:
                result.flags.append(ScreenFlag(FlagLevel.GREEN, "Debt", f"Healthy D/E ratio: {result.de_ratio:.2f}x"))

        if result.interest_coverage is not None:
            if result.interest_coverage < cfg_d["interest_coverage_red"]:
                result.flags.append(ScreenFlag(FlagLevel.RED, "Debt", f"Critical interest coverage: {result.interest_coverage:.2f}x (min {cfg_d['interest_coverage_red']}x)"))
            elif result.interest_coverage < cfg_d["interest_coverage_min"]:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Debt", f"Low interest coverage: {result.interest_coverage:.2f}x (min {cfg_d['interest_coverage_min']}x)"))
            else:
                result.flags.append(ScreenFlag(FlagLevel.GREEN, "Debt", f"Good interest coverage: {result.interest_coverage:.2f}x"))

        if result.net_debt_to_ebitda is not None and result.net_debt_to_ebitda > cfg_d["net_debt_ebitda_max"]:
            result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Debt", f"High Net Debt/EBITDA: {result.net_debt_to_ebitda:.2f}x (max {cfg_d['net_debt_ebitda_max']}x)"))

        # --- ROE/ROCE flags ---
        cfg_prof = self.cfg["profitability"]
        if result.roe_pct is not None:
            if result.roe_pct < cfg_prof["roe_min_pct"]:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Profitability", f"Low ROE: {result.roe_pct:.1f}% (min {cfg_prof['roe_min_pct']}%)"))
            else:
                result.flags.append(ScreenFlag(FlagLevel.GREEN, "Profitability", f"Strong ROE: {result.roe_pct:.1f}%"))

        if result.roce_pct is not None:
            if result.roce_pct < cfg_prof["roce_min_pct"]:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Profitability", f"Low ROCE: {result.roce_pct:.1f}% (min {cfg_prof['roce_min_pct']}%)"))
            else:
                result.flags.append(ScreenFlag(FlagLevel.GREEN, "Profitability", f"Strong ROCE: {result.roce_pct:.1f}%"))

        # --- Promoter flags ---
        if result.promoter_pledge_pct is not None:
            if result.promoter_pledge_pct > cfg_s["promoter_pledge_red_pct"]:
                result.flags.append(ScreenFlag(FlagLevel.RED, "Promoter", f"Very high promoter pledge: {result.promoter_pledge_pct:.1f}% (alert > {cfg_s['promoter_pledge_red_pct']}%)"))
            elif result.promoter_pledge_pct > cfg_s["promoter_pledge_max_pct"]:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Promoter", f"Elevated promoter pledge: {result.promoter_pledge_pct:.1f}%"))

        if result.pledge_delta is not None and result.pledge_delta > cfg_s["promoter_pledge_increase_alert"]:
            result.flags.append(ScreenFlag(FlagLevel.RED, "Promoter", f"Promoter pledge increased QoQ: +{result.pledge_delta:.1f}%"))

        if result.promoter_holding_delta is not None:
            if result.promoter_holding_delta < -cfg_s["promoter_holding_decrease_alert"]:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Promoter", f"Promoter reducing stake: {result.promoter_holding_delta:.1f}% QoQ"))
            elif result.promoter_holding_delta > 0:
                result.flags.append(ScreenFlag(FlagLevel.GREEN, "Promoter", f"Promoter increasing stake: +{result.promoter_holding_delta:.1f}% QoQ"))

        # FII activity
        if result.fii_holding_delta is not None:
            if result.fii_holding_delta >= cfg_s["fii_increase_min_pct"]:
                result.flags.append(ScreenFlag(FlagLevel.GREEN, "Institutional", f"FII buying: +{result.fii_holding_delta:.1f}% QoQ"))
            elif result.fii_holding_delta <= -cfg_s["fii_increase_min_pct"]:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Institutional", f"FII selling: {result.fii_holding_delta:.1f}% QoQ"))

        # --- Valuation flags ---
        if result.pe_ratio is not None:
            if result.pe_ratio > cfg_v["pe_red"]:
                result.flags.append(ScreenFlag(FlagLevel.RED, "Valuation", f"Extremely high P/E: {result.pe_ratio:.1f}x (alert > {cfg_v['pe_red']}x)"))
            elif result.pe_ratio > cfg_v["pe_max"]:
                result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Valuation", f"High P/E: {result.pe_ratio:.1f}x (max {cfg_v['pe_max']}x)"))
            elif result.pe_ratio > 0:
                result.flags.append(ScreenFlag(FlagLevel.GREEN, "Valuation", f"Reasonable P/E: {result.pe_ratio:.1f}x"))

        if result.pb_ratio is not None and result.pb_ratio > cfg_v["pb_max"]:
            result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Valuation", f"High P/B: {result.pb_ratio:.1f}x (max {cfg_v['pb_max']}x)"))

        if result.ev_ebitda is not None and result.ev_ebitda > cfg_v["ev_ebitda_max"]:
            result.flags.append(ScreenFlag(FlagLevel.YELLOW, "Valuation", f"High EV/EBITDA: {result.ev_ebitda:.1f}x (max {cfg_v['ev_ebitda_max']}x)"))

        # --- P/E vs historical mean ---
        if result.pe_ratio and result.pe_ratio > 0 and result.pe_mean_historical:
            ratio = result.pe_ratio / result.pe_mean_historical
            label = "1yr"
            if ratio > 1.5:
                result.flags.append(ScreenFlag(
                    FlagLevel.YELLOW, "Valuation",
                    f"P/E {result.pe_ratio:.1f}x is {ratio:.1f}x above {label} mean {result.pe_mean_historical:.1f}x — expensive vs history",
                ))
            elif ratio < 0.75:
                result.flags.append(ScreenFlag(
                    FlagLevel.GREEN, "Valuation",
                    f"P/E {result.pe_ratio:.1f}x is below {label} mean {result.pe_mean_historical:.1f}x — cheap vs history",
                ))

        # --- FCF flags ---
        if result.fcf_latest is not None and result.fcf_latest < 0:
            result.flags.append(ScreenFlag(FlagLevel.YELLOW, "CashFlow", "Negative FCF in latest quarter"))
        if result.fcf_trend == "deteriorating":
            result.flags.append(ScreenFlag(FlagLevel.YELLOW, "CashFlow", "FCF trend deteriorating"))
        elif result.fcf_trend == "improving":
            result.flags.append(ScreenFlag(FlagLevel.GREEN, "CashFlow", "FCF trend improving"))

        # --- OCF declining 3+ quarters while PAT rising (checked from income+cashflow) ---
        if income_df is not None and cashflow_df is not None:
            ocf_col = _find_col(cashflow_df, ["OCF", "Operating Cash Flow"])
            pat_col = _find_col(income_df, ["Net_Income", "Net Income"])
            if ocf_col and pat_col:
                ocf = _col_as_series(cashflow_df, ocf_col)
                pat = _col_as_series(income_df, pat_col)
                if _consecutive_decline(ocf, 3):
                    last_pat_change = pat.diff().dropna().tail(3)
                    if (last_pat_change > 0).sum() >= 2:
                        result.flags.append(ScreenFlag(FlagLevel.RED, "CashQuality", "OCF declining 3+ quarters while PAT rising — earnings quality RED FLAG"))

        # --- Working capital deterioration ---
        cfg_wc = self.cfg["working_capital"]
        if result.debtor_days is not None and result.debtor_days > cfg_wc["debtor_days_max"]:
            result.flags.append(ScreenFlag(FlagLevel.YELLOW, "WorkingCapital", f"High debtor days: {result.debtor_days:.0f} (max {cfg_wc['debtor_days_max']})"))
        if result.inventory_days is not None and result.inventory_days > cfg_wc["inventory_days_max"]:
            result.flags.append(ScreenFlag(FlagLevel.YELLOW, "WorkingCapital", f"High inventory days: {result.inventory_days:.0f} (max {cfg_wc['inventory_days_max']})"))

    def _compute_score(
        self,
        result: AdvancedScreenResult,
        cfg_d: dict,
        cfg_v: dict,
        cfg_s: dict,
    ) -> int:
        cfg_prof = self.cfg["profitability"]
        score = 50

        # ROE (max ±10)
        if result.roe_pct is not None:
            if result.roe_pct >= cfg_prof["roe_min_pct"] * 2:
                score += 10
            elif result.roe_pct >= cfg_prof["roe_min_pct"]:
                score += 5
            else:
                score -= 5

        # ROCE (max ±8)
        if result.roce_pct is not None:
            if result.roce_pct >= cfg_prof["roce_min_pct"] * 2:
                score += 8
            elif result.roce_pct >= cfg_prof["roce_min_pct"]:
                score += 4
            else:
                score -= 4

        # Debt health (max ±12)
        if result.de_ratio is not None:
            if result.de_ratio < 0.5:
                score += 12
            elif result.de_ratio < cfg_d["de_ratio_max"]:
                score += 6
            elif result.de_ratio < cfg_d["de_ratio_red"]:
                score -= 6
            else:
                score -= 12

        if result.interest_coverage is not None:
            if result.interest_coverage >= cfg_d["interest_coverage_min"] * 2:
                score += 6
            elif result.interest_coverage >= cfg_d["interest_coverage_min"]:
                score += 3
            else:
                score -= 6

        # Promoter activity (max ±10)
        if result.promoter_pledge_pct is not None:
            if result.promoter_pledge_pct == 0:
                score += 5
            elif result.promoter_pledge_pct <= cfg_s["promoter_pledge_max_pct"]:
                score += 2
            elif result.promoter_pledge_pct <= cfg_s["promoter_pledge_red_pct"]:
                score -= 5
            else:
                score -= 10
        if result.pledge_delta and result.pledge_delta > cfg_s["promoter_pledge_increase_alert"]:
            score -= 10

        # Valuation (max ±10)
        if result.pe_ratio is not None and result.pe_ratio > 0:
            if result.pe_ratio < 15:
                score += 10
            elif result.pe_ratio < cfg_v["pe_max"]:
                score += 5
            elif result.pe_ratio < cfg_v["pe_red"]:
                score -= 5
            else:
                score -= 10

        # FCF
        if result.fcf_latest is not None:
            if result.fcf_latest > 0:
                score += 5
            else:
                score -= 5

        # Red flag penalty
        score -= result.red_flag_count * self.cfg["scoring"]["weights"]["red_flag_penalty"] * -1

        return max(0, min(100, score))
