# Indian Stock Screener

A terminal-based fundamental analysis tool for Indian listed stocks. Fetches financial data from two sources, runs quantitative screening checks, and optionally generates AI-powered narrative analysis using Claude.

---

## What It Does

- **Single stock deep-dive** — growth metrics, profitability, debt health, shareholding pattern, valuation ratios, historical P/E context, working capital, and red flag detection
- **Batch scan** — screen a watchlist of symbols and display a comparison table sorted by score
- **AI narrative** (optional, requires Anthropic API key) — Claude analyses price action vs fundamentals over a chosen time horizon (6M / 1Y / 2Y / 3Y) and gives a 6-month forward prediction with risks, catalysts, and confidence level
- **PDF audit scan** (optional) — downloads quarterly audit reports from screener.in and flags auditor qualifications, going concern opinions, emphasis of matter, and CARO issues

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Screen a single stock
python -m screener screen RELIANCE.NS

# Screen with AI narrative + audit scan
python -m screener screen TCS.NS --ai

# Batch scan from a watchlist file
python -m screener scan --watchlist stocks.txt

# Batch scan with inline symbols
python -m screener scan --symbols "INFY.NS,WIPRO.NS,TCS.NS"

# Export results to CSV
python -m screener scan --watchlist stocks.txt --output results.csv

# Filter batch results by minimum score
python -m screener scan --watchlist stocks.txt --min-score 60

# Clear cache for a symbol (force fresh data)
python -m screener clear-cache RELIANCE.NS

# Clear all cached data
python -m screener clear-cache
```

---

## AI Mode

Run any screen with `--ai` to unlock:

1. **Horizon selection** — arrow-key menu to choose how far back to look (6 months, 1 year, 2 years, 3 years)
2. **Audit PDF scan** — downloads and analyses quarterly audit reports for the chosen period
3. **Claude narrative** — historical trend analysis + 6-month forward prediction with risks and catalysts
4. **Follow-up Q&A** — type questions about the analysis directly in the terminal

```bash
export ANTHROPIC_API_KEY=your_key_here
python -m screener screen RELIANCE.NS --ai
```

---

## Screening Score

Every stock gets a score out of 100 based on weighted checks:

| Rating       | Score  |
|-------------|--------|
| STRONG BUY  | 80–100 |
| BUY         | 60–79  |
| WATCH       | 40–59  |
| AVOID       | 20–39  |
| SELL        | 0–19   |

Red flags deduct points. The score weights are configurable in `config/thresholds.yaml`.

---

## Data Sources

| Source | Data Provided |
|--------|--------------|
| **yfinance** | Price, quarterly income/balance/cashflow, historical P/E (1Y/5Y/10Y) |
| **screener.in** | Shareholding pattern, promoter pledge, FII/DII activity, working capital ratios, quarterly audit PDF links |

Both sources are cached locally as CSV files (24-hour TTL) to avoid repeated network calls.

---

## Watchlist File Format

One symbol per line. Lines starting with `#` are comments.

```
# Nifty 50 picks
RELIANCE.NS
TCS.NS
HDFCBANK.NS
# INFY.NS  <- excluded
NESTLEIND.NS
```
