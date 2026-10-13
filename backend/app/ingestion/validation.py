"""
validation.py – Per-row validation and employment canonicalisation.

Ranges are derived from profiling the actual users_sample.csv:
  - age:            18 – 100
  - credit_score:   300 – 900
  - monthly_income: > 0
  - email:          must contain @ and .
  - employment_status: must map to a canonical value
"""

import logging
import re

logger = logging.getLogger(__name__)

# Canonical employment status values.
# These MUST match the values stored in loan_products.eligible_employment
# and the seed data in 02_seed_products.sql.
EMPLOYMENT_CANONICAL_MAP = {
    # CSV values (case-insensitive key) -> canonical DB value
    "salaried":       "Salaried",
    "self-employed":  "Self-Employed",
    "self employed":  "Self-Employed",
    "selfemployed":   "Self-Employed",
    "business":       "Business",
    "business owner": "Business",
    "entrepreneur":   "Business",
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_row(row: dict) -> tuple[dict | None, str | None]:
    """
    Validate a single CSV row dict.

    Returns ``(cleaned_row, None)`` on success, or ``(None, reason)`` on failure.
    ``cleaned_row`` has numeric fields parsed and employment canonicalised.
    """
    errors = []

    # ── user_id ──────────────────────────────────────────────────────
    user_id = (row.get("user_id") or "").strip()
    if not user_id:
        errors.append("missing user_id")

    # ── email ────────────────────────────────────────────────────────
    email = (row.get("email") or "").strip()
    if not email or not _EMAIL_RE.match(email):
        errors.append(f"invalid email: '{email}'")

    # ── name (optional but stored) ───────────────────────────────────
    name = (row.get("name") or "").strip() or None

    # ── monthly_income ───────────────────────────────────────────────
    try:
        monthly_income = float((row.get("monthly_income") or "").replace(",", ""))
        if monthly_income <= 0:
            errors.append(f"monthly_income must be > 0, got {monthly_income}")
    except (ValueError, TypeError):
        errors.append(f"non-numeric monthly_income: '{row.get('monthly_income')}'")
        monthly_income = None

    # ── credit_score ─────────────────────────────────────────────────
    try:
        credit_score = int(float((row.get("credit_score") or "").replace(",", "")))
        if not (300 <= credit_score <= 900):
            errors.append(f"credit_score out of range 300-900: {credit_score}")
    except (ValueError, TypeError):
        errors.append(f"non-numeric credit_score: '{row.get('credit_score')}'")
        credit_score = None

    # ── age ───────────────────────────────────────────────────────────
    try:
        age = int(float((row.get("age") or "").replace(",", "")))
        if not (18 <= age <= 100):
            errors.append(f"age out of range 18-100: {age}")
    except (ValueError, TypeError):
        errors.append(f"non-numeric age: '{row.get('age')}'")
        age = None

    # ── employment_status ────────────────────────────────────────────
    raw_employment = (row.get("employment_status") or "").strip()
    if not raw_employment:
        errors.append("empty employment_status")
        canonical_employment = None
    else:
        key = raw_employment.lower().strip()
        canonical_employment = EMPLOYMENT_CANONICAL_MAP.get(key)
        if canonical_employment is None:
            errors.append(f"unrecognised employment_status: '{raw_employment}'")

    if errors:
        return None, "; ".join(errors)

    return {
        "user_id": user_id,
        "name": name,
        "email": email,
        "monthly_income": monthly_income,
        "credit_score": credit_score,
        "employment_status": canonical_employment,
        "age": age,
    }, None
