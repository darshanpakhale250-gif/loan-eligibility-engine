"""
core.py – Ingestion orchestrator.

Reads CSV → validates each row → upserts users → writes rejections →
updates batch counters → sets status to 'processed' →
POSTs webhook to n8n Workflow B with retry.

Shared by the local FastAPI route and the Lambda handler.
"""

import logging
import time

import httpx

from app.ingestion.csv_reader import stream_csv
from app.ingestion.validation import validate_row
from app.ingestion.loader import (
    upsert_users,
    insert_rejections,
    update_batch_counters,
    update_batch_status,
)
from app.db import get_db
from app.config import settings

logger = logging.getLogger(__name__)


def run_ingestion(batch_id: str, file_path: str):
    """
    Full ingestion pipeline for a single batch.

    1. Stream-parse CSV
    2. Validate each row
    3. Upsert valid rows, record rejections
    4. Update batch counters and status → 'processed'
    5. POST webhook to n8n Workflow B
    """
    valid_rows = []
    rejections = []
    rows_total = 0

    try:
        with get_db() as conn:
            update_batch_status(conn, batch_id, "processing")

        # ── 1 & 2: Stream + validate ────────────────────────────────
        for row_number, row in stream_csv(file_path):
            rows_total += 1
            cleaned, reason = validate_row(row)
            if cleaned is not None:
                valid_rows.append(cleaned)
            else:
                rejections.append({
                    "row_number": row_number,
                    "reason": reason,
                    "raw_row": row,
                })

        logger.info(
            "Batch %s: parsed %d rows, %d valid, %d rejected",
            batch_id, rows_total, len(valid_rows), len(rejections),
        )

        # ── 3: Write to DB ──────────────────────────────────────────
        with get_db() as conn:
            upsert_users(conn, batch_id, valid_rows)
            insert_rejections(conn, batch_id, rejections)

        # ── 4: Update counters and status ───────────────────────────
        with get_db() as conn:
            update_batch_counters(conn, batch_id, rows_total, len(valid_rows), len(rejections))
            update_batch_status(conn, batch_id, "processed")

        # ── 5: Trigger n8n Workflow B ───────────────────────────────
        _trigger_workflow_b(batch_id)

    except Exception as e:
        logger.exception("Ingestion failed for batch %s", batch_id)
        try:
            with get_db() as conn:
                update_batch_status(conn, batch_id, "failed", str(e))
        except Exception:
            logger.exception("Failed to update batch status after error")


def _trigger_workflow_b(batch_id: str):
    """
    POST to n8n Workflow B webhook with retry (3 attempts, exponential backoff).
    On success, sets batch status to 'matching'.
    On failure, sets batch status to 'failed' with error message.
    """
    webhook_url = f"{settings.n8n_webhook_base_internal}/loan-match"
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Secret": settings.webhook_secret,
    }
    payload = {"batch_id": batch_id}

    last_error = None
    for attempt in range(1, 4):
        try:
            resp = httpx.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=30.0,
            )
            if resp.status_code in (200, 201, 202):
                logger.info(
                    "Triggered Workflow B for batch %s (attempt %d, status %d)",
                    batch_id, attempt, resp.status_code,
                )
                with get_db() as conn:
                    update_batch_status(conn, batch_id, "matching")
                return
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.warning(
                    "Workflow B webhook returned %d for batch %s (attempt %d)",
                    resp.status_code, batch_id, attempt,
                )
        except Exception as e:
            last_error = str(e)
            logger.warning(
                "Workflow B webhook failed for batch %s (attempt %d): %s",
                batch_id, attempt, e,
            )

        if attempt < 3:
            backoff = 2 ** attempt
            logger.info("Retrying in %ds...", backoff)
            time.sleep(backoff)

    # All retries exhausted
    error_msg = f"Failed to trigger Workflow B after 3 attempts: {last_error}"
    logger.error(error_msg)
    with get_db() as conn:
        update_batch_status(conn, batch_id, "failed", error_msg)
