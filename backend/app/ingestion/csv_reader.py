"""
csv_reader.py – Stream-parse a CSV file from disk.

Handles UTF-8 BOM, normalizes header casing and whitespace,
and yields rows as dicts one at a time.
"""

import csv
import io
import logging

logger = logging.getLogger(__name__)

EXPECTED_COLUMNS = {"user_id", "name", "email", "monthly_income", "credit_score", "employment_status", "age"}


def stream_csv(file_path: str):
    """
    Open *file_path* and yield one dict per data row.

    - Strips the UTF-8 BOM if present.
    - Normalises header names: lowercase, strip whitespace.
    - Yields ``(row_number, row_dict)`` tuples (1-indexed, header row excluded).
    """
    with open(file_path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)

        # Normalise headers
        if reader.fieldnames is None:
            raise ValueError("CSV file is empty or has no header row")

        reader.fieldnames = [col.strip().lower().replace(" ", "_") for col in reader.fieldnames]

        missing = EXPECTED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")

        for row_number, row in enumerate(reader, start=1):
            # Strip whitespace from every cell value
            cleaned = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
            yield row_number, cleaned
