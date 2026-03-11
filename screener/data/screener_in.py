"""Scraper for screener.in — shareholding, pledge, ratios."""
from __future__ import annotations

import random
import re
import time
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag

from screener.data.yfinance_fetcher import CacheManager

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

_BASE_URLS = [
    "https://www.screener.in/company/{symbol}/consolidated/",
    "https://www.screener.in/company/{symbol}/",
]


class ScreenerInFetcher:
    """Fetches data from screener.in.

    One HTTP request per symbol per session — the page is cached in memory
    so all sections (P&L, balance, cash flow, shareholding, ratios) are
    parsed from the same soup object.
    """

    def __init__(self, cache: Optional[CacheManager] = None):
        self.cache = cache or CacheManager()
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        # In-memory page cache: symbol → BeautifulSoup
        self._page_cache: dict[str, BeautifulSoup] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """RELIANCE.NS → RELIANCE"""
        return symbol.upper().split(".")[0]

    @staticmethod
    def _page_has_data(soup: BeautifulSoup) -> bool:
        """Return True if the page has financial sections AND the quarters table has actual data columns."""
        has_section = False
        for sid in ("quarters", "profit-loss", "balance-sheet"):
            if soup.find("section", {"id": sid}):
                has_section = True
                break
        if not has_section:
            return False
        # Also verify the quarters table has more than just a label column (consolidated
        # pages for some companies return a valid-looking page but with no value columns)
        q_section = soup.find("section", {"id": "quarters"})
        if q_section:
            table = q_section.find("table")
            if table:
                first_tr = table.find("tr")
                if first_tr:
                    cols = first_tr.find_all(["th", "td"])
                    if len(cols) < 2:
                        return False
        return True

    @staticmethod
    def _page_has_recent_quarterly_data(soup: BeautifulSoup, max_lag_months: int = 6) -> bool:
        """Return True if the quarters section has data within the last max_lag_months months.

        Some consolidated pages lag standalone by several quarters (e.g. UCOBANK consolidated
        only has Mar 2025 while standalone has Dec 2025). Rejecting stale consolidated pages
        forces fallback to standalone which has the latest data.
        """
        import datetime
        q_section = soup.find("section", {"id": "quarters"})
        if not q_section:
            return True  # can't tell — don't reject
        table = q_section.find("table")
        if not table:
            return True
        first_tr = table.find("tr")
        if not first_tr:
            return True
        _month_map = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                      "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
        _qre = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})$")
        latest = None
        for cell in first_tr.find_all(["td", "th"]):
            m = _qre.match(cell.get_text(strip=True))
            if m:
                d = datetime.date(int(m.group(2)), _month_map[m.group(1)], 1)
                if latest is None or d > latest:
                    latest = d
        if latest is None:
            return True
        cutoff = datetime.date.today() - datetime.timedelta(days=max_lag_months * 30)
        return latest >= cutoff

    @staticmethod
    def _page_has_recent_annual_data(soup: BeautifulSoup, min_recent: int = 2, window: int = 5) -> bool:
        """Return True if the profit-loss table has at least `min_recent` column years within
        the last `window` years. This guards against consolidated pages that have a recent year
        but are missing intermediate years (e.g. Mar 2019 → Mar 2025 gap), making 3Y/5Y YoY
        averages unreliable — in such cases we fall back to standalone.
        """
        import datetime
        cutoff = datetime.date.today().year - window
        pl_section = soup.find("section", {"id": "profit-loss"})
        if not pl_section:
            return True  # can't tell — don't reject
        table = pl_section.find("table")
        if not table:
            return True
        first_tr = table.find("tr")
        if not first_tr:
            return True
        _year_re = re.compile(r"\b(\d{4})\b")
        recent_count = 0
        for cell in first_tr.find_all(["th", "td"]):
            m = _year_re.search(cell.get_text())
            if m and int(m.group(1)) > cutoff:
                recent_count += 1
        return recent_count >= min_recent

    def _fetch_page(self, symbol: str) -> Optional[BeautifulSoup]:
        """Fetch screener.in page — tries consolidated first, falls back to standalone.

        Acceptance requires actual financial sections to be present, so a consolidated
        URL that returns a valid 200 but has no data (e.g. SBICARD) is rejected and
        the standalone URL is tried next.
        """
        normalized = self._normalize_symbol(symbol)
        if normalized in self._page_cache:
            return self._page_cache[normalized]

        soup = None
        for url_tmpl in _BASE_URLS:
            url = url_tmpl.format(symbol=normalized)
            try:
                time.sleep(random.uniform(1.0, 2.0))
                resp = self._session.get(url, timeout=20)
                if resp.status_code == 200:
                    candidate = BeautifulSoup(resp.text, "lxml")
                    if (self._page_has_data(candidate)
                            and self._page_has_recent_annual_data(candidate)
                            and self._page_has_recent_quarterly_data(candidate)):
                        soup = candidate
                        break
            except Exception:
                continue

        if soup:
            self._page_cache[normalized] = soup
        return soup

    def _clean_number(self, val) -> Optional[float]:
        """Parse screener.in values: '1,234.56', '12.5%', '49.91'."""
        if val is None:
            return None
        s = str(val).strip()
        if not s or s in ("-", "", "NA", "N/A", "--"):
            return None
        s = s.replace(",", "").replace("%", "").replace("₹", "").replace("Cr.", "").strip()
        try:
            return float(s)
        except ValueError:
            return None

    def _parse_section_table(self, soup: BeautifulSoup, section_id: str) -> Optional[pd.DataFrame]:
        """
        Find <section id='{section_id}'> and parse its first table.
        Handles tables that put headers in <thead> OR in first <tr> of <tbody>.
        """
        section: Optional[Tag] = soup.find("section", {"id": section_id})
        if not section:
            return None
        return self._parse_table(section)

    def _parse_table(self, container: Tag) -> Optional[pd.DataFrame]:
        """Parse the first <table> inside `container` into a DataFrame."""
        table = container.find("table")
        if not table:
            return None

        all_rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells:
                all_rows.append(cells)

        if not all_rows:
            return None

        # Detect if first row is a header row (contains quarter-like strings or known labels)
        _quarter_re = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}$")
        first = all_rows[0]
        is_header = (
            any(_quarter_re.match(c) for c in first[1:])
            or first[0] in ("", "Shareholding Pattern", "Particulars")
        )

        if is_header:
            headers = first
            data_rows = all_rows[1:]
        else:
            headers = None
            data_rows = all_rows

        if not data_rows:
            return None

        # Detect max row width from data rows
        max_cols = max(len(r) for r in data_rows)

        # If the header has only 1 cell but data rows are wider, the header row
        # only contained the empty label cell — generate synthetic column names
        if headers and len(headers) < max_cols:
            n_value_cols = max_cols - 1   # minus label column
            headers = [headers[0]] + [f"col_{i}" for i in range(1, n_value_cols + 1)]

        if headers:
            n = len(headers)
            padded = [r + [""] * max(0, n - len(r)) for r in data_rows]
            padded = [r[:n] for r in padded]
            return pd.DataFrame(padded, columns=headers)

        return pd.DataFrame(data_rows)

    # ------------------------------------------------------------------
    # Public data methods
    # ------------------------------------------------------------------

    def get_quarterly_results(self, symbol: str) -> Optional[pd.DataFrame]:
        cached = self.cache.read(symbol, "si_quarterly")
        if cached is not None:
            return cached
        soup = self._fetch_page(symbol)
        if not soup:
            return None
        df = self._parse_section_table(soup, "quarters")
        if df is not None and not df.empty:
            self.cache.write(symbol, "si_quarterly", df)
        return df

    def get_annual_results(self, symbol: str) -> Optional[pd.DataFrame]:
        """Annual P&L from <section id='profit-loss'>, enriched with Other Income sub-rows
        (including Exceptional Items) fetched via the schedules AJAX API."""
        cached = self.cache.read(symbol, "si_annual")
        if cached is not None:
            return cached
        soup = self._fetch_page(symbol)
        if not soup:
            return None
        df = self._parse_section_table(soup, "profit-loss")
        if df is None or df.empty:
            return None

        # Enrich with Other Income sub-rows (Exceptional Items, Dividend Income, etc.)
        company_id = self._get_company_id(soup)
        if company_id:
            consolidated = self._is_consolidated(soup)
            schedule = self._fetch_schedule(company_id, "Other Income", "profit-loss", consolidated)
            if schedule:
                df = self._merge_schedule_rows(df, schedule)

        self.cache.write(symbol, "si_annual", df)
        return df

    def _get_company_id(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract screener.in numeric company ID from page HTML."""
        el = soup.find(attrs={"data-company-id": True})
        if el:
            return el.get("data-company-id")
        return None

    def _is_consolidated(self, soup: BeautifulSoup) -> bool:
        """Return True if the fetched page is the consolidated view."""
        return bool(soup.find(attrs={"data-consolidated": True}))

    def _fetch_schedule(
        self, company_id: str, parent: str, section: str, consolidated: bool
    ) -> Optional[dict]:
        """Fetch sub-row data for a balance-sheet parent row via screener.in's internal API."""
        from urllib.parse import quote
        params = f"parent={quote(parent)}&section={section}"
        if consolidated:
            params += "&consolidated="
        url = f"https://www.screener.in/api/company/{company_id}/schedules/?{params}"
        try:
            import time as _time
            import random as _random
            _time.sleep(_random.uniform(0.5, 1.0))
            resp = self._session.get(
                url, timeout=15,
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    def _merge_schedule_rows(self, df: pd.DataFrame, schedule: dict) -> pd.DataFrame:
        """Append schedule sub-rows (from schedules API) into the balance sheet DataFrame."""
        if not schedule:
            return df
        label_col = df.columns[0]
        year_cols = list(df.columns[1:])
        new_rows = []
        for row_label, year_data in schedule.items():
            row = {label_col: row_label}
            for col in year_cols:
                row[col] = year_data.get(str(col), "")
            new_rows.append(row)
        if new_rows:
            sched_df = pd.DataFrame(new_rows, columns=df.columns)
            df = pd.concat([df, sched_df], ignore_index=True)
        return df

    def get_balance_sheet(self, symbol: str) -> Optional[pd.DataFrame]:
        cached = self.cache.read(symbol, "si_balance")
        if cached is not None:
            return cached
        soup = self._fetch_page(symbol)
        if not soup:
            return None
        df = self._parse_section_table(soup, "balance-sheet")
        if df is None or df.empty:
            return None

        # Enrich with sub-rows via schedules API
        company_id = self._get_company_id(soup)
        if company_id:
            consolidated = self._is_consolidated(soup)
            for parent in ["Other Assets", "Borrowings", "Other Liabilities"]:
                schedule = self._fetch_schedule(company_id, parent, "balance-sheet", consolidated)
                if schedule:
                    df = self._merge_schedule_rows(df, schedule)

        self.cache.write(symbol, "si_balance", df)
        return df

    def get_cash_flow(self, symbol: str) -> Optional[pd.DataFrame]:
        cached = self.cache.read(symbol, "si_cashflow")
        if cached is not None:
            return cached
        soup = self._fetch_page(symbol)
        if not soup:
            return None
        df = self._parse_section_table(soup, "cash-flow")
        if df is not None and not df.empty:
            self.cache.write(symbol, "si_cashflow", df)
        return df

    def get_shareholding(self, symbol: str) -> Optional[dict]:
        """
        Shareholding pattern: Promoters%, Pledge%, FII%, DII% with QoQ deltas.

        screener.in structure inside <section id="shareholding">:
          Table rows: Promoters, FIIs, DIIs, Government, Public, No. of Shareholders
          Columns: label col | quarter cols (Sep 2024, Dec 2024, ...)
        """
        cached = self.cache.read(symbol, "si_shareholding")
        if cached is not None:
            row = cached.to_dict(orient="index")
            return list(row.values())[0] if row else None

        soup = self._fetch_page(symbol)
        if not soup:
            return None

        df = self._parse_section_table(soup, "shareholding")
        if df is None or df.empty:
            return None

        result = self._extract_shareholding(df)
        if result:
            self.cache.write(symbol, "si_shareholding", pd.DataFrame([result]))
        return result or None

    def _extract_shareholding(self, df: pd.DataFrame) -> dict:
        """
        Extract promoter/FII/DII values and QoQ deltas from shareholding DataFrame.
        Columns: [label_col, q1, q2, ..., q_latest]
        """
        result: dict = {}

        # Identify quarter columns (all except first)
        cols = list(df.columns)
        label_col = cols[0]
        quarter_cols = cols[1:]

        # Filter to only actual quarter columns (skip any that look like "Trades" or junk)
        _qre = re.compile(r"[A-Z][a-z]{2}\s+\d{4}")
        quarter_cols = [c for c in quarter_cols if _qre.search(str(c))]

        if not quarter_cols:
            # Fallback: treat all non-first columns as quarters
            quarter_cols = cols[1:]

        if not quarter_cols:
            return result

        latest_q = quarter_cols[-1]
        prev_q = quarter_cols[-2] if len(quarter_cols) >= 2 else None
        # 6 quarters back (or oldest available)
        six_q_ago = quarter_cols[-7] if len(quarter_cols) >= 7 else quarter_cols[0]

        def _row(keyword: str) -> Optional[pd.Series]:
            for _, row in df.iterrows():
                label = str(row.iloc[0]).lower().strip()
                if keyword.lower() in label:
                    return row
            return None

        def _val(row: pd.Series, col) -> Optional[float]:
            try:
                raw = row[col]
            except KeyError:
                return None
            return self._clean_number(raw)

        def _delta(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
            if curr is not None and prev is not None:
                return round(curr - prev, 2)
            return None

        # Promoters
        promoter_row = _row("promoter")
        if promoter_row is not None:
            curr = _val(promoter_row, latest_q)
            prev = _val(promoter_row, prev_q) if prev_q else None
            old6 = _val(promoter_row, six_q_ago)
            result["promoter_pct"] = curr
            result["promoter_delta"] = _delta(curr, prev)
            result["promoter_6q_delta"] = _delta(curr, old6)

        # FIIs
        fii_row = _row("fii")
        if fii_row is None:
            fii_row = _row("foreign institutional")
        if fii_row is None:
            fii_row = _row("foreign portfolio")
        if fii_row is not None:
            curr = _val(fii_row, latest_q)
            prev = _val(fii_row, prev_q) if prev_q else None
            old6 = _val(fii_row, six_q_ago)
            result["fii_pct"] = curr
            result["fii_delta"] = _delta(curr, prev)
            result["fii_6q_delta"] = _delta(curr, old6)

        # DIIs
        dii_row = _row("dii")
        if dii_row is None:
            dii_row = _row("domestic institutional")
        if dii_row is not None:
            curr = _val(dii_row, latest_q)
            prev = _val(dii_row, prev_q) if prev_q else None
            old6 = _val(dii_row, six_q_ago)
            result["dii_pct"] = curr
            result["dii_delta"] = _delta(curr, prev)
            result["dii_6q_delta"] = _delta(curr, old6)

        # Pledge — usually a sub-row under Promoters or in a separate section
        pledge_row = _row("pledge")
        if pledge_row is not None:
            curr = _val(pledge_row, latest_q)
            prev = _val(pledge_row, prev_q) if prev_q else None
            old6 = _val(pledge_row, six_q_ago)
            result["promoter_pledge_pct"] = curr
            result["pledge_delta"] = _delta(curr, prev)
            result["pledge_6q_delta"] = _delta(curr, old6)

        # Public
        public_row = _row("public")
        if public_row is not None:
            curr = _val(public_row, latest_q)
            prev = _val(public_row, prev_q) if prev_q else None
            old6 = _val(public_row, six_q_ago)
            result["public_pct"] = curr
            result["public_delta"] = _delta(curr, prev)
            result["public_6q_delta"] = _delta(curr, old6)

        return result

    def get_ratios(self, symbol: str) -> Optional[dict]:
        """Key ratios from screener.in top panel: P/E, P/B, ROE, ROCE."""
        cached = self.cache.read(symbol, "si_ratios")
        if cached is not None:
            row = cached.to_dict(orient="index")
            return list(row.values())[0] if row else None

        soup = self._fetch_page(symbol)
        if not soup:
            return None

        result: dict = {}
        try:
            top_ratios = soup.find("ul", {"id": "top-ratios"})
            if top_ratios:
                for li in top_ratios.find_all("li"):
                    name_span = li.find("span", class_="name")
                    val_span = li.find("span", class_="value")
                    if not name_span or not val_span:
                        continue
                    name = name_span.get_text(strip=True).lower()
                    # value span may contain a nested <span> with the number
                    val_text = val_span.get_text(strip=True)
                    val = self._clean_number(val_text)

                    if "stock p/e" in name or name == "p/e":
                        result["pe"] = val
                    elif "price to book" in name or "p/b" in name:
                        result["pb"] = val
                    elif "return on equity" in name or name == "roe":
                        result["roe"] = val
                    elif "roce" in name:
                        result["roce"] = val
                    elif "debt / equity" in name or "debt to equity" in name:
                        result["de_ratio"] = val
                    elif "market cap" in name:
                        result["market_cap"] = val
                    elif "dividend yield" in name:
                        result["dividend_yield"] = val
                    elif "eps" in name:
                        result["eps"] = val
        except Exception:
            pass

        if result:
            self.cache.write(symbol, "si_ratios", pd.DataFrame([result]))
        return result or None

    def get_working_capital_ratios(self, symbol: str) -> Optional[dict]:
        """
        Parse screener.in's annual Ratios table (<section id="ratios">) to get
        Debtor Days, Inventory Days, Days Payable, CCC for the latest year.
        These are far more reliable than yfinance balance sheet data for Indian stocks.
        """
        cached = self.cache.read(symbol, "si_wc_ratios")
        if cached is not None:
            row = cached.to_dict(orient="index")
            return list(row.values())[0] if row else None

        soup = self._fetch_page(symbol)
        if not soup:
            return None

        df = self._parse_section_table(soup, "ratios")
        if df is None or df.empty:
            return None

        try:
            # Columns: [label, Mar 2014, Mar 2015, ..., Mar 2025]
            # Take the last column as the most recent year
            cols = list(df.columns)
            if len(cols) < 2:
                return None
            latest_col = cols[-1]

            def _row_val(keyword: str) -> Optional[float]:
                for _, row in df.iterrows():
                    label = str(row.iloc[0]).lower().strip()
                    if keyword.lower() in label:
                        return self._clean_number(row[latest_col])
                return None

            result = {
                "debtor_days":    _row_val("debtor days"),
                "inventory_days": _row_val("inventory days"),
                "days_payable":   _row_val("days payable"),
                "ccc":            _row_val("cash conversion cycle"),
                "working_capital_days": _row_val("working capital days"),
                "source_year":    str(latest_col),
            }
            # Only cache if we got at least one value
            if any(v is not None for k, v in result.items() if k != "source_year"):
                self.cache.write(symbol, "si_wc_ratios", pd.DataFrame([result]))
            return result
        except Exception:
            return None

    def get_quarterly_pdf_links(self, symbol: str, max_quarters: int = 6) -> list[dict]:
        """
        Extract quarterly result PDF links from screener.in.

        Looks inside ``<section id="quarters">`` for any table row whose cells
        contain ``<a href="…">`` anchors pointing to PDF files (BSE/NSE filings).

        Returns a list of ``{quarter: str, url: str}`` dicts for the most recent
        `max_quarters` quarters, ordered newest-first.
        """
        soup = self._fetch_page(symbol)
        if not soup:
            return []

        section = soup.find("section", {"id": "quarters"})
        if not section:
            return []

        table = section.find("table")
        if not table:
            return []

        # Collect column headers so we can label each PDF by its quarter
        headers: list[str] = []
        first_tr = table.find("tr")
        if first_tr:
            for cell in first_tr.find_all(["th", "td"]):
                headers.append(cell.get_text(strip=True))

        pdf_links: list[dict] = []

        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue

            # Only process rows that look like PDF rows
            row_label = cells[0].get_text(strip=True).lower()
            has_anchors = any(c.find("a") for c in cells[1:])
            if not has_anchors:
                continue
            # Accept rows whose label hints at PDF *or* any anchor that looks like a PDF URL
            def _is_pdf_url(href: str) -> bool:
                h = href.lower()
                return (
                    h.endswith(".pdf")
                    or "pdf" in h
                    or "bseindia.com" in h
                    or "nseindia.com" in h
                    or "exchange" in h
                    or "filing" in h
                    or "result" in h
                    or "/source/quarter/" in h   # screener.in redirect links
                )

            row_is_pdf_row = "pdf" in row_label

            for i, cell in enumerate(cells[1:], 1):
                a_tag = cell.find("a")
                if not a_tag:
                    continue
                href = (a_tag.get("href") or "").strip()
                if not href:
                    continue
                # Resolve relative URLs (screener.in returns paths like /company/source/...)
                if href.startswith("/"):
                    href = "https://www.screener.in" + href
                if row_is_pdf_row or _is_pdf_url(href):
                    quarter_label = headers[i] if i < len(headers) else f"Q{i}"
                    # Deduplicate by quarter label
                    if not any(p["quarter"] == quarter_label for p in pdf_links):
                        pdf_links.append({"quarter": quarter_label, "url": href})

        # Table shows oldest→newest (left→right); reverse so newest comes first
        pdf_links.reverse()
        return pdf_links[:max_quarters]

    def fetch_all(self, symbol: str) -> dict:
        """
        Fetch all screener.in data — ONE HTTP request for the whole page,
        then parse each section from the cached soup.
        """
        # Warm the page cache with a single request
        self._fetch_page(symbol)

        return {
            "symbol": symbol,
            "quarterly_results": self.get_quarterly_results(symbol),
            "annual_results": self.get_annual_results(symbol),
            "balance_sheet": self.get_balance_sheet(symbol),
            "cash_flow": self.get_cash_flow(symbol),
            "shareholding": self.get_shareholding(symbol),
            "ratios": self.get_ratios(symbol),
            "wc_ratios": self.get_working_capital_ratios(symbol),
        }
