"""
presign.py – AWS Lambda handler for generating S3 presigned upload URLs.

Triggered by API Gateway HTTP API POST /api/uploads.
Creates a batch record in PostgreSQL and returns an S3 presigned PUT URL.
"""

import json
import logging
import os
import uuid

from app.db import get_db
from app.s3 import sanitize_filename, generate_presigned_put_url

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

S3_BUCKET = os.getenv("S3_BUCKET_NAME", "loan-eligibility-uploads")
EXPIRATION = int(os.getenv("PRESIGN_EXPIRATION_SECONDS", "900"))
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")


def handler(event, context):
    try:
        body = {}
        if event.get("body"):
            body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]

        raw_filename = body.get("filename", "users.csv")
        try:
            sanitized_filename = sanitize_filename(raw_filename)
        except ValueError as e:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({"detail": str(e)}),
            }

        batch_id = str(uuid.uuid4())
        s3_key = f"uploads/{batch_id}/{sanitized_filename}"

        # Insert batch record into PostgreSQL
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO upload_batches (batch_id, filename, status)
                    VALUES (%s, %s, 'created')
                    """,
                    (batch_id, sanitized_filename),
                )

        # Generate presigned PUT URL using shared helper (SigV4, no ContentType restriction)
        presigned_url = generate_presigned_put_url(
            bucket_name=S3_BUCKET,
            s3_key=s3_key,
            region_name=AWS_REGION,
            expires_in=EXPIRATION,
        )

        logger.info("Generated presigned URL for batch %s, key %s", batch_id, s3_key)

        return {
            "statusCode": 201,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({
                "batch_id": batch_id,
                "upload_url": presigned_url,
                "s3_key": s3_key,
            }),
        }

    except Exception as e:
        logger.error("Failed to generate presigned URL: %s", e, exc_info=True)
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"detail": f"Internal server error: {str(e)}"}),
        }
