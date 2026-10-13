"""
normalize.py – Normalizes extracted crawl output into the loan_products schema shape.

Transforms raw text and metadata extracted from bank pages into clean dictionaries
matching database/01_schema.sql loan_products columns:
  - lender_name, product_name, source_url
  - interest_rate_min, interest_rate_max, interest_rate_basis
  - loan_amount_min, loan_amount_max
  - age_min, age_max
  - min_credit_score, max_credit_score
  - eligible_employment (canonical list: ['Salaried', 'Self-Employed', 'Business'])
  - min_monthly_income_rules (jsonb dict)
  - processing_fee (jsonb dict)
  - eligibility_criteria (clean text)
  - raw_criteria (jsonb dict)
  - min_monthly_income (flat numeric derived from rules)
  - has_qualitative_rules (boolean)
  - source ('crawl')
  - is_active (True)
"""

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.crawler.parsers import (
    derive_flat_min_income,
    extract_age_range,
    extract_credit_score,
    extract_income,
    extract_interest_rates,
    extract_loan_amount,
    extract_processing_fee,
    has_qualitative_rules,
    identify_bank,
    identify_employment,
    normalize as clean_text,
)

logger = logging.getLogger(__name__)

# Map raw parser employment tokens to database canonical values
EMPLOYMENT_MAP = {
    "salaried": "Salaried",
    "self_employed": "Self-Employed",
    "government_or_public_sector": "Salaried",
    "private_or_corporate_sector": "Salaried",
    "business": "Business",
}


def normalize_crawled_page(
    page_data: Dict[str, Any],
    site_config: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Parse and normalize a single crawled page's content into a loan_product dict.
    Returns None if the page is not an identifiable loan product.
    """
    url = clean_text(page_data.get("url") or page_data.get("source_url") or "")
    if not url:
        return None

    title = clean_text(page_data.get("title") or page_data.get("page_title") or "")
    text = clean_text(page_data.get("markdown") or page_data.get("text") or "")
    if not text:
        return None

    # 1. Bank identification
    lender_name = identify_bank(page_data, url)
    if site_config and site_config.get("display_name") and (not lender_name or lender_name == "Unknown"):
        lender_name = site_config["display_name"]
    if not lender_name or lender_name == "Unknown":
        # Fallback from domain
        hostname = (urlparse(url).hostname or "").lower()
        if "sbi" in hostname:
            lender_name = "State Bank of India"
        elif "hdfc" in hostname:
            lender_name = "HDFC Bank"
        elif "icici" in hostname:
            lender_name = "ICICI Bank"
        else:
            return None

    # 2. Product name identification
    product_name = ""
    if title:
        # Strip common site suffixes like '| SBI', '| HDFC Bank', etc.
        for sep in ("|", "-", "–", ":"):
            if sep in title:
                parts = title.split(sep)
                if any("loan" in p.lower() for p in parts):
                    for p in parts:
                        if "loan" in p.lower() and len(p.strip()) > 5:
                            product_name = p.strip()
                            break
        if not product_name:
            product_name = title

    if not product_name or len(product_name) < 5 or "loan" not in product_name.lower():
        # Derive product name from URL path
        slug = urlparse(url).path.strip("/").split("/")[-1].replace("-", " ").title()
        if "loan" in slug.lower():
            product_name = f"{lender_name} {slug}"
        else:
            product_name = f"{lender_name} Personal Loan"

    # 3. Interest Rates
    rates = extract_interest_rates(text)
    interest_rate_min = rates.get("minimum")
    interest_rate_max = rates.get("maximum")
    interest_rate_basis = rates.get("basis")

    # 4. Loan Amount
    amount = extract_loan_amount(text)
    loan_amount_min = amount.get("minimum")
    loan_amount_max = amount.get("maximum")

    # 5. Age Range
    age = extract_age_range(text)
    age_min = age.get("minimum")
    age_max = age.get("maximum")

    # 6. Credit Score
    cibil = extract_credit_score(text)
    min_credit_score = cibil.get("minimum")
    max_credit_score = cibil.get("maximum")

    # 7. Employment
    raw_employment = identify_employment(text)
    eligible_employment: List[str] = []
    for emp in raw_employment:
        canonical = EMPLOYMENT_MAP.get(emp)
        if canonical and canonical not in eligible_employment:
            eligible_employment.append(canonical)

    # If no specific employment mentioned, default to all common categories
    if not eligible_employment:
        eligible_employment = ["Salaried", "Self-Employed"]

    # 8. Income rules & flat min_monthly_income
    income_rules = extract_income(text)
    flat_income = derive_flat_min_income(income_rules)
    min_income_rules_obj = {"rules": income_rules} if income_rules else None

    # 9. Processing fee
    fee = extract_processing_fee(text)

    # 10. Qualitative rules & eligibility criteria snippet
    is_qualitative = has_qualitative_rules(text)
    eligibility_snippet = text[:1500] if len(text) > 1500 else text

    raw_criteria = {
        "extracted_income_rules": income_rules,
        "extracted_tenure": page_data.get("tenure"),
        "page_title": title,
    }

    # Minimum viability check: must have either rate, amount, or income rule
    # If all numeric indicators are missing, this might not be an actual product page
    if not any([interest_rate_min, loan_amount_min, loan_amount_max, flat_income, min_credit_score]):
        logger.warning("Dropping page %s: insufficient loan terms extracted", url)
        return None

    return {
        "lender_name": lender_name,
        "product_name": product_name,
        "source_url": url,
        "interest_rate_min": interest_rate_min,
        "interest_rate_max": interest_rate_max,
        "interest_rate_basis": interest_rate_basis,
        "loan_amount_min": loan_amount_min,
        "loan_amount_max": loan_amount_max,
        "age_min": age_min,
        "age_max": age_max,
        "min_credit_score": min_credit_score,
        "max_credit_score": max_credit_score,
        "eligible_employment": eligible_employment,
        "min_monthly_income_rules": min_income_rules_obj,
        "processing_fee": fee,
        "eligibility_criteria": eligibility_snippet,
        "raw_criteria": raw_criteria,
        "min_monthly_income": flat_income,
        "has_qualitative_rules": is_qualitative,
        "source": "crawl",
        "is_active": True,
    }
