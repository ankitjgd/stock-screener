# Indian Stock Screening Guide — Quarterly Audit Reference

A standalone reference for evaluating Indian listed companies each quarter. Use this alongside the CLI tool or independently for manual analysis.

---

## Table of Contents

1. [Quarterly P&L Quality](#1-quarterly-pl-quality)
2. [Auditor Opinion & Key Phrases](#2-auditor-opinion--key-phrases)
3. [Debt Health Analysis](#3-debt-health-analysis)
4. [Promoter & Institutional Activity](#4-promoter--institutional-activity)
5. [Valuation Ratios](#5-valuation-ratios)
6. [Red Flag Checklist](#6-red-flag-checklist)
7. [Sector-Specific Notes](#7-sector-specific-notes)
8. [Quantitative Scorecard Template](#8-quantitative-scorecard-template)

---

## 1. Quarterly P&L Quality

### 1.1 Revenue (Net Sales)

| Signal | Threshold | Action |
|--------|-----------|--------|
| Strong growth | YoY > 15% | Positive |
| Acceptable growth | YoY 10–15% | Neutral |
| Weak growth | YoY 0–10% | Watch |
| Revenue decline | YoY < 0% | RED FLAG |
| Revenue recognition change | Note in results | Investigate |

**Key checks:**
- Compare standalone vs consolidated revenue — large divergence can hide holding company losses
- Check if growth is organic or acquisition-driven (check balance sheet for goodwill spike)
- Revenue with rising debtors = possible channel stuffing

### 1.2 EBITDA Margin

EBITDA = Operating Profit before depreciation, interest, and tax.

| Signal | Threshold |
|--------|-----------|
| High-quality | Margin > 20% |
| Acceptable | Margin 10–20% |
| Low quality | Margin < 10% |
| Deteriorating | 8-quarter declining trend |

**Calculation:** `EBITDA Margin = EBITDA / Net Sales × 100`

Watch for: margins recovering only due to cost cuts (not revenue growth) — unsustainable.

### 1.3 PAT (Profit After Tax)

PAT quality matters more than PAT quantum.

**Key checks:**
- **Exceptional items**: Strip them out. Compare recurring PAT YoY.
- **Other income**: If "Other Income" > 20% of PBT, the business may not be generating real operating profit.
- **Tax rate anomalies**: Unusually low effective tax rate (<15%) — check for deferred tax assets or one-time exemptions.
- **Minority interest**: In consolidated results, large minority interest deductions can distort PAT picture.

### 1.4 EPS (Earnings Per Share)

- Use **Diluted EPS** for proper comparison (accounts for warrants, ESOPs)
- EPS declining despite PAT rising → check for fresh equity dilution
- Consistent EPS growth of 15%+ YoY over 4+ quarters = quality signal

### 1.5 Operating Cash Flow (OCF) Quality

**The most important number that analysts overlook.**

```
OCF/PAT Ratio = Operating Cash Flow / Net Profit After Tax
```

| Ratio | Interpretation |
|-------|----------------|
| > 1.0 | Excellent — company collecting more cash than it reports as profit |
| 0.75–1.0 | Good |
| 0.5–0.75 | Mediocre — watch receivables |
| < 0.5 | Poor — profits may be paper gains |
| < 0 | RED FLAG — negative OCF despite positive PAT |

**OCF declining while PAT rising** = one of the strongest red flags in Indian markets. Classic signs of:
- Aggressive revenue recognition
- Rising debtors (customers not paying)
- Inventory pile-up
- Related party transactions inflating paper profits

---

## 2. Auditor Opinion & Key Phrases

### 2.1 Audit Opinion Types

| Opinion | Meaning | Action |
|---------|---------|--------|
| **Unqualified (Clean)** | No issues found | Normal |
| **Qualified** | Auditor disagrees on specific items | Investigate qualification |
| **Adverse** | Financial statements materially misstated | SELL signal |
| **Disclaimer** | Auditor unable to form opinion | SELL signal |
| **Emphasis of Matter** | Not a qualification, but drawing attention | Read the note carefully |

### 2.2 Red Flag Phrases in Audit Reports

| Phrase | Risk Level | What It Means |
|--------|------------|---------------|
| "Going concern" | CRITICAL | Company may not survive 12 months |
| "Material uncertainty" | HIGH | Serious doubt about viability |
| "Qualified opinion" | HIGH | Auditor disagrees with treatment |
| "Emphasis of matter" | MEDIUM | Something needs attention |
| "Contingent liabilities" (large) | MEDIUM-HIGH | Hidden future obligations |
| "Related party transactions not at arm's length" | HIGH | Money may be siphoned |
| "Loans and advances to subsidiaries" (rising) | MEDIUM | Cash may be parked away |
| "Revenue recognition policy changed" | MEDIUM | May inflate current year profits |

### 2.3 CARO (Companies Audit Report Order) Checks

CARO 2020 requires auditors to comment on:
- Whether loans to related parties are prejudicial to company's interest
- Whether term loans were used for intended purpose
- Whether company has defaulted on any dues to banks/FIs
- Fraud detected by/against company

Always read CARO notes in annual reports — quarterly reports don't include full CARO, but watch for mentions.

### 2.4 Auditor Change

- Auditor resignation mid-year → significant red flag
- Frequent auditor rotation (every 1-2 years) → possible opinion shopping
- Big 4 replacing smaller auditor → usually positive
- Smaller auditor replacing Big 4 → investigate why

---

## 3. Debt Health Analysis

### 3.1 Key Debt Ratios

**Debt/Equity Ratio (D/E)**
```
D/E = Total Debt / Shareholders' Equity
```

| D/E | Signal |
|-----|--------|
| < 0.5 | Debt-free / very low debt |
| 0.5–1.0 | Conservative |
| 1.0–2.0 | Moderate — monitor |
| > 2.0 | HIGH RISK |
| > 3.0 | RED FLAG (except banks/NBFCs) |

Note: Banks/NBFCs have structurally high D/E — use Capital Adequacy Ratio (CAR) instead.

**Interest Coverage Ratio (ICR)**
```
ICR = EBIT / Interest Expense
```

| ICR | Signal |
|-----|--------|
| > 5x | Very safe |
| 3–5x | Comfortable |
| 1.5–3x | Caution |
| < 1.5x | RED FLAG — barely covering interest |
| < 1.0x | CRITICAL — interest not covered |

**Net Debt / EBITDA**
```
Net Debt = Total Debt − Cash & Equivalents
Net Debt/EBITDA = Net Debt / Annual EBITDA
```

| Ratio | Signal |
|-------|--------|
| < 1x | Very comfortable |
| 1–2x | Manageable |
| 2–3x | Watch |
| > 3x | Concerning |
| > 5x | RED FLAG |

### 3.2 Debt Quality Checks

- **Short-term vs Long-term debt**: High short-term debt (CP, working capital loans) in a rising interest rate cycle = refinancing risk
- **Debt vs Revenue growth**: Debt growing faster than revenue = LEVERAGE for GROWTH problem
- **Debt for capex vs operations**: Debt taken for capacity expansion is acceptable; debt to fund operations is a red flag
- **Promoter-level debt**: Check if promoters have pledged shares to borrow — company balance sheet may look clean but promoter is leveraged

### 3.3 Contingent Liabilities

Found in notes to accounts. Include:
- Disputed tax demands
- Pending litigation
- Bank guarantees
- Performance guarantees

**Red flag**: Contingent liabilities > 50% of Net Worth

Always read management commentary on probability of crystallization.

### 3.4 Working Capital Analysis

```
Debtor Days = (Trade Receivables / Net Sales) × 365
Inventory Days = (Inventory / COGS) × 365
Creditor Days = (Trade Payables / Purchases) × 365
Cash Conversion Cycle = Debtor Days + Inventory Days − Creditor Days
```

**Warning signs:**
- Debtor days rising QoQ → customers not paying, or aggressive revenue recognition
- Inventory days rising → demand slowdown or procurement issues
- Creditor days falling rapidly → losing supplier confidence

---

## 4. Promoter & Institutional Activity

### 4.1 Promoter Holding

| Holding % | Interpretation |
|-----------|----------------|
| > 60% | Strong promoter control |
| 40–60% | Normal |
| 25–40% | Low — vulnerable to takeover |
| < 25% | Very low — investigate |

**Promoter Buying (increase in stake):**
- Promoters buying open market → strong confidence signal
- Creeping acquisition (buying up to 5% per year without open offer) → accumulation

**Promoter Selling:**
- Selling > 2% in a quarter → investigate reason
- Selling through bulk/block deals → may be distress or diversification
- Selling after stock split/bonus → may be suspect

**CLI Scoring — Promoter Holding Change (max ±10 pts):**

| QoQ Change | Score Impact |
|------------|-------------|
| > +1% | +6 (strong buying signal) |
| 0 to +1% | +2 (mild accumulation) |
| 0 to −threshold | −3 (mild selling) |
| < −threshold | −8 (meaningful selling) |

6-quarter trend reinforces the QoQ signal: sustained buying over 6Q adds +2; sustained selling subtracts −2.

### 4.2 Promoter Pledge

**Pledge mechanics**: Promoter borrows money by pledging shares. If stock price falls below margin, lender can sell shares → cascade fall.

| Pledge % of Promoter Holding | Risk |
|------------------------------|------|
| 0% | No risk |
| < 10% | Low |
| 10–25% | Moderate — monitor |
| > 25% | HIGH RISK |
| > 50% | RED FLAG |

**Critical signal**: Pledge percentage INCREASING quarter-over-quarter means promoter is borrowing MORE against shares — financial stress indicator.

### 4.3 FII/FPI Activity

FII (Foreign Institutional Investors) / FPI (Foreign Portfolio Investors) are sophisticated, information-rich investors.

| Signal | Interpretation |
|--------|----------------|
| FII buying > 1% QoQ | Bullish — international money coming in |
| FII holding steady | Neutral |
| FII selling > 1% QoQ | Caution — may signal concerns |
| FII selling + DII buying | Transition — domestic confidence |
| Both FII + DII selling | RED FLAG |

**Key nuance**: FII selling may be due to global EM outflows (macro, not company-specific). Check broader FII activity before concluding.

**CLI Scoring — FII Activity (max ±6 pts):**

| FII QoQ Change | Score Impact |
|----------------|-------------|
| ≥ 2× threshold (e.g. ≥ +2%) | +6 |
| ≥ threshold (e.g. ≥ +1%) | +3 |
| 0 to −threshold | 0 |
| ≤ −threshold | −3 |
| ≤ −2× threshold | −6 |

Threshold defaults to `fii_increase_min_pct: 1.0` in `config/thresholds.yaml`.

### 4.4 DII Activity

DII (Domestic Institutional Investors) = Mutual Funds + Insurance companies + Pension funds.

- DII often provides support during FII selling (counter-cyclical)
- Systematic buying from DII (MF SIP flows) provides floor
- DII reducing despite FII buying = unusual, investigate

**CLI Scoring — DII Activity (secondary signal, max ±3 pts):**

| DII QoQ Change | Score Impact |
|----------------|-------------|
| ≥ threshold | +3 |
| 0 to −threshold | 0 |
| ≤ −threshold | −3 |

### 4.5 Shareholding Concentration Risk

- If top 5 shareholders hold > 80%, liquidity is thin
- Free float < 15% → large bid-ask spreads, manipulation risk
- High HNI (High Net Worth Individual) concentration → volatile moves

---

## 5. Valuation Ratios

### 5.1 Price to Earnings (P/E)

```
P/E = Market Price / Earnings Per Share (EPS)
Trailing P/E = Price / Last 12 months EPS
Forward P/E = Price / Next 12 months estimated EPS
```

**P/E context matters more than absolute number:**
- A P/E of 50 for a 40% growth company may be cheap (PEG < 1.25)
- A P/E of 15 for a declining business is expensive

| P/E Range | Signal (for average Indian company) |
|-----------|-------------------------------------|
| < 10 | Very cheap (or value trap — verify) |
| 10–20 | Reasonable |
| 20–35 | Growth premium, justified if growth > 15% |
| 35–60 | High expectations priced in |
| > 60 | Speculative — needs very high growth |

**Historical P/E vs Mean (most powerful valuation signal):**

Compare the current P/E to the stock's own 5-year (or 1-year) mean P/E. This accounts for sector-specific re-rating and is far more useful than an absolute P/E threshold.

```
P/E Ratio = Current P/E / Historical Mean P/E (5Y preferred, 1Y fallback)
```

| Ratio | Interpretation |
|-------|----------------|
| < 0.70 | Trading at steep discount to own history — strong value opportunity |
| 0.70–0.90 | Moderately undervalued |
| 0.90–1.15 | Fair value — near historical average |
| 1.15–1.40 | Moderately overvalued |
| > 1.40 | Significantly above historical average — priced for perfection |

**CLI Scoring — Historical P/E vs Mean (max ±8 pts):**

| P/E Ratio (Current / Mean) | Score Impact |
|----------------------------|-------------|
| < 0.70 | +8 (deep discount) |
| 0.70–0.90 | +4 (mild discount) |
| 0.90–1.15 | 0 (fair value) |
| 1.15–1.40 | −4 (mild premium) |
| > 1.40 | −8 (significant premium) |

### 5.2 Price to Book (P/B)

```
P/B = Market Cap / Book Value of Equity
```

Most useful for capital-intensive businesses: banks, insurance, metals, cement.

| P/B Range | Signal |
|-----------|--------|
| < 1x | Cheap — trading below book value |
| 1–2x | Reasonable |
| 2–5x | Premium for quality |
| > 5x | Only justified for very high ROE businesses |

**Buffett rule**: Buy when P/B is low AND ROE is consistently high.

### 5.3 EV/EBITDA

```
Enterprise Value = Market Cap + Total Debt − Cash
EV/EBITDA = Enterprise Value / EBITDA (annualized)
```

Preferred over P/E for capital-intensive or leveraged companies because it ignores capital structure.

| EV/EBITDA | Signal |
|-----------|--------|
| < 8x | Cheap |
| 8–15x | Reasonable |
| 15–20x | Growth premium |
| > 20x | Expensive |

### 5.4 PEG Ratio

```
PEG = P/E Ratio / EPS Growth Rate (%)
```

| PEG | Interpretation |
|-----|----------------|
| < 0.75 | Undervalued relative to growth |
| 0.75–1.25 | Fair value |
| 1.25–2.0 | Slight premium |
| > 2.0 | Expensive relative to growth |

Rule of thumb: PEG < 1 = growth is "on sale".

### 5.5 Dividend Yield

```
Dividend Yield = Annual DPS / Market Price × 100
```

- Yield > 3% for a growing company → often mispriced by market
- Dividend cuts despite rising PAT → management not sharing profits (governance concern)
- Very high yield (>8%) for a regular company → may be a dividend trap (yield due to falling stock price)

---

## 6. Red Flag Checklist

### 6.1 Balance Sheet Red Flags

- [ ] D/E > 2x (non-financial company)
- [ ] Contingent liabilities > 50% of Net Worth
- [ ] Large loans/advances to subsidiaries or related parties (that are loss-making)
- [ ] Goodwill > 30% of total assets (acquisition addiction)
- [ ] Reserves declining despite reported profits
- [ ] Cash declining while debt rising
- [ ] Book value declining — equity erosion

### 6.2 P&L Red Flags

- [ ] Revenue declining YoY
- [ ] PAT declining while revenue growing (margin collapse)
- [ ] Other Income > 20% of PBT (operating business weak)
- [ ] EPS dilution despite PAT growth (fresh equity at bad valuations)
- [ ] Exceptional/extraordinary items in 3+ consecutive quarters (normalizing the extraordinary)
- [ ] Effective tax rate < 15% without clear explanation

### 6.3 Cash Flow Red Flags

- [ ] Negative OCF with positive PAT
- [ ] OCF declining 3+ consecutive quarters while PAT rises
- [ ] Consistently negative FCF for 3+ years (capex-heavy without visible payoff)
- [ ] Investing cash outflows > operating cash inflows without a clear capex story
- [ ] Cash from financing (borrowing) used to pay dividends

### 6.4 Promoter / Management Red Flags

- [ ] Promoter pledge > 25% of their holding
- [ ] Promoter pledge increasing > 5% QoQ
- [ ] Promoter selling via block deals while announcing buybacks
- [ ] Frequent management changes (CEO/CFO/auditor)
- [ ] Company has multiple subsidiaries in tax havens
- [ ] Related party transactions growing faster than revenue
- [ ] Promoter salary/perquisites growing faster than PAT

### 6.5 Qualitative Red Flags

- [ ] Qualified / Adverse audit opinion
- [ ] "Going concern" in auditor's report
- [ ] SEBI action: insider trading probe, order for forensic audit
- [ ] Promoter arrested or under investigation
- [ ] Company switching auditors frequently
- [ ] BSE/NSE surveillance actions (GSM, ASM framework)
- [ ] Media reports of corporate governance issues

---

## 7. Sector-Specific Notes

### 7.1 Banking & NBFCs

**Key metrics (different from regular companies):**

| Metric | What It Measures | Threshold |
|--------|-----------------|-----------|
| NIM (Net Interest Margin) | Spread on loans vs deposits | > 3% (banks), > 4% (NBFCs) |
| GNPA / NNPA % | Gross / Net Non-Performing Assets | GNPA < 3%, NNPA < 1% |
| PCR (Provision Coverage Ratio) | % of bad loans covered by provisions | > 70% |
| CAR / CRAR | Capital Adequacy Ratio | > 15% |
| Credit-Deposit Ratio | Lending intensity | 70–85% (optimal) |
| ROA | Return on Assets | > 1.5% (banks) |
| ROE | Return on Equity | > 15% |

**Watch for:**
- NPA slippages quarter-over-quarter
- Restructured loans (hidden NPAs)
- Concentration in stressed sectors (real estate, infra)
- Aggressive loan growth without capital raising

### 7.2 IT / Software

**Key metrics:**

| Metric | Threshold |
|--------|-----------|
| Revenue growth (CC) | > 10% YoY |
| EBIT Margin | > 20% |
| Attrition Rate | < 15% |
| Utilisation Rate | > 80% |
| Days Sales Outstanding (DSO) | < 70 days |

**Watch for:**
- Deal wins declining
- Large deals > 10 years (may have thin margins baked in)
- Revenue from top 5 clients > 40% (concentration risk)
- Visa issues for US-dependent revenue

### 7.3 Pharmaceuticals

**Key metrics:**

| Metric | Threshold |
|--------|-----------|
| R&D as % of Revenue | > 6% |
| Gross Margin | > 55% |
| Export % | Higher = better (US generics is premium) |
| EBITDA Margin | > 20% |

**Watch for:**
- FDA import alerts (Warning Letters, Import Alerts)
- ANDA approvals pipeline
- US price erosion in generic drugs
- Domestic MR-to-revenue ratio (large field force without proportionate revenue)
- API vs formulations mix (formulations = better margins)

### 7.4 FMCG

**Key metrics:**

| Metric | Threshold |
|--------|-----------|
| Volume growth | > 5% YoY |
| EBITDA Margin | > 18% |
| Return on Capital | > 30% |
| Market Share | Stable/growing |

**Watch for:**
- Volume vs price-led growth (volume = organic demand, price = inflation pass-through)
- Raw material cost pressure (palm oil, crude derivatives, packaging)
- Distribution expansion vs same-store revenue
- Private label competition in modern trade

### 7.5 Infrastructure / Capital Goods

**Key metrics:**

| Metric | Threshold |
|--------|-----------|
| Order Book / Revenue | 2.5–3.5x (2-3 year visibility) |
| Order Inflow Growth | > 20% |
| Working Capital Days | < 120 |
| D/E | < 0.5 (construction), < 1.5 (project companies) |

**Watch for:**
- Order cancellations / modifications
- Receivables from government (delayed payments are common)
- Subcontracting margins being squeezed
- Debt funding bridge between order execution and payment

---

## 8. Quantitative Scorecard Template

The CLI tool computes a 0–100 score automatically. Both sub-scores start at a neutral **50** and are adjusted up or down based on signals. The final score is:

```
Final Score = BasicScore × 40% + AdvancedScore × 60%
```

### 8.1 Basic Score Components (40% weight)

Each component adjusts the starting score of 50:

| # | Parameter | Criteria | Max Points |
|---|-----------|----------|-----------|
| 1 | Revenue YoY Growth | >20%: +10 · 10–20%: +5 · 0–10%: 0 · <0%: −10 | ±10 |
| 2 | PAT YoY Growth | >20%: +10 · 10–20%: +5 · 0–10%: 0 · <0%: −10 | ±10 |
| 3 | EBITDA Margin + Trend | High margin + improving trend: +10 · low / deteriorating: −10 | ±10 |
| 4 | OCF Quality (OCF/PAT) | >1.0: +15 · 0.75–1: +8 · 0.5–0.75: 0 · <0.5: −10 | ±15 |
| 5 | EPS YoY Growth | >20%: +5 · 10–20%: +3 · <0%: −5 | ±5 |
| 6 | Flags (RED/YELLOW/GREEN) | GREEN: +3 each · YELLOW: −2 each · RED: −5 each | variable |

### 8.2 Advanced Score Components (60% weight)

| # | Parameter | Criteria | Max Points |
|---|-----------|----------|-----------|
| 1 | ROE | >25%: +10 · 15–25%: +5 · 10–15%: 0 · <10%: −10 | ±10 |
| 2 | ROCE | >20%: +8 · 12–20%: +4 · 8–12%: 0 · <8%: −8 | ±8 |
| 3 | Debt/Equity Ratio | <0.3: +10 · 0.3–1: +5 · 1–2: −5 · >2: −15 | ±15 |
| 4 | Interest Coverage | >5×: +5 · 3–5×: +2 · 1.5–3×: −3 · <1.5×: −8 | ±8 |
| 5 | Net Debt / EBITDA | <1×: +5 · 1–2×: +2 · 2–3×: −2 · >3×: −5 | ±5 |
| 6 | Promoter Pledge | 0%: +10 · <10%: +5 · 10–25%: −5 · >25%: −10 | ±10 |
| 7 | **Promoter Holding Change** | QoQ >+1%: +6 · mild buy: +2 · mild sell: −3 · heavy sell: −8 | ±10 |
| 8 | **FII Activity** | QoQ ≥+2%: +6 · ≥+1%: +3 · ≤−1%: −3 · ≤−2%: −6 | ±6 |
| 9 | **DII Activity** | QoQ ≥ threshold: +3 · ≤ −threshold: −3 | ±3 |
| 10 | **Historical P/E vs Mean** | <0.70×: +8 · 0.70–0.90×: +4 · 0.90–1.15×: 0 · 1.15–1.40×: −4 · >1.40×: −8 | ±8 |
| 11 | FCF Trend | Positive + growing: +5 · stable: +2 · declining: −5 | ±5 |
| 12 | Working Capital (Debtor+Inv days) | Improving: +3 · worsening: −3 | ±3 |
| 13 | Revenue Quality Score | Internal signal (0–10 scale) | ±5 |
| 14 | Red Flag Penalty | −5 per RED flag | variable |

> **Bold rows** = factors added in the latest scoring update (FII/DII activity, promoter holding change QoQ, historical P/E vs mean).

### 8.3 Score Interpretation (CLI output)

| Score | Rating | Action |
|-------|--------|--------|
| 80–100 | **STRONG BUY** | High conviction, size up position |
| 60–79 | **BUY** | Good entry, standard position size |
| 40–59 | **WATCH** | Monitor for improvement, don't buy yet |
| 20–39 | **AVOID** | Multiple concerns, stay away |
| < 20 | **SELL** | Consider exiting, serious red flags |

### 8.4 Manual Scorecard (for offline use)

| # | Parameter | Your Assessment | Score | Notes |
|---|-----------|----------------|-------|-------|
| 1 | Revenue Growth (YoY) | | /10 | |
| 2 | PAT Growth (YoY) | | /10 | |
| 3 | EBITDA Margin + Trend | | /10 | |
| 4 | OCF Quality (OCF/PAT) | | /15 | |
| 5 | ROE | | /10 | |
| 6 | ROCE | | /8 | |
| 7 | Debt Health (D/E + ICR) | | /15 | |
| 8 | Promoter Pledge | | /10 | |
| 9 | Promoter Holding Change (QoQ) | | /10 | |
| 10 | FII/DII Activity | | /9 | |
| 11 | Historical P/E vs Mean | | /8 | |
| 12 | FCF Generation | | /5 | |
| 13 | Audit Quality | Clean=0 · Emphasis=−3 · Qualified=−10 · Adverse=−25 | penalty | |
| 14 | Red Flags (count) | | penalty | |
| — | **TOTAL** | | **/120** | normalise to 100 |

---

## Quick Reference Card

### Must-Check 5 Things Every Quarter

1. **OCF vs PAT** — Did cash flow match profit? (OCF/PAT < 0.5 = investigate)
2. **Promoter Pledge** — Did pledge % go up? (Any increase = flag)
3. **Debtor Days** — Are customers paying faster or slower?
4. **Audit Opinion** — Any qualifications or emphasis of matter?
5. **Debt + Interest Coverage** — Can company service its debt comfortably?

### Sources for Indian Stock Data

| Source | Best For | Free? |
|--------|----------|-------|
| screener.in | Financial ratios, shareholding, peer comparison | Yes (basic) |
| moneycontrol.com | News, management interviews, shareholding | Yes |
| bseindia.com | Official filings, quarterly results PDF | Yes |
| nseindia.com | Bulk/block deals, insider trading data | Yes |
| ratestar.in | Credit ratings, NCD/bond details | Yes |
| capitaline.com | Deep historical data, segment breakdowns | Paid |
| Investor Relations page | Management commentary, concall transcripts | Yes |

### Concall Transcript Analysis — 5 Key Questions

1. What is management saying about the next 2–3 quarters? (Forward guidance)
2. What are the reasons for any margin pressure? Are they temporary?
3. Is the management blaming external factors for every bad metric?
4. What is the capital allocation plan — buyback, capex, dividends, acquisitions?
5. How many times does management use the word "headwinds" vs "opportunities"?

---

*This guide is for educational purposes. Always do your own due diligence. Past performance is not indicative of future returns.*
