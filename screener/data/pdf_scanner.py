"""Download quarterly audit PDFs and scan for red flags.

Strategy (auto-selected):
  1. Claude AI  — semantic analysis via Anthropic API (requires ANTHROPIC_API_KEY)
  2. Structural — looks for explicit section headings that only appear in problem reports
                  (e.g. "Basis for Qualified Opinion", "Material Uncertainty Related to Going Concern")

The old naive keyword approach is intentionally removed — it produced too many false positives
because phrases like "no instances of fraud" and "going concern basis of accounting" appear in
every clean Indian quarterly audit report as standard boilerplate.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

try:
    import pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _PDFPLUMBER_AVAILABLE = False

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AuditFlag:
    level: str          # "RED" | "YELLOW"
    category: str
    keyword: str        # short phrase that triggered the flag (empty for LLM flags)
    context: str        # surrounding text or LLM description
    quarter: str


@dataclass
class AuditScanResult:
    symbol: str
    quarters_scanned: list[str] = field(default_factory=list)
    flags: list[AuditFlag] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    strategy_used: str = "structural"   # "llm" | "structural"

    @property
    def red_count(self) -> int:
        return sum(1 for f in self.flags if f.level == "RED")

    @property
    def yellow_count(self) -> int:
        return sum(1 for f in self.flags if f.level == "YELLOW")

    @property
    def is_clean(self) -> bool:
        return self.red_count == 0 and self.yellow_count == 0


# ---------------------------------------------------------------------------
# Structural section patterns (fallback, no API required)
#
# These headings are ONLY present in modified/qualified/adverse/disclaimer reports.
# A clean unqualified Indian audit / limited review report will NEVER contain them.
# ---------------------------------------------------------------------------

_STRUCTURAL_RED: dict[str, list[str]] = {
    "Qualified Opinion": [
        r"basis\s+for\s+qualified\s+(?:opinion|review\s+conclusion|conclusion)",
        r"qualified\s+(?:opinion|review\s+conclusion)\b",
    ],
    "Adverse Opinion": [
        r"basis\s+for\s+adverse\s+(?:opinion|conclusion)",
        r"adverse\s+opinion\b",
    ],
    "Disclaimer of Opinion": [
        r"disclaimer\s+of\s+opinion",
        r"basis\s+for\s+disclaimer\s+of\s+opinion",
    ],
    "Going Concern Doubt": [
        # "Material Uncertainty Related to Going Concern" is a SPECIFIC section heading
        # that only appears when there is actual doubt — not the boilerplate responsibility text
        r"material\s+uncertainty\s+related\s+to\s+going\s+concern",
        r"substantial\s+doubt\s+about.*?continue\s+as\s+a\s+going\s+concern",
        r"going\s+concern\s+doubt\s+exists",
    ],
    "Fraud Discovered": [
        # Only match POSITIVE findings — exclude standard "no instances of fraud" declaration
        r"instances?\s+of\s+(?:significant\s+)?fraud\s+(?:has|have|was|were)\s+(?:been\s+)?(?:detected|found|identified|discovered|reported)",
        r"fraud\s+amounting\s+to",
    ],
    "CARO Non-Compliance": [
        r"companies\s+auditor.{0,20}report\s+order.*?(?:not\s+complied|non[-\s]compliance|adverse|qualification)",
    ],
    "Loan / NPA": [
        r"declared.*?wilful\s+defaulter",
        r"classified\s+as\s+(?:npa|non[-\s]performing\s+asset)",
    ],
}

_STRUCTURAL_YELLOW: dict[str, list[str]] = {
    "Emphasis of Matter": [
        # This section heading only appears when auditor wants to draw attention to something
        r"emphasis\s+of\s+matter\b",
    ],
    "Key Audit Matter": [
        r"key\s+audit\s+matter\b",
        r"significant\s+audit\s+(?:risk|matter)\b",
    ],
    "Prior Period Restatement": [
        r"restatement\s+of\s+(?:financial\s+(?:statements?|results?))",
        r"prior\s+period\s+error\b",
    ],
    "NCLT / Insolvency": [
        r"\bnclt\b",
        r"corporate\s+insolvency\s+resolution\s+process",
        r"insolvency\s+and\s+bankruptcy\s+code",
    ],
    "SEBI Action": [
        r"show\s+cause\s+notice\s+(?:from|by|issued\s+by)\s+sebi",
        r"sebi\s+(?:has\s+)?(?:imposed|passed|issued)\s+(?:an?\s+)?(?:order|penalty|direction)",
    ],
}


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_AUDIT_SYSTEM = (
    "You are a senior Chartered Accountant specialising in Indian listed-company audit reports. "
    "You have deep knowledge of Indian GAAP, SEBI LODR, and the Companies Auditor's Report Order (CARO). "
    "You respond only with valid JSON."
)

_AUDIT_PROMPT = """\
Analyse the following quarterly AUDIT / LIMITED REVIEW REPORT extract from an Indian listed company.

CRITICAL RULES (false-positive prevention):
- "there are no instances of significant fraud" → CLEAN declaration, NOT a flag
- "going concern basis of accounting" in management responsibility section → CLEAN boilerplate
- "assessing the company's ability to continue as a going concern" → CLEAN boilerplate
- Any statement confirming the ABSENCE of an issue is CLEAN
- Standard closing declarations signed by auditors are NOT flags

GENUINE RED flags ONLY (these represent actual problems):
• Qualified / Adverse / Disclaimer opinion
• Presence of a "Basis for Qualified/Adverse Opinion" section
• "Material Uncertainty Related to Going Concern" section (not just the words in passing)
• Actual fraud discovered or confirmed (not the standard "no instances" declaration)
• Material misstatement identified and NOT corrected
• Wilful defaulter status / NPA classification
• CARO adverse remarks / non-compliance

YELLOW caution flags (notable but not disqualifying):
• Emphasis of Matter section — what specific item is highlighted?
• Key Audit Matters of significance
• Prior period restatements / errors
• Significant pending litigation (with amount if mentioned)
• NCLT / IBC proceedings
• SEBI regulatory notices or penalties

REPORT TEXT:
{text}

Return ONLY this JSON (no markdown, no explanation):
{{
  "opinion_type": "<unqualified|qualified|adverse|disclaimer|clean_limited_review|modified_limited_review>",
  "red_flags": [{{"category": "<short label>", "description": "<what was specifically found>"}}],
  "yellow_flags": [{{"category": "<short label>", "description": "<what was specifically found>"}}],
  "summary": "<one sentence verdict>"
}}"""


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
}


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

class PDFAuditScanner:
    """
    Downloads quarterly result PDFs and scans for audit red flags.

    If ``ANTHROPIC_API_KEY`` is set, uses Claude for semantic analysis (highly accurate).
    Otherwise falls back to structural section-heading detection (no false positives from
    boilerplate, but may miss issues phrased unusually).

    Model can be overridden via ``SCREENER_AUDIT_MODEL`` env var (default: claude-opus-4-6).
    """

    def __init__(self, timeout: int = 60):
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        self.timeout = timeout
        self._model = os.environ.get("SCREENER_AUDIT_MODEL", "claude-opus-4-6")

    def scan_symbol(self, symbol: str, pdf_links: list[dict]) -> AuditScanResult:
        result = AuditScanResult(symbol=symbol)

        if not _PDFPLUMBER_AVAILABLE:
            result.errors.append("pdfplumber not installed — run: pip install pdfplumber")
            return result

        if not pdf_links:
            result.errors.append("No PDF links found for this symbol.")
            return result

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        use_llm = _ANTHROPIC_AVAILABLE and bool(api_key)
        result.strategy_used = "llm" if use_llm else "structural"

        for item in pdf_links:
            quarter = item.get("quarter", "Unknown")
            url = item.get("url", "")
            if not url:
                continue
            try:
                text = self._download_and_extract(url)
                if not text:
                    result.errors.append(f"{quarter}: could not extract text from PDF")
                    continue
                result.quarters_scanned.append(quarter)
                flags = (
                    self._analyze_with_llm(text, quarter)
                    if use_llm
                    else self._analyze_structural(text, quarter)
                )
                result.flags.extend(flags)
            except requests.exceptions.Timeout:
                result.errors.append(f"{quarter}: download timed out")
            except Exception as exc:
                result.errors.append(f"{quarter}: {exc}")

        return result

    # ------------------------------------------------------------------
    # PDF download + text extraction
    # ------------------------------------------------------------------

    def _download_and_extract(self, url: str) -> Optional[str]:
        resp = self._session.get(url, timeout=self.timeout, stream=True)
        if resp.status_code != 200:
            return None
        ct = resp.headers.get("Content-Type", "")
        if "html" in ct and "pdf" not in ct:
            return None

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            for chunk in resp.iter_content(chunk_size=16384):
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            parts: list[str] = []
            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        parts.append(t)
            return "\n".join(parts)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _extract_auditor_section(self, text: str) -> str:
        """
        Slice out just the auditor's report / limited review section.

        Indian quarterly PDFs follow a standard layout:
          pages 1-3: limited review / auditor's report
          pages 4+:  financial statements (P&L, balance sheet, …)
        We stop at the first financial statement heading to save tokens.
        """
        lower = text.lower()
        start_markers = [
            "independent auditor",
            "limited review report",
            "auditors' report",
            "auditor's report",
            "to the board of directors",
            "to the members",
        ]
        start = 0
        for marker in start_markers:
            idx = lower.find(marker)
            if idx != -1:
                start = max(0, idx - 50)
                break

        end_markers = [
            "statement of profit",
            "consolidated statement of",
            "standalone statement of",
            "balance sheet as at",
            "cash flow statement",
        ]
        end = min(len(text), start + 9000)
        for marker in end_markers:
            idx = lower.find(marker, start + 500)
            if idx != -1 and idx < end:
                end = idx
                break

        section = text[start:end].strip()
        return section if len(section) > 200 else text[:7000]

    # ------------------------------------------------------------------
    # Strategy 1: Claude AI
    # ------------------------------------------------------------------

    def _analyze_with_llm(self, text: str, quarter: str) -> list[AuditFlag]:
        """Semantic analysis via Claude API.  Falls back to structural on any error."""
        try:
            client = anthropic.Anthropic()
            auditor_text = self._extract_auditor_section(text)
            if len(auditor_text) > 7000:
                auditor_text = auditor_text[:7000]

            prompt = _AUDIT_PROMPT.format(text=auditor_text)

            with client.messages.stream(
                model=self._model,
                max_tokens=1024,
                system=_AUDIT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                response = stream.get_final_message()

            raw = response.content[0].text.strip()
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                raise ValueError("No JSON found in LLM response")
            data = json.loads(m.group())
        except Exception:
            # Graceful fallback to structural
            return self._analyze_structural(text, quarter)

        flags: list[AuditFlag] = []

        opinion = data.get("opinion_type", "unqualified")
        summary = data.get("summary", "")

        if opinion in ("qualified", "adverse", "disclaimer", "modified_limited_review"):
            flags.append(AuditFlag(
                level="RED",
                category=f"{opinion.replace('_', ' ').title()} Opinion",
                keyword=opinion,
                context=summary,
                quarter=quarter,
            ))

        for item in data.get("red_flags", []):
            flags.append(AuditFlag(
                level="RED",
                category=item.get("category", "Red Flag"),
                keyword="",
                context=item.get("description", ""),
                quarter=quarter,
            ))

        for item in data.get("yellow_flags", []):
            flags.append(AuditFlag(
                level="YELLOW",
                category=item.get("category", "Caution"),
                keyword="",
                context=item.get("description", ""),
                quarter=quarter,
            ))

        return flags

    # ------------------------------------------------------------------
    # Strategy 2: Structural section detection (no API needed)
    # ------------------------------------------------------------------

    def _analyze_structural(self, text: str, quarter: str) -> list[AuditFlag]:
        """
        Look only for explicit section HEADINGS that are never present in a clean report.

        A clean Indian audit report will NEVER have:
          - "Basis for Qualified Opinion"
          - "Material Uncertainty Related to Going Concern"
          - "Emphasis of Matter"
          - etc.
        So matching these headings has near-zero false-positive rate.
        """
        flags: list[AuditFlag] = []
        lower = text.lower()

        def _ctx(m: re.Match) -> str:
            snippet = text[max(0, m.start() - 60): m.end() + 160]
            return snippet.replace("\n", " ").strip()

        for category, patterns in _STRUCTURAL_RED.items():
            for pat in patterns:
                m = re.search(pat, lower, re.IGNORECASE)
                if m:
                    flags.append(AuditFlag(
                        level="RED",
                        category=category,
                        keyword=m.group(0),
                        context=_ctx(m),
                        quarter=quarter,
                    ))
                    break

        for category, patterns in _STRUCTURAL_YELLOW.items():
            for pat in patterns:
                m = re.search(pat, lower, re.IGNORECASE)
                if m:
                    flags.append(AuditFlag(
                        level="YELLOW",
                        category=category,
                        keyword=m.group(0),
                        context=_ctx(m),
                        quarter=quarter,
                    ))
                    break

        return flags
