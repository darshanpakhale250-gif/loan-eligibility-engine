"""
parsers.py – Regex-based field extractors for loan product pages.

Ported from the original extract_fields.py.  Functions accept raw text
and return structured dicts / lists.  No file I/O — they operate purely
on strings so they can be called from the crawler pipeline or tests.
"""

import html
import re
from datetime import datetime
from urllib.parse import urlparse


# ── text normalisation ──────────────────────────────────────────────

def normalize(value):
    """Decode HTML entities, repair mojibake, and collapse whitespace."""
    if not isinstance(value, str):
        return ""
    text = html.unescape(value)
    markers = ("â‚¹", "â€™", "â€œ", "â€˜", "â€\x9d", "â€“", "â€”", "â€¦")
    if any(marker in text for marker in markers):
        try:
            repaired = text.encode("cp1252").decode("utf-8")
            if not any(marker in repaired for marker in markers):
                text = repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    replacements = {
        "â‚¹": "₹", "â€™": "'", "â€˜": "'", "â€œ": "\u201c",
        "â€\x9d": "\u201d", "â€“": "–", "â€”": "—", "â€¦": "…",
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"[ \t]+", " ", text).strip()


# ── section helpers ─────────────────────────────────────────────────

def get_section(sections, *names):
    if not isinstance(sections, dict):
        return ""
    normalized_sections = {
        str(key).strip().lower().replace("_", " "): value
        for key, value in sections.items()
    }
    for name in names:
        value = normalized_sections.get(name.lower().replace("_", " "))
        if isinstance(value, str) and value.strip():
            return normalize(value)
    return ""


def get_page_url(page):
    return normalize(
        page.get("source_url") or page.get("url") or page.get("URL") or ""
    )


def get_page_title(page):
    return normalize(
        page.get("page_title") or page.get("title")
        or page.get("product_name") or ""
    )


# ── bank identification ────────────────────────────────────────────

def identify_bank(page, url):
    bank = page.get("bank_name") or page.get("bank") or page.get("lender_name")
    if isinstance(bank, str) and bank.strip() and bank.lower() not in {
        "unknown", "unknown bank"
    }:
        return normalize(bank)
    host = (urlparse(url).hostname or "").lower()
    if host.endswith(("sbi.bank.in", "sbi.co.in")):
        return "State Bank of India"
    if host.endswith(("hdfc.bank.in", "hdfcbank.com")):
        return "HDFC Bank"
    if host.endswith("icicibank.com"):
        return "ICICI Bank"
    if host.endswith("axisbank.com"):
        return "Axis Bank"
    if host.endswith(("bankofbaroda.in", "bankofbaroda.bank.in")):
        return "Bank of Baroda"
    if host.endswith("pnbindia.in"):
        return "Punjab National Bank"
    return "Unknown"


# ── amount parsing ─────────────────────────────────────────────────

def parse_amount(number, unit=""):
    try:
        amount = float(str(number).replace(",", ""))
    except (TypeError, ValueError):
        return None
    unit = (unit or "").lower()
    if unit.startswith(("lakh", "lac")):
        amount *= 100_000
    elif unit.startswith("crore"):
        amount *= 10_000_000
    return int(amount)


AMOUNT = r"(?:₹|Rs\.?\s*)?\s*([\d,]+(?:\.\d+)?)\s*(crores?|lakhs?|lacs?)?"


# ── loan amount ────────────────────────────────────────────────────

def extract_loan_amount(*texts):
    """Extract loan amounts near loan-amount wording only."""
    text = normalize("\n".join(t for t in texts if t))
    if not text:
        return {"minimum": None, "maximum": None, "currency": "INR"}

    minimum = maximum = None

    block_match = re.search(
        r"loan\s+amount\s*:?\s*(.{0,600})",
        text, re.IGNORECASE | re.DOTALL
    )
    if block_match:
        block = block_match.group(1)
        block = re.split(
            r"\n\s*(?:employee\s+should|eligibility|interest\s+rates?|"
            r"processing\s+fee|documents|required|age\s*:)",
            block, maxsplit=1, flags=re.IGNORECASE
        )[0]
        for label in ("minimum", "maximum"):
            m = re.search(
                rf"\b{label}\b\s*:?\s*{AMOUNT}", block, re.IGNORECASE
            )
            if m:
                value = parse_amount(m.group(1), m.group(2) or "")
                if label == "minimum":
                    minimum = value
                else:
                    maximum = value

    if minimum is None or maximum is None:
        range_patterns = [
            rf"(?:personal\s+loan|loan)\s+(?:amount\s+)?(?:from\s+)?{AMOUNT}"
            rf"\s+to\s+{AMOUNT}",
            rf"(?:instantly|available|amount)\s+from\s+{AMOUNT}\s+to\s+{AMOUNT}",
            rf"loan\s+of\s+{AMOUNT}\s+to\s+{AMOUNT}",
        ]
        for pattern in range_patterns:
            m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if not m:
                continue
            groups = m.groups()
            if len(groups) == 4:
                low = parse_amount(groups[0], groups[1] or "")
                high = parse_amount(groups[2], groups[3] or "")
            else:
                continue
            if low is not None and high is not None:
                if minimum is None:
                    minimum = low
                if maximum is None:
                    maximum = high
                break

    if minimum is None or maximum is None:
        for line in text.splitlines():
            if not re.search(
                r"loan\s+amount|loan\s+up\s+to|get a loan",
                line, re.IGNORECASE
            ):
                continue
            m = re.search(
                rf"{AMOUNT}\s*(?:to|[-–—])\s*{AMOUNT}", line, re.IGNORECASE
            )
            if m:
                low = parse_amount(m.group(1), m.group(2) or "")
                high = parse_amount(m.group(3), m.group(4) or "")
                if low is not None and high is not None:
                    minimum = low if minimum is None else minimum
                    maximum = high if maximum is None else maximum
                    break

    return {"minimum": minimum, "maximum": maximum, "currency": "INR"}


# ── age range ──────────────────────────────────────────────────────

def extract_age_range(text):
    text = normalize(text)
    patterns = [
        r"\bage(?:\s+of\s+applicant)?\s*:?\s*(\d{2})\s*(?:to|[-–])\s*(\d{2})"
        r"\s*years?\b",
        r"\bbetween\s+(\d{2})\s+and\s+(\d{2})\s*years?\b",
        r"\bminimum\s+age\s*:?\s*(\d{2})\s*years?\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            if len(m.groups()) == 2:
                return {"minimum": int(m.group(1)), "maximum": int(m.group(2))}
            return {"minimum": int(m.group(1)), "maximum": None}
    return {"minimum": None, "maximum": None}


# ── income rules ───────────────────────────────────────────────────

def extract_income(text):
    text = normalize(text)
    rules = []
    salary_match = re.search(
        r"(?:minimum\s+net\s+monthly\s+salary|minimum\s+monthly\s+salary|"
        r"minimum\s+monthly\s+income)\s*:?\s*(.*?)"
        r"(?=\n\s*(?:loan\s+amount|eligibility|credit\s+score|"
        r"employee\s+should)|$)",
        text, re.IGNORECASE | re.DOTALL
    )
    salary_section = salary_match.group(1) if salary_match else text
    patterns = [
        ("government_defence",
         r"(?:government\s*/\s*defen[cs]e|government\s+and\s+defen[cs]e)"
         r"\s+sector\s+employees?\s*:?\s*(?:₹|Rs\.?\s*)?(\d[\d,]*)"),
        ("corporate",
         r"corporate\s+sector\s+employees?\s*:?\s*(?:₹|Rs\.?\s*)?(\d[\d,]*)"),
        ("general",
         r"(?:minimum\s+monthly\s+(?:net\s+)?income|minimum\s+net\s+monthly"
         r"\s+salary|minimum\s+monthly\s+salary|minimum\s+earning)"
         r"\s*(?:of|is|:)?\s*(?:₹|Rs\.?\s*)?(\d[\d,]*)"),
    ]
    for category, pattern in patterns:
        search_text = (
            salary_section
            if category in {"government_defence", "corporate"}
            else text
        )
        for m in re.finditer(pattern, search_text, re.IGNORECASE):
            rule = {
                "employment_category": category,
                "minimum_monthly_income": int(m.group(1).replace(",", "")),
                "currency": "INR",
            }
            if rule not in rules:
                rules.append(rule)
    return rules


# ── credit score ───────────────────────────────────────────────────

def extract_credit_score(text):
    text = normalize(text)
    context = r"(?:cibil|credit\s+score|credit\s+rating|bureau\s+score)"
    patterns = [
        rf"{context}[^\n.]{{0,100}}?\b(?:between|from|of|at least)?\s*"
        rf"(\d{{3}})\s*(?:to|[-–—])\s*(\d{{3}})\b",
        rf"\b(?:minimum|required|preferred)\s+(?:cibil|credit)\s+score"
        rf"\s*(?:of|is|:)?\s*(\d{{3}})\b",
        rf"{context}[^\n.]{{0,70}}?\b(?:at least|minimum of|above|"
        rf"greater than)\s*(\d{{3}})\b",
        r"\bscore\s+of\s+(\d{3})\s+(?:or above|and above|and higher)\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        values = [int(v) for v in m.groups() if v]
        if all(300 <= v <= 900 for v in values):
            if len(values) == 2:
                return {
                    "minimum": min(values),
                    "maximum": max(values),
                    "basis": "stated_range",
                }
            return {
                "minimum": values[0],
                "maximum": None,
                "basis": "minimum_stated",
            }
    return {"minimum": None, "maximum": None, "basis": "not_found"}


# ── work experience ────────────────────────────────────────────────

def extract_experience(text):
    text = normalize(text)
    total = current = None
    m = re.search(
        r"(\d+)\s+years?\s+of\s+total\s+work\s+experience",
        text, re.IGNORECASE,
    )
    if m:
        total = int(m.group(1))
    m = re.search(
        r"(?:at\s+least\s+)?(\d+)\s+years?\s+in\s+the\s+current\s+"
        r"(?:organisation|organization|employer|company)",
        text, re.IGNORECASE,
    )
    if m:
        current = int(m.group(1))
    return {"total_years": total, "current_employer_years": current}


# ── interest rates ─────────────────────────────────────────────────

def extract_interest_rates(*texts):
    text = normalize("\n".join(t for t in texts if t))
    range_patterns = [
        r"(?:rate\s+of\s+interest|interest\s+rates?)\s*:?\s*"
        r"(?:starting\s+)?(?:from\s+)?(\d+(?:\.\d{1,2})?)\s*%"
        r"\s*(?:p\.?a\.?)?\s*(?:to|[-–—])\s*(\d+(?:\.\d{1,2})?)\s*%",
        r"(?:interest\s+rates?|rate\s+of\s+interest)[^\n%]{0,100}?"
        r"(\d+(?:\.\d{1,2})?)\s*%\s*(?:to|[-–—])\s*(\d+(?:\.\d{1,2})?)\s*%",
    ]
    for pattern in range_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            low, high = float(m.group(1)), float(m.group(2))
            if 0 < low <= 100 and 0 < high <= 100:
                return {
                    "minimum": min(low, high),
                    "maximum": max(low, high),
                    "basis": "stated_range",
                }
    start_patterns = [
        r"(?:interest\s+rate|rate\s+of\s+interest|interest\s+rates?)"
        r"[^\n%]{0,100}?(?:starting\s+at|starts?\s+at|starting\s+from|"
        r"from|as\s+low\s+as)\s*(\d+(?:\.\d{1,2})?)\s*%",
        r"interest\s+rate\s+starting\s+at\s*(\d+(?:\.\d{1,2})?)\s*%",
        r"starting\s+at\s*(\d+(?:\.\d{1,2})?)\s*%\s*p\.?a\.?",
        r"start\s+from\s*(\d+(?:\.\d{1,2})?)\s*%\s*p\.?a\.?",
    ]
    for pattern in start_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            value = float(m.group(1))
            if 0 < value <= 100:
                return {
                    "minimum": value,
                    "maximum": None,
                    "basis": "starting_rate_only",
                }
    return {"minimum": None, "maximum": None, "basis": "not_found"}


# ── processing fee ─────────────────────────────────────────────────

def extract_processing_fee(*texts):
    text = normalize("\n".join(t for t in texts if t))
    if not text:
        return None

    pct = re.search(
        r"(?:loan\s+)?processing\s+(?:fee|charges?)\s*:?\s*"
        r"(?:up\s+to\s+)?(\d+(?:\.\d+)?)\s*%"
        r"(?:\s+of\s+(?:the\s+)?loan\s+amount)?",
        text, re.IGNORECASE,
    )
    if pct:
        tail = text[pct.start():pct.start() + 500]
        min_match = re.search(
            r"\bminimum\s*:?\s*(?:₹|Rs\.?\s*)?(\d[\d,]*)", tail, re.IGNORECASE
        )
        max_match = re.search(
            r"\bmaximum\s*:?\s*(?:₹|Rs\.?\s*)?(\d[\d,]*)", tail, re.IGNORECASE
        )
        qualifier = (
            "up_to"
            if re.search(
                r"(?:loan\s+)?processing\s+(?:fee|charges?)\s*:?\s*up\s+to",
                text, re.IGNORECASE,
            )
            else "stated_rate"
        )
        return {
            "fee_type": "percentage_of_loan_amount",
            "percentage": float(pct.group(1)),
            "currency": "INR",
            "minimum_amount": (
                int(min_match.group(1).replace(",", ""))
                if min_match else None
            ),
            "maximum_amount": (
                int(max_match.group(1).replace(",", ""))
                if max_match else None
            ),
            "qualifier": qualifier,
            "tax_note": (
                "GST mentioned; verify applicability"
                if re.search(r"\bGST\b", tail, re.IGNORECASE)
                else None
            ),
        }

    fixed = re.search(
        r"(?:loan\s+)?processing\s+(?:fee|charges?)\s*:?\s*"
        r"(?:up\s+to\s+)?(?:₹|Rs\.?\s*)?"
        r"([\d,]+(?:\.\d+)?)",
        text, re.IGNORECASE,
    )
    if fixed:
        tail = text[fixed.start():fixed.start() + 250]
        return {
            "fee_type": "fixed_amount",
            "amount": float(fixed.group(1).replace(",", "")),
            "currency": "INR",
            "qualifier": (
                "up_to"
                if re.search(
                    r"(?:loan\s+)?processing\s+(?:fee|charges?)\s*:?\s*up\s+to",
                    tail, re.IGNORECASE,
                )
                else "stated_amount"
            ),
            "tax_note": (
                "GST mentioned; verify applicability"
                if re.search(r"\bGST\b", tail, re.IGNORECASE)
                else None
            ),
        }

    return None


# ── repayment tenure ───────────────────────────────────────────────

def extract_repayment_months(*texts):
    text = normalize("\n".join(t for t in texts if t))
    for line in text.splitlines():
        if not re.search(r"tenure|repayment|loan period", line, re.IGNORECASE):
            continue
        values = [
            int(v) for v in re.findall(r"(\d{1,3})\s*months?\b", line, re.IGNORECASE)
        ]
        values += [
            int(v) * 12
            for v in re.findall(r"(\d{1,2})\s*years?\b", line, re.IGNORECASE)
        ]
        if len(values) >= 2:
            return {"minimum": min(values), "maximum": max(values)}

    m = re.search(
        r"(?:repayment\s+period|repayment\s+tenure|loan\s+tenure|"
        r"loan\s+period)\s*:?\s*(.{0,220})",
        text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        block = m.group(1)
        min_match = re.search(
            r"\bminimum\b\s*:?\s*(\d{1,3})\s*months?\b", block, re.IGNORECASE
        )
        max_match = re.search(
            r"\bmaximum\b\s*:?\s*(?:maximum\s*:?\s*)?(\d{1,3})\s*months?\b",
            block, re.IGNORECASE,
        )
        if not max_match:
            max_match = re.search(
                r"\bmaximum\b.{0,40}?(\d{1,3})\s*months?\b",
                block, re.IGNORECASE,
            )
        if min_match or max_match:
            return {
                "minimum": int(min_match.group(1)) if min_match else None,
                "maximum": int(max_match.group(1)) if max_match else None,
            }
    return {"minimum": None, "maximum": None}


# ── employment identification ──────────────────────────────────────

CANONICAL_EMPLOYMENT = {
    "Salaried": "salaried",
    "Self-Employed": "self_employed",
    "Business": "business",
}


def identify_employment(text):
    """Identify eligible employment types from eligibility text."""
    text = normalize(text)
    employment = []
    if re.search(r"salaried|salary", text, re.IGNORECASE):
        employment.append("salaried")
    if re.search(
        r"self[\s-]?employed|business owner|professional", text, re.IGNORECASE
    ):
        employment.append("self_employed")
    if re.search(
        r"government|public sector undertaking|\bPSU\b|defence",
        text, re.IGNORECASE,
    ):
        employment.append("government_or_public_sector")
    if re.search(
        r"private limited|limited companies|corporate sector|LLP",
        text, re.IGNORECASE,
    ):
        employment.append("private_or_corporate_sector")
    return list(dict.fromkeys(employment))


# ── source date ────────────────────────────────────────────────────

def extract_source_updated_date(text):
    text = normalize(text)
    patterns = [
        r"(?:last\s+)?updated\s+on\s*:?\s*(?:(?:Monday|Tuesday|Wednesday|"
        r"Thursday|Friday|Saturday|Sunday)\s*,?\s*)?(\d{1,2})-(\d{1,2})-(\d{4})",
        r"(?:last\s+)?updated\s+on\s*:?\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
        r"(?:last\s+)?updated\s*:?\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
    ]
    for idx, pattern in enumerate(patterns):
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        try:
            if idx == 0:
                day, month, year = map(int, m.groups())
                return datetime(year, month, day).date().isoformat()
            day, month_name, year = m.groups()
            month = datetime.strptime(month_name[:3].title(), "%b").month
            return datetime(int(year), month, int(day)).date().isoformat()
        except ValueError:
            continue
    return None


# ── qualitative rules detection ────────────────────────────────────

_QUALITATIVE_KEYWORDS = re.compile(
    r"work\s+experience|employer\s+category|employer\s+type|"
    r"residence|domicile|guarantee|guarantor|collateral|"
    r"existing\s+relationship|existing\s+customer|"
    r"co-applicant|co.applicant|repayment\s+capacity",
    re.IGNORECASE,
)


def has_qualitative_rules(eligibility_text):
    """True when eligibility text has conditions that structured columns can't express."""
    if not eligibility_text:
        return False
    return bool(_QUALITATIVE_KEYWORDS.search(eligibility_text))


# ── flat min_monthly_income derivation ─────────────────────────────

def derive_flat_min_income(income_rules):
    """Return the lowest threshold across all categories, or None."""
    if not income_rules:
        return None
    values = [
        r["minimum_monthly_income"]
        for r in income_rules
        if isinstance(r, dict) and r.get("minimum_monthly_income") is not None
    ]
    return min(values) if values else None
