"""
process_csv.py – AWS Lambda handler for S3 ObjectCreated event.

Downloads uploaded CSV file from S3 and calls the core ingestion pipeline
(app.ingestion.core.run_ingestion), which streams the CSV, validates rows,
bulk-upserts into PostgreSQL, and triggers the n8n matching webhook.
"""

import logging
import os
import urllib.parse
import boto3

from app.ingestion.core import run_ingestion

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")


def handler(event, context):
    try:
        # Extract S3 bucket and object key from event records
        records = event.get("Records", [])
        if not records:
            logger.warning("No records found in S3 event")
            return {"status": "skipped", "reason": "no records"}

        for record in records:
            bucket = record["s3"]["bucket"]["name"]
            key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

            # Expecting key format: uploads/{batch_id}/{filename}
            parts = key.split("/")
            if len(parts) >= 3 and parts[0] == "uploads":
                batch_id = parts[1]
                filename = parts[2]
            else:
                batch_id = os.path.basename(key).replace(".csv", "")
                filename = os.path.basename(key)

            download_path = f"/tmp/{batch_id}_{filename}"
            logger.info("Downloading s3://%s/%s to %s", bucket, key, download_path)
            s3_client.download_file(bucket, key, download_path)

            try:
                # Run the shared core ingestion orchestrator
                logger.info("Executing core ingestion for batch %s", batch_id)
                run_ingestion(batch_id, download_path)
            finally:
                if os.path.exists(download_path):
                    os.remove(download_path)

        return {"status": "success", "processed_records": len(records)}

    except Exception as e:
        logger.error("Error processing S3 CSV event: %s", e, exc_info=True)
        raise e
