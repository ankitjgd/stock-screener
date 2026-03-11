# Deployment & Technical Reference

## Architecture Overview

```
CLI (typer)
  └── cli.py  ─── screen / scan / clear-cache / version commands
        │
        ├── Data Layer
        │     ├── yfinance_fetcher.py   — Yahoo Finance API + cache
        │     └── screener_in.py        — screener.in scraper + cache
        │
        ├── Analysis Layer
        │     ├── basic_screen.py       — growth, margins, OCF quality
        │     └── advanced_screen.py    — debt, shareholding, valuation, red flags
        │
        ├── AI Layer (optional)
        │     ├── pdf_scanner.py        — downloads & analyses audit PDFs
        │     └── narrator.py           — Claude API: narrative + Q&A
        │
        └── Output Layer
              └── formatter.py          — rich tables, CSV export
```

---

## File Structure

```
stock-screener/
├── README.md
├── DEPLOYMENT.md
├── requirements.txt
├── config/
│   └── thresholds.yaml         # All numeric thresholds (no hardcoded values in source)
├── screener/
│   ├── __init__.py             # Version string
│   ├── __main__.py             # Entry point: python -m screener
│   ├── cli.py                  # Typer CLI: screen, scan, clear-cache, version
│   ├── data/
│   │   ├── yfinance_fetcher.py # CacheManager + YFinanceFetcher
│   │   ├── screener_in.py      # ScreenerInFetcher (scrapes screener.in)
│   │   └── pdf_scanner.py      # PDFAuditScanner (downloads + parses audit PDFs)
│   ├── analysis/
│   │   ├── basic_screen.py     # BasicScreener → BasicScreenResult
│   │   └── advanced_screen.py  # AdvancedScreener → AdvancedScreenResult
│   │   └── narrator.py         # Claude AI: narrative generation + follow-up Q&A
│   └── reports/
│       └── formatter.py        # Rich tables, scan summary, CSV export, narrative display
└── data/cache/                 # Auto-created CSV cache files (gitignored)
```

---

## Setup & Installation

### Requirements
- Python 3.9+
- pip

### Steps

```bash
# Clone the repo
git clone <repo-url>
cd stock-screener

# (Recommended) Create a virtual environment
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
.venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# (Optional) Set Anthropic API key for AI features
export ANTHROPIC_API_KEY=sk-ant-...
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `yfinance` | Yahoo Finance data (price, financials, historical P/E) |
| `requests` + `beautifulsoup4` + `lxml` | screener.in HTML scraping |
| `pdfplumber` | Quarterly audit PDF text extraction |
| `pandas` | DataFrame manipulation throughout |
| `rich` | Terminal tables, panels, progress spinners |
| `typer` | CLI framework |
| `questionary` | Arrow-key menus and text input for AI mode |
| `anthropic` | Claude API SDK (AI narrative + audit Q&A) |
| `pyyaml` | Load `config/thresholds.yaml` |

---

## Data Flow — Single Stock (`screen`)

```
python -m screener screen RELIANCE.NS
          │
          ▼
    CacheManager.is_fresh?
    ├─ YES → load CSV from data/cache/
    └─ NO  → fetch from source, write CSV
          │
          ▼
    YFinanceFetcher.fetch_all(symbol)
    ├── price_info         (current price, market cap, sector — always fresh)
    ├── historical_pe      (TTM P/E — 1Y / 5Y / 10Y windows)
    └── price_trend        (6M & 1Y change, high/low, sparkline, MAs)
          │
    ScreenerInFetcher.fetch_all(symbol)
    ├── shareholding       (Promoter%, Pledge%, FII%, DII%, Public%)
    ├── ratios             (P/E, P/B, ROE, ROCE from metrics panel)
    ├── wc_ratios          (Debtor days, Inventory days, CCC)
    ├── quarterly_results  (Sales, OPM%, Net Profit — screener.in format)
    └── annual_results     (Full-year P&L data)
          │
          ▼
    BasicScreener.screen()
    ├── Revenue QoQ / YoY growth vs thresholds
    ├── PAT QoQ / YoY growth vs thresholds
    ├── EPS QoQ / YoY growth
    ├── EBITDA margin (latest + 8Q trend)
    ├── OCF/PAT ratio (cash quality — ≥ 0.75 = healthy)
    └── OCF trend (improving / stable / deteriorating)
          │
    AdvancedScreener.screen()
    ├── ROE / ROCE
    ├── D/E ratio, Interest Coverage, Net Debt/EBITDA
    ├── Promoter holding + QoQ + 6Q change
    ├── Promoter pledge + QoQ + 6Q change
    ├── FII / DII / Public holding + deltas
    ├── P/E, P/B, EV/EBITDA
    ├── Historical P/E context (1Y / 5Y / 10Y mean, min, max)
    ├── Debtor days, Inventory days, Cash Conversion Cycle
    ├── FCF latest + trend
    └── Red flag detection (pledge spike, OCF divergence, debt rising, etc.)
          │
          ▼
    formatter.print_stock_report()
    ├── Header Panel (company, price, market cap, score)
    ├── Growth Metrics table
    ├── Profitability & Cash Quality table
    ├── Debt Health table
    ├── Shareholding Pattern table (Promoter / Pledge / FII / DII / Public)
    ├── Valuation Ratios table
    ├── Historical P/E Context table (1Y / 5Y / 10Y vs current)
    ├── Working Capital Efficiency table
    ├── Flags Panel (RED / YELLOW sorted)
    └── Final Score Panel (score / rating / red flag count)
```

---

## Data Flow — AI Mode (`screen --ai`)

```
python -m screener screen RELIANCE.NS --ai
          │
          ▼
    [Steps 1–5 same as above: fetch + screen + print report]
          │
          ▼
    questionary.select()  →  User picks horizon (6M / 1Y / 2Y / 3Y)
          │
          ▼
    ScreenerInFetcher.get_quarterly_pdf_links(symbol, max_quarters)
    ├── 6M  → up to 2 quarters of PDFs
    ├── 1Y  → up to 4 quarters of PDFs
    ├── 2Y  → up to 8 quarters of PDFs
    └── 3Y  → up to 13 quarters of PDFs
          │
          ▼
    PDFAuditScanner.scan_symbol(symbol, pdf_links)
    ├── Downloads each PDF (with cache)
    ├── Extracts text with pdfplumber
    ├── Scans for auditor keywords:
    │   RED:    "qualified opinion", "going concern", "material uncertainty"
    │   YELLOW: "emphasis of matter", "key audit matter", "CARO"
    └── Returns AuditScanResult (flags per quarter, clean/dirty verdict)
          │
          ▼
    narrator.build_data_block()  →  structured text summary of all data
          │
    narrator.generate_narrative()
    ├── Calls Claude API (claude-opus-4-6, adaptive thinking, streaming)
    ├── Prompt includes: price action, financials, shareholding,
    │   historical P/E, screening flags, audit findings
    ├── Returns JSON:
    │   {
    │     "historical": { "period", "trend_cause", "supporting_factors", "verdict" }
    │     "prediction": { "period": "6M", "outlook", "outlook_basis", "verdict" }
    │     "key_risks": [...],
    │     "key_catalysts": [...],
    │     "confidence": "High|Medium|Low"
    │   }
          │
          ▼
    formatter.print_narrative_report()
    ├── AI Narrative panel (horizons + verdicts + confidence)
    ├── "What happened in the last Xmonths?" section
    ├── "Next 6-Month Prediction" section
    └── "Key Risks vs Catalysts" side-by-side table
          │
          ▼
    Follow-up Q&A loop (questionary.text)
    ├── User types question → narrator.answer_followup()
    ├── Claude answers in plain English citing specific numbers
    ├── Ctrl+C → cancel and re-prompt
    └── Empty Enter → exit
```

---

## Caching

- **Location:** `data/cache/` (relative to project root)
- **Format:** CSV files, one per symbol + data type
- **Naming:** `RELIANCE_NS_quarterly_income.csv`, `RELIANCE_NS_si_shareholding.csv`, etc.
- **TTL:** 24 hours (configurable in `config/thresholds.yaml` → `cache.ttl_hours`)
- **Invalidation:** `python -m screener clear-cache [SYMBOL]`

Cache files are created automatically. If a fetch fails, the cache file is not written and fresh data is attempted on the next run.

### Cache keys

| Key | Source | Contains |
|-----|--------|---------|
| `price_info` | yfinance | Current price, market cap, sector, P/E, P/B — **not cached, always fresh** |
| `price_trend` | yfinance | 6M/1Y price change, high/low, sparkline, MAs |
| `historical_pe` | yfinance | TTM P/E — 1Y / 5Y / 10Y statistics |
| `si_shareholding` | screener.in | Promoter%, Pledge%, FII%, DII%, Public% with deltas |
| `si_ratios` | screener.in | Ratio panel (ROE, ROCE, P/E, P/B) |
| `si_wc_ratios` | screener.in | Working capital ratios (debtor/inventory days) |
| `si_quarterly` | screener.in | Quarterly results table |
| `si_annual` | screener.in | Annual results table |

---

## Scoring System

The combined score (0–100) is a weighted sum of sub-scores from `BasicScreener` and `AdvancedScreener`. Weights are in `config/thresholds.yaml`:

| Component | Weight |
|-----------|--------|
| Revenue growth | 10 |
| PAT growth | 10 |
| EBITDA margin | 8 |
| OCF quality | 12 |
| ROE | 10 |
| ROCE | 8 |
| Debt health | 12 |
| Promoter activity | 10 |
| Valuation | 10 |
| Working capital | 5 |
| Red flag penalty | −5 per flag |

---

## Configuration

All numeric thresholds live in `config/thresholds.yaml`. Edit this file to tune sensitivity without touching source code.

Key thresholds:

| Threshold | Default | Meaning |
|-----------|---------|---------|
| `growth.revenue_yoy_min_pct` | 10% | Min YoY revenue growth for YELLOW flag |
| `profitability.roe_min_pct` | 15% | Min ROE for healthy signal |
| `profitability.ocf_pat_ratio_min` | 0.75 | Cash quality floor |
| `debt.de_ratio_max` | 1.0 | D/E above this = YELLOW |
| `debt.de_ratio_red` | 2.0 | D/E above this = RED |
| `debt.interest_coverage_min` | 3.0x | Coverage below this = YELLOW |
| `shareholding.promoter_pledge_max_pct` | 10% | Pledge above this = YELLOW |
| `shareholding.promoter_pledge_red_pct` | 25% | Pledge above this = RED |
| `cache.ttl_hours` | 24 | Hours before cache is considered stale |

---

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | For `--ai` only | Claude API key for narrative generation and Q&A |
| `SCREENER_NARRATOR_MODEL` | No | Override Claude model (default: `claude-opus-4-6`) |

---

## Graceful Degradation

The app is designed to never crash on missing data:

- If screener.in is unreachable or rate-limits, all `si_*` fields default to `None` and display as `–`
- If yfinance returns no data for a field, it is skipped silently
- If the Anthropic API call fails, the error is shown and the standard report is still displayed
- If PDF download fails for a quarter, that quarter is skipped and an error note is shown

---

## Known Limitations

- **screener.in scraping** — relies on HTML structure; may break if screener.in changes their page layout
- **Historical P/E accuracy** — calculated from TTM EPS constructed from quarterly + annual data; approximate for stocks with irregular reporting
- **PDF audit scan** — keyword-based and semantic only; does not parse financial tables from PDFs
- **yfinance scope** — only used for current price, historical P/E, and price trend; all quarterly financials (revenue, profit, debt, OCF) come exclusively from screener.in

---

## ExcelScreener Web Product (excelscreener.in)

Marketing + app site that wraps this CLI into a Google Sheets product.

### Repo & Deploy
- Repo: `git@github.com:ankitjgd/excelscreener.git`
- Local: `/Users/ankitbhardwaj/Documents/GitHub/excelscreener-marketing/`
- Stack: Next.js 16 App Router, `output: 'export'` (static HTML), Tailwind CSS + inline styles, react-icons
- Deploy via rsync to Hostinger (no git on server):

```bash
cd /Users/ankitbhardwaj/Documents/GitHub/excelscreener-marketing
rm -rf out/ && npm run build
rsync -av --delete --exclude='*.txt' out/ \
  -e "ssh -p 65002" \
  u889244618@46.28.45.163:/home/u889244618/domains/excelscreener.in/public_html/
```

### Product Value Prop
- User has their portfolio in Google Sheets (own formulas, buy price, P&L etc.)
- ExcelScreener adds **only two columns**: `Score` (0–100) and `Comments` (STRONG BUY / BUY / WATCH / AVOID)
- User's existing data, formulas and layout are completely untouched
- Score is computed from 40+ fundamental checks (this CLI's logic)

### Pricing
- **Free**: up to 10 stocks per run, no login required
- **Pro (₹499/mo)**: unlimited stocks, custom scoring weights, weekly/monthly auto-refresh, score change email alerts, 90-day history

### Completed (as of Mar 2026)
- Full marketing site: Home, How It Works, Features, Pricing, Blog (3 posts), FAQ, Screener page
- Hero: animated spreadsheet mockup with scan animation + magnifying glass lens
- Auto-refresh section on home + highlighted in pricing page
- Favicon (`app/icon.svg`) and OG image (`app/opengraph-image.tsx`)
- Mobile responsive: all sections use `mob-*` utility classes, spreadsheet mocks hidden on mobile
- Removed all "Indian"/"India" from page titles, metadata, and copy
- All icons: react-icons only (no emoji/inline SVG)

### Backend (Not Yet Built)
The `/screener` page at `app/screener/page.tsx` is already wired to poll a backend API:

```
POST /run        { sheetUrl, email }  →  { jobId }
GET  /status/{jobId}                  →  { stage, progress, done, resultUrl }
```

Planned architecture:
- **Lambda on AWS** (or similar) runs the Python screener CLI
- **Google Sheets API** via service account: reads column A symbols, writes Score + Comments back
- **EventBridge / cron Lambda** for weekly/monthly auto-refresh
- Set `NEXT_PUBLIC_API_URL` in `.env.production` once Lambda URL is known
- Service account: `screener@excelscreener.iam.gserviceaccount.com`

### Environment Variables (web)
| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_API_URL` | Backend Lambda URL (not set yet) |
| `NEXT_PUBLIC_GA_ID` | Google Analytics (not set yet) |
