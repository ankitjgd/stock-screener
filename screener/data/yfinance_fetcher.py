"""yfinance-based data fetcher with CSV cache."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
import yaml


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent.parent / "config" / "thresholds.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


class CacheManager:
    """CSV-based cache with TTL."""

    def __init__(self, cache_dir: Optional[str] = None, ttl_hours: Optional[int] = None):
        cfg = _load_config()
        self.cache_dir = Path(cache_dir or cfg["cache"]["dir"])
        self.ttl_hours = ttl_hours or cfg["cache"]["ttl_hours"]
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, symbol: str, data_type: str) -> Path:
        safe = symbol.replace(".", "_").upper()
        return self.cache_dir / f"{safe}_{data_type}.csv"

    def is_fresh(self, symbol: str, data_type: str) -> bool:
        path = self._cache_path(symbol, data_type)
        if not path.exists():
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return datetime.now() - mtime < timedelta(hours=self.ttl_hours)

    def read(self, symbol: str, data_type: str) -> Optional[pd.DataFrame]:
        if not self.is_fresh(symbol, data_type):
            return None
        path = self._cache_path(symbol, data_type)
        try:
            return pd.read_csv(path, index_col=0)
        except Exception:
            return None

    def write(self, symbol: str, data_type: str, df: pd.DataFrame) -> None:
        path = self._cache_path(symbol, data_type)
        try:
            df.to_csv(path)
        except Exception:
            pass

    def clear(self, symbol: Optional[str] = None) -> int:
        """Clear cache. If symbol given, clear only that symbol. Returns count deleted."""
        count = 0
        for f in self.cache_dir.glob("*.csv"):
            if symbol is None or f.name.startswith(symbol.replace(".", "_").upper()):
                f.unlink()
                count += 1
        return count


class YFinanceFetcher:
    """Fetches financial data via yfinance with caching."""

    def __init__(self, cache: Optional[CacheManager] = None):
        self.cache = cache or CacheManager()

    def _ticker(self, symbol: str) -> yf.Ticker:
        return yf.Ticker(symbol)

    def get_price_info(self, symbol: str) -> Optional[dict]:
        """Returns price, marketCap, P/E, P/B, EPS from ticker info.
        Always fetched fresh — current_price must reflect live market value."""
        try:
            info = self._ticker(symbol).info
            data = {
                "symbol": symbol,
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
                "pb_ratio": info.get("priceToBook"),
                "eps_ttm": info.get("trailingEps"),
                "dividend_yield": info.get("dividendYield"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "company_name": info.get("longName") or info.get("shortName"),
            }
            df = pd.DataFrame([data]).set_index("symbol")
            self.cache.write(symbol, "price_info", df)
            return data
        except Exception:
            return None

    def get_historical_pe_stats(self, symbol: str) -> Optional[dict]:
        """
        Compute mean TTM P/E over 1Y, 5Y, and 10Y windows.
        - Quarterly TTM EPS (rolling 4Q sum) used for recent data (~5Y).
        - Annual EPS used to extend coverage to 10Y for older periods.
        - Both forward-filled onto monthly price history.
        Returns flat dict with mean/median/min/max for each window.
        """
        cached = self.cache.read(symbol, "historical_pe")
        if cached is not None:
            d = cached.to_dict(orient="index")
            result = list(d.values())[0] if d else None
            # Invalidate old cache format (missing 5Y/10Y fields)
            if result is not None and "mean_pe_5y" not in result:
                self.cache._cache_path(symbol, "historical_pe").unlink(missing_ok=True)
                result = None
            if result is not None:
                return result

        def _norm_idx(series: pd.Series) -> pd.Series:
            series.index = pd.to_datetime([
                pd.Timestamp(d).tz_localize(None) if getattr(d, "tzinfo", None) else pd.Timestamp(d)
                for d in series.index
            ])
            return series

        def _find_eps_col(df: pd.DataFrame) -> Optional[str]:
            for col in df.columns:
                cl = str(col).lower()
                if "basic eps" in cl or "diluted eps" in cl or cl == "eps":
                    return col
            return None

        try:
            ticker = self._ticker(symbol)

            # ── Quarterly TTM EPS (last ~5 years) ────────────────────────
            ttm_quarterly = None
            inc_q = ticker.quarterly_income_stmt
            if inc_q is not None and not inc_q.empty:
                inc_q = inc_q.T
                inc_q.index = pd.to_datetime(inc_q.index)
                inc_q = inc_q.sort_index()
                eps_col = _find_eps_col(inc_q)
                if eps_col:
                    eps_q = inc_q[eps_col].apply(pd.to_numeric, errors="coerce").dropna()
                    if len(eps_q) >= 4:
                        ttm_quarterly = _norm_idx(eps_q.rolling(4).sum().dropna())

            # ── Annual EPS (extends coverage to ~10 years) ────────────────
            ttm_annual = None
            inc_a = ticker.income_stmt
            if inc_a is not None and not inc_a.empty:
                inc_a = inc_a.T
                inc_a.index = pd.to_datetime(inc_a.index)
                inc_a = inc_a.sort_index()
                eps_col_a = _find_eps_col(inc_a)
                if eps_col_a:
                    ttm_annual = _norm_idx(
                        inc_a[eps_col_a].apply(pd.to_numeric, errors="coerce").dropna()
                    )

            if ttm_quarterly is None and ttm_annual is None:
                return None

            # Combine: quarterly where available, annual for older period
            if ttm_quarterly is not None and ttm_annual is not None:
                q_start = ttm_quarterly.index[0]
                annual_old = ttm_annual[ttm_annual.index < q_start]
                ttm_combined = pd.concat([annual_old, ttm_quarterly]).sort_index()
                ttm_combined = ttm_combined[~ttm_combined.index.duplicated(keep="last")]
            elif ttm_quarterly is not None:
                ttm_combined = ttm_quarterly
            else:
                ttm_combined = ttm_annual

            if (ttm_combined <= 0).all():
                return None

            # ── Monthly price history (max available) ─────────────────────
            hist = ticker.history(period="max", interval="1mo")
            if hist is None or hist.empty:
                return None
            hist.index = hist.index.tz_localize(None) if hist.index.tzinfo else hist.index
            hist = hist.sort_index()

            # Forward-fill TTM EPS onto monthly price dates
            combined_idx = ttm_combined.index.union(hist.index).sort_values()
            ttm_filled = ttm_combined.reindex(combined_idx).ffill()
            ttm_at_month = ttm_filled.reindex(hist.index)

            monthly_pe = (hist["Close"] / ttm_at_month).replace(
                [float("inf"), -float("inf")], float("nan")
            ).dropna()
            monthly_pe = monthly_pe[(monthly_pe > 1) & (monthly_pe < 1000)]

            if monthly_pe.empty:
                return None

            last_date = monthly_pe.index[-1]

            def _window(months: int, min_months: int) -> Optional[dict]:
                cutoff = last_date - pd.DateOffset(months=months)
                w = monthly_pe[monthly_pe.index > cutoff]
                if len(w) < min_months:
                    return None
                vals = w.tolist()
                vs = sorted(vals)
                return {
                    "mean":   round(sum(vals) / len(vals), 1),
                    "median": round(vs[len(vs) // 2], 1),
                    "min":    round(vs[0], 1),
                    "max":    round(vs[-1], 1),
                    "months": len(vals),
                }

            s1y  = _window(12, 4)
            s5y  = _window(60, 24)
            s10y = _window(120, 48)

            if s1y is None:
                return None

            result = {
                # 1Y — flat keys (backward compat)
                "mean_pe":   s1y["mean"],
                "median_pe": s1y["median"],
                "min_pe":    s1y["min"],
                "max_pe":    s1y["max"],
                "current_pe": round(float(monthly_pe.iloc[-1]), 1),
                "periods":   s1y["months"],
            }
            if s5y:
                result.update({
                    "mean_pe_5y":   s5y["mean"],
                    "median_pe_5y": s5y["median"],
                    "min_pe_5y":    s5y["min"],
                    "max_pe_5y":    s5y["max"],
                    "periods_5y":   s5y["months"],
                })
            if s10y:
                result.update({
                    "mean_pe_10y":   s10y["mean"],
                    "median_pe_10y": s10y["median"],
                    "min_pe_10y":    s10y["min"],
                    "max_pe_10y":    s10y["max"],
                    "periods_10y":   s10y["months"],
                })

            self.cache.write(symbol, "historical_pe", pd.DataFrame([result]))
            return result
        except Exception:
            return None

    def get_price_trend(self, symbol: str) -> Optional[dict]:
        """
        6-month price trend for sparkline + key stats.
        Fetches 1Y daily data → weekly resample for sparkline, full daily for MAs.
        """
        cached = self.cache.read(symbol, "price_trend")
        if cached is not None:
            d = cached.to_dict(orient="index")
            result = list(d.values())[0] if d else None
            # Invalidate stale cache that predates the 1Y fields
            if result is not None and result.get("change_1y_pct") is None:
                self.cache._cache_path(symbol, "price_trend").unlink(missing_ok=True)
                result = None
            if result is not None:
                return result

        _SPARK = "▁▂▃▄▅▆▇█"

        def _sparkline(values: list) -> str:
            if not values or len(values) < 2:
                return ""
            mn, mx = min(values), max(values)
            if mn == mx:
                return _SPARK[3] * len(values)
            n = len(_SPARK) - 1
            return "".join(_SPARK[round((v - mn) / (mx - mn) * n)] for v in values)

        try:
            ticker = self._ticker(symbol)

            # 1Y daily — enough for 200D MA and 6M sparkline
            hist = ticker.history(period="1y", interval="1d")
            if hist is None or hist.empty:
                return None

            hist.index = hist.index.tz_localize(None) if hist.index.tzinfo else hist.index
            daily_close = hist["Close"].dropna()

            if len(daily_close) < 10:
                return None

            # 6M window
            cutoff_6m = daily_close.index[-1] - pd.DateOffset(months=6)
            close_6m = daily_close[daily_close.index >= cutoff_6m]

            # Weekly resample for sparkline (last ~26 data points)
            weekly = close_6m.resample("W").last().dropna()
            spark = _sparkline(weekly.tolist())

            current = float(daily_close.iloc[-1])
            start_6m = float(close_6m.iloc[0]) if not close_6m.empty else current
            change_6m_pct = round((current - start_6m) / start_6m * 100, 2) if start_6m else None

            high_6m = float(close_6m.max())
            low_6m = float(close_6m.min())
            pct_from_high = round((current - high_6m) / high_6m * 100, 2)

            ma50 = round(float(daily_close.tail(50).mean()), 2) if len(daily_close) >= 50 else None
            ma200 = round(float(daily_close.tail(200).mean()), 2) if len(daily_close) >= 200 else None

            date_start_6m = str(close_6m.index[0].date()) if not close_6m.empty else ""
            date_end = str(daily_close.index[-1].date()) if not daily_close.empty else ""

            # 1Y stats (full 1Y window)
            start_1y = float(daily_close.iloc[0])
            change_1y_pct = round((current - start_1y) / start_1y * 100, 2) if start_1y else None
            high_1y = float(daily_close.max())
            low_1y = float(daily_close.min())
            pct_from_high_1y = round((current - high_1y) / high_1y * 100, 2)
            monthly = daily_close.resample("ME").last().dropna()
            spark_1y = _sparkline(monthly.tolist())
            date_start_1y = str(daily_close.index[0].date()) if not daily_close.empty else ""

            result = {
                # 6M
                "sparkline": spark,
                "date_start": date_start_6m,
                "date_end": date_end,
                "current": round(current, 2),
                "change_6m_pct": change_6m_pct,
                "high_6m": round(high_6m, 2),
                "low_6m": round(low_6m, 2),
                "pct_from_high": pct_from_high,
                # 1Y
                "sparkline_1y": spark_1y,
                "date_start_1y": date_start_1y,
                "change_1y_pct": change_1y_pct,
                "high_1y": round(high_1y, 2),
                "low_1y": round(low_1y, 2),
                "pct_from_high_1y": pct_from_high_1y,
                # MAs
                "ma50": ma50,
                "ma200": ma200,
            }
            self.cache.write(symbol, "price_trend", pd.DataFrame([result]))
            return result
        except Exception:
            return None

    def fetch_all(self, symbol: str) -> dict:
        """Fetch price-only data for a symbol. All financial statements come from screener.in."""
        return {
            "symbol": symbol,
            "price_info": self.get_price_info(symbol),
            "historical_pe": self.get_historical_pe_stats(symbol),
            "price_trend": self.get_price_trend(symbol),
        }
