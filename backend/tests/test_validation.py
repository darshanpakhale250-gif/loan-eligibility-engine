"""
test_validation.py – Unit tests for CSV ingestion row validation.
Compatible with standard unittest and pytest.
"""

import unittest
from app.ingestion.validation import validate_row, EMPLOYMENT_CANONICAL_MAP


class TestValidation(unittest.TestCase):

    def test_valid_row_passes(self):
        row = {
            "user_id": "u-12345",
            "name": "Aarav Sharma",
            "email": "aarav.sharma@example.com",
            "monthly_income": "75000",
            "credit_score": "750",
            "employment_status": "Salaried",
            "age": "28"
        }
        cleaned, err = validate_row(row)
        self.assertIsNone(err)
        self.assertIsNotNone(cleaned)
        self.assertEqual(cleaned["user_id"], "u-12345")
        self.assertEqual(cleaned["monthly_income"], 75000.0)
        self.assertEqual(cleaned["credit_score"], 750)
        self.assertEqual(cleaned["employment_status"], "Salaried")
        self.assertEqual(cleaned["age"], 28)

    def test_invalid_email_fails(self):
        row = {
            "user_id": "u-12345",
            "email": "invalid-email-format",
            "monthly_income": "50000",
            "credit_score": "700",
            "employment_status": "Salaried",
            "age": "30"
        }
        cleaned, err = validate_row(row)
        self.assertIsNone(cleaned)
        self.assertIn("invalid email", err)

    def test_credit_score_range_fails(self):
        # Below 300
        row_low = {
            "user_id": "u-low",
            "email": "test@example.com",
            "monthly_income": "50000",
            "credit_score": "250",
            "employment_status": "Salaried",
            "age": "30"
        }
        cleaned, err = validate_row(row_low)
        self.assertIsNone(cleaned)
        self.assertIn("credit_score out of range 300-900", err)

        # Above 900
        row_high = {
            "user_id": "u-high",
            "email": "test@example.com",
            "monthly_income": "50000",
            "credit_score": "950",
            "employment_status": "Salaried",
            "age": "30"
        }
        cleaned, err = validate_row(row_high)
        self.assertIsNone(cleaned)
        self.assertIn("credit_score out of range 300-900", err)

    def test_age_range_fails(self):
        # Age < 18
        row_young = {
            "user_id": "u-young",
            "email": "test@example.com",
            "monthly_income": "50000",
            "credit_score": "700",
            "employment_status": "Salaried",
            "age": "16"
        }
        cleaned, err = validate_row(row_young)
        self.assertIsNone(cleaned)
        self.assertIn("age out of range 18-100", err)

    def test_employment_status_canonicalization(self):
        variations = [
            ("salaried", "Salaried"),
            ("Salaried", "Salaried"),
            ("self-employed", "Self-Employed"),
            ("self employed", "Self-Employed"),
            ("business", "Business"),
            ("business owner", "Business"),
        ]
        for raw, expected in variations:
            row = {
                "user_id": f"u-{raw}",
                "email": "test@example.com",
                "monthly_income": "50000",
                "credit_score": "700",
                "employment_status": raw,
                "age": "30"
            }
            cleaned, err = validate_row(row)
            self.assertIsNone(err)
            self.assertEqual(cleaned["employment_status"], expected)

    def test_missing_user_id_fails(self):
        row = {
            "user_id": "",
            "email": "test@example.com",
            "monthly_income": "50000",
            "credit_score": "700",
            "employment_status": "Salaried",
            "age": "30"
        }
        cleaned, err = validate_row(row)
        self.assertIsNone(cleaned)
        self.assertIn("missing user_id", err)


if __name__ == "__main__":
    unittest.main()
