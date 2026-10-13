"""
internal.py – Internal API routes (never exposed directly to the outside host).

POST /internal/crawl – Trigger crawler, secured by X-Internal-Token header.
Returns {products: [...], stats: {...}}.
Called by n8n Workflow A. Does NOT write to DB directly; n8n handles persistence.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, status

from app.config import settings
from app.crawler.crawl import run_crawler

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/crawl")
async def trigger_crawl(
    x_internal_token: str = Header(None, alias="X-Internal-Token"),
) -> Dict[str, Any]:
    """
    Execute bank loan crawler run.
    Requires matching X-Internal-Token header.
    """
    if not x_internal_token or x_internal_token != settings.internal_token:
        logger.warning("Unauthorized access to /internal/crawl with token: %s", x_internal_token)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Invalid or missing X-Internal-Token header",
        )

    logger.info("Internal crawl triggered via n8n")
    try:
        result = await run_crawler()
        return result
    except Exception as e:
        logger.error("Error executing crawl: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Crawl execution failed: {str(e)}",
        )
