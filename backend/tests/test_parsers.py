"""
test_parsers.py – Unit tests for crawler regex extractors and page normalizer.
Compatible with standard unittest and pytest.
"""

import unittest
from app.crawler.parsers import (
    derive_flat_min_income,
    extract_age_range,
    extract_credit_score,
    extract_interest_rates,
    extract_loan_amount,
    has_qualitative_rules,
    identify_bank,
    identify_employment,
    normalize,
)
from app.crawler.normalize import normalize_crawled_page


class TestParsers(unittest.TestCase):

    def test_text_normalization(self):
        raw = "Rate of interest: 10.5% &nbsp; â‚¹ 50,000"
        cleaned = normalize(raw)
        self.assertIn("₹", cleaned)
        self.assertNotIn("&nbsp;", cleaned)

    def test_identify_bank(self):
        url_sbi = "https://sbi.co.in/personal-loans/xpress-credit"
        self.assertEqual(identify_bank({}, url_sbi), "State Bank of India")

        url_hdfc = "https://www.hdfcbank.com/personal-loan"
        self.assertEqual(identify_bank({}, url_hdfc), "HDFC Bank")

        url_icici = "https://www.icicibank.com/personal-banking/loans/personal-loan"
        self.assertEqual(identify_bank({}, url_icici), "ICICI Bank")

    def test_extract_interest_rates(self):
        text = "Enjoy competitive interest rates starting from 10.25% to 14.50% p.a."
        rates = extract_interest_rates(text)
        self.assertEqual(rates["minimum"], 10.25)
        self.assertEqual(rates["maximum"], 14.50)

    def test_extract_loan_amount(self):
        text = "Get personal loan amount from Rs. 50,000 to Rs. 40,00,000 for all your needs."
        amount = extract_loan_amount(text)
        self.assertEqual(amount["minimum"], 50000)
        self.assertEqual(amount["maximum"], 4000000)

    def test_extract_age_range(self):
        text = "Applicant age must be between 21 and 60 years at the time of loan application."
        age = extract_age_range(text)
        self.assertEqual(age["minimum"], 21)
        self.assertEqual(age["maximum"], 60)

    def test_extract_credit_score(self):
        text = "Applicants with a minimum CIBIL score of 750 are eligible."
        score = extract_credit_score(text)
        self.assertEqual(score["minimum"], 750)

    def test_has_qualitative_rules(self):
        self.assertTrue(has_qualitative_rules("Requires at least 2 years work experience in current company"))
        self.assertFalse(has_qualitative_rules("Rate 10.5% with zero processing fee"))

    def test_derive_flat_min_income(self):
        rules = [
            {"employment_category": "government_defence", "minimum_monthly_income": 25000},
            {"employment_category": "corporate", "minimum_monthly_income": 35000},
        ]
        self.assertEqual(derive_flat_min_income(rules), 25000)
        self.assertIsNone(derive_flat_min_income([]))

    def test_normalize_crawled_page_full(self):
        page_data = {
            "url": "https://sbi.bank.in/web/personal-banking/loans/personal-loans/sbi-personal-loan",
            "title": "SBI Personal Loan Scheme | State Bank of India",
            "text": """
            State Bank of India offers personal loans.
            Rate of interest starting from 11.15% to 14.30% p.a.
            Loan amount from Rs. 25,000 to Rs. 20,00,000.
            Age of applicant: 21 to 58 years.
            Minimum CIBIL score of 650.
            Minimum monthly salary of Rs 25,000 for salaried employees.
            Requires at least 1 year work experience.
            """
        }
        product = normalize_crawled_page(page_data)
        self.assertIsNotNone(product)
        self.assertEqual(product["lender_name"], "State Bank of India")
        self.assertEqual(product["interest_rate_min"], 11.15)
        self.assertEqual(product["interest_rate_max"], 14.30)
        self.assertEqual(product["loan_amount_min"], 25000)
        self.assertEqual(product["loan_amount_max"], 2000000)
        self.assertEqual(product["age_min"], 21)
        self.assertEqual(product["age_max"], 58)
        self.assertEqual(product["min_credit_score"], 650)
        self.assertIn("Salaried", product["eligible_employment"])
        self.assertTrue(product["has_qualitative_rules"])


if __name__ == "__main__":
    unittest.main()
