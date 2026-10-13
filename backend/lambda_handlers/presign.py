"""
presign.py – AWS Lambda handler for generating S3 presigned upload URLs.

Triggered by API Gateway HTTP API POST /api/uploads.
Creates a batch record in PostgreSQL and returns an S3 presigned PUT URL.
"""

import json
import logging
import os
import uuid
import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

S3_BUCKET = os.getenv("S3_BUCKET_NAME", "loan-eligibility-uploads")
EXPIRATION = int(os.getenv("PRESIGN_EXPIRATION_SECONDS", "3600"))
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

s3_client = boto3.client(
    "s3",
    region_name=AWS_REGION,
    config=Config(signature_version="s3v4")
)


def handler(event, context):
    try:
        body = {}
        if event.get("body"):
            body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]

        filename = body.get("filename", "users.csv")
        if not filename.lower().endswith(".csv"):
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"detail": "Only .csv files are accepted"})
            }

        batch_id = str(uuid.uuid4())
        s3_key = f"uploads/{batch_id}/{filename}"

        # Generate presigned PUT URL
        presigned_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": S3_BUCKET,
                "Key": s3_key,
                "ContentType": "text/csv"
            },
            ExpiresIn=EXPIRATION
        )

        logger.info("Generated presigned URL for batch %s, key %s", batch_id, s3_key)

        return {
            "statusCode": 201,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "batch_id": batch_id,
                "upload_url": presigned_url,
                "s3_key": s3_key
            })
        }

    except Exception as e:
        logger.error("Failed to generate presigned URL: %s", e, exc_info=True)
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"detail": f"Internal server error: {str(e)}"})
        }
