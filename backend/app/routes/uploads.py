"""
uploads.py – FastAPI routes for batch creation and CSV upload.

POST /api/uploads       → create batch, return {batch_id, upload_url}
PUT  /api/uploads/{id}  → stream raw CSV body to uploads volume,
                          then kick off ingestion as a background task.
"""

import logging
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import BaseModel

from app.config import settings
from app.db import get_db
from app.ingestion.core import run_ingestion

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/uploads", tags=["uploads"])


class CreateUploadRequest(BaseModel):
    filename: str


class CreateUploadResponse(BaseModel):
    batch_id: str
    upload_url: str


@router.post("", response_model=CreateUploadResponse, status_code=status.HTTP_201_CREATED)
def create_upload(body: CreateUploadRequest):
    """Create a new upload batch and return the upload URL."""
    if not body.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")

    batch_id = str(uuid.uuid4())

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO upload_batches (batch_id, filename, status)
                VALUES (%s, %s, 'created')
                """,
                (batch_id, body.filename),
            )

    upload_url = f"/api/uploads/{batch_id}"
    logger.info("Created batch %s for file '%s'", batch_id, body.filename)
    return CreateUploadResponse(batch_id=batch_id, upload_url=upload_url)


@router.put("/{batch_id}")
async def upload_file(batch_id: str, request: Request, background_tasks: BackgroundTasks):
    """
    Stream the raw CSV body to the uploads volume, then start ingestion
    as a background task so the client is not blocked.
    """
    # Verify batch exists and is in 'created' state
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, filename FROM upload_batches WHERE batch_id = %s",
                (batch_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Batch not found")

    batch_status, filename = row
    if batch_status not in ("created", "uploading"):
        raise HTTPException(
            status_code=409,
            detail=f"Batch is already in state '{batch_status}', cannot upload again",
        )

    # Set status to uploading
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE upload_batches SET status = 'uploading' WHERE batch_id = %s",
                (batch_id,),
            )

    # Stream the request body to a file on disk (never load entirely into memory)
    upload_dir = settings.upload_dir
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{batch_id}.csv")

    try:
        with open(file_path, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
    except Exception as e:
        logger.exception("Failed to write uploaded file for batch %s", batch_id)
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE upload_batches SET status = 'failed', error_message = %s WHERE batch_id = %s",
                    (f"Upload write failed: {e}", batch_id),
                )
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")

    # Update storage_ref
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE upload_batches SET storage_ref = %s WHERE batch_id = %s",
                (file_path, batch_id),
            )

    # Kick off ingestion in background
    background_tasks.add_task(run_ingestion, batch_id, file_path)
    logger.info("Upload complete for batch %s, ingestion queued", batch_id)

    return {"batch_id": batch_id, "status": "uploading", "message": "File received, ingestion started"}
