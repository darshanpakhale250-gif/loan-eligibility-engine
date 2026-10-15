"""
s3.py – S3 presigned URL generation and filename sanitization helper.
Shared by FastAPI backend and AWS Lambda handlers.
"""

import os
import re
import boto3
from botocore.config import Config


def sanitize_filename(filename: str) -> str:
    """
    Sanitize uploaded filename:
    1. Extract base name to avoid path traversal.
    2. Replace any character outside [A-Za-z0-9._-] with '_'.
    3. Ensure it ends with '.csv' (case-insensitive).
    """
    if not filename:
        raise ValueError("Filename cannot be empty")

    base = os.path.basename(filename)
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", base)

    if not sanitized.lower().endswith(".csv"):
        raise ValueError("Filename must end with .csv")

    return sanitized


def generate_presigned_put_url(
    bucket_name: str,
    s3_key: str,
    region_name: str = "ap-south-1",
    expires_in: int = 900,
) -> str:
    """
    Generate an S3 presigned PUT URL using SigV4 and regional endpoint.
    Do NOT include ContentType in Params so that browser PUT does not fail with 403
    if the browser sends different content types (e.g. application/vnd.ms-excel).
    """
    s3_client = boto3.client(
        "s3",
        region_name=region_name,
        endpoint_url=f"https://s3.{region_name}.amazonaws.com",
        config=Config(signature_version="s3v4"),
    )

    url = s3_client.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": bucket_name,
            "Key": s3_key,
        },
        ExpiresIn=expires_in,
    )
    return url
