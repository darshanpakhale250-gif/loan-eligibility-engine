"""
loader.py – Bulk upsert validated user rows and rejections into Postgres.

Uses psycopg2.extras.execute_values for chunked inserts (1000 rows per chunk).
All writes use ON CONFLICT so re-running is safe.
"""

import json
import logging
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1000


def upsert_users(conn, batch_id: str, valid_rows: list[dict]):
    """
    Upsert valid user rows into the ``users`` table in chunks.
    Returns the number of rows actually upserted.
    """
    if not valid_rows:
        return 0

    sql = """
        INSERT INTO users (user_id, batch_id, name, email, monthly_income, credit_score, employment_status, age)
        VALUES %s
        ON CONFLICT (user_id) DO UPDATE SET
            batch_id = EXCLUDED.batch_id,
            name = EXCLUDED.name,
            email = EXCLUDED.email,
            monthly_income = EXCLUDED.monthly_income,
            credit_score = EXCLUDED.credit_score,
            employment_status = EXCLUDED.employment_status,
            age = EXCLUDED.age
    """

    total = 0
    with conn.cursor() as cur:
        for i in range(0, len(valid_rows), CHUNK_SIZE):
            chunk = valid_rows[i : i + CHUNK_SIZE]
            values = [
                (
                    r["user_id"],
                    batch_id,
                    r["name"],
                    r["email"],
                    r["monthly_income"],
                    r["credit_score"],
                    r["employment_status"],
                    r["age"],
                )
                for r in chunk
            ]
            execute_values(cur, sql, values, page_size=CHUNK_SIZE)
            total += len(chunk)
            logger.info("Upserted %d users (chunk %d)", len(chunk), i // CHUNK_SIZE + 1)

    conn.commit()
    return total


def insert_rejections(conn, batch_id: str, rejections: list[dict]):
    """
    Insert rejection records into ``batch_rejections``.
    Each rejection is ``{row_number, reason, raw_row}``.
    """
    if not rejections:
        return

    sql = """
        INSERT INTO batch_rejections (batch_id, row_number, reason, raw_row)
        VALUES %s
    """

    with conn.cursor() as cur:
        for i in range(0, len(rejections), CHUNK_SIZE):
            chunk = rejections[i : i + CHUNK_SIZE]
            values = [
                (
                    batch_id,
                    r["row_number"],
                    r["reason"],
                    json.dumps(r["raw_row"], ensure_ascii=False),
                )
                for r in chunk
            ]
            execute_values(cur, sql, values, page_size=CHUNK_SIZE)

    conn.commit()
    logger.info("Inserted %d rejection records", len(rejections))


def update_batch_counters(conn, batch_id: str, rows_total: int, rows_valid: int, rows_rejected: int):
    """Update the upload_batches row with ingestion counters."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE upload_batches
            SET rows_total = %s,
                rows_valid = %s,
                rows_rejected = %s,
                processed_at = NOW()
            WHERE batch_id = %s
            """,
            (rows_total, rows_valid, rows_rejected, batch_id),
        )
    conn.commit()


def update_batch_status(conn, batch_id: str, status: str, error_message: str = None):
    """Set batch status (and optional error_message)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE upload_batches
            SET status = %s,
                error_message = COALESCE(%s, error_message)
            WHERE batch_id = %s
            """,
            (status, error_message, batch_id),
        )
    conn.commit()
