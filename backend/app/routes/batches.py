"""
batches.py – FastAPI routes for batch status and match queries.

GET /api/batches/{batch_id}  → single batch status with counters
GET /api/batches             → recent batches list
GET /api/matches             → matches for a batch (with optional limit)
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from app.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["batches"])


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str):
    """Return full batch status including funnel counters."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT batch_id, filename, storage_ref, status,
                       rows_total, rows_valid, rows_rejected,
                       pairs_total, pairs_after_sql, pairs_after_rules,
                       pairs_sent_to_llm, pairs_matched,
                       emails_sent, error_message,
                       created_at, processed_at, completed_at
                FROM upload_batches
                WHERE batch_id = %s
                """,
                (batch_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Batch not found")

    return {
        "batch_id": str(row[0]),
        "filename": row[1],
        "storage_ref": row[2],
        "status": row[3],
        "rows_total": row[4],
        "rows_valid": row[5],
        "rows_rejected": row[6],
        "pairs_total": row[7],
        "pairs_after_sql": row[8],
        "pairs_after_rules": row[9],
        "pairs_sent_to_llm": row[10],
        "pairs_matched": row[11],
        "emails_sent": row[12],
        "error_message": row[13],
        "created_at": row[14].isoformat() if row[14] else None,
        "processed_at": row[15].isoformat() if row[15] else None,
        "completed_at": row[16].isoformat() if row[16] else None,
    }


@router.get("/batches")
def list_batches():
    """Return the 20 most recent batches."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT batch_id, filename, status,
                       rows_total, rows_valid, rows_rejected,
                       pairs_matched, emails_sent,
                       error_message, created_at
                FROM upload_batches
                ORDER BY created_at DESC
                LIMIT 20
                """
            )
            rows = cur.fetchall()

    return [
        {
            "batch_id": str(r[0]),
            "filename": r[1],
            "status": r[2],
            "rows_total": r[3],
            "rows_valid": r[4],
            "rows_rejected": r[5],
            "pairs_matched": r[6],
            "emails_sent": r[7],
            "error_message": r[8],
            "created_at": r[9].isoformat() if r[9] else None,
        }
        for r in rows
    ]


@router.get("/matches")
def list_matches(
    batch_id: str = Query(None, description="Filter matches by batch_id"),
    limit: int = Query(50, ge=1, le=500, description="Max results to return"),
):
    """Return matches, optionally filtered by batch_id."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if batch_id:
                cur.execute(
                    """
                    SELECT m.match_id, m.user_id, u.name, u.email,
                           m.product_id, lp.lender_name, lp.product_name,
                           m.stage, m.score, m.reason,
                           m.notification_status, m.created_at
                    FROM matches m
                    JOIN users u ON u.user_id = m.user_id
                    JOIN loan_products lp ON lp.id = m.product_id
                    WHERE u.batch_id = %s
                    ORDER BY m.created_at DESC
                    LIMIT %s
                    """,
                    (batch_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT m.match_id, m.user_id, u.name, u.email,
                           m.product_id, lp.lender_name, lp.product_name,
                           m.stage, m.score, m.reason,
                           m.notification_status, m.created_at
                    FROM matches m
                    JOIN users u ON u.user_id = m.user_id
                    JOIN loan_products lp ON lp.id = m.product_id
                    ORDER BY m.created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()

    return [
        {
            "match_id": str(r[0]),
            "user_id": r[1],
            "user_name": r[2],
            "user_email": r[3],
            "product_id": r[4],
            "lender_name": r[5],
            "product_name": r[6],
            "stage": r[7],
            "score": float(r[8]) if r[8] is not None else None,
            "reason": r[9],
            "notification_status": r[10],
            "created_at": r[11].isoformat() if r[11] else None,
        }
        for r in rows
    ]


@router.get("/products")
def list_products():
    """Return all active loan products."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, lender_name, product_name, source_url,
                       interest_rate_min, interest_rate_max,
                       loan_amount_min, loan_amount_max,
                       min_credit_score, source, is_active, stored_at
                FROM loan_products
                WHERE is_active = TRUE
                ORDER BY id ASC
                """
            )
            rows = cur.fetchall()

    return {
        "count": len(rows),
        "products": [
            {
                "id": r[0],
                "lender_name": r[1],
                "product_name": r[2],
                "source_url": r[3],
                "interest_rate_min": float(r[4]) if r[4] is not None else None,
                "interest_rate_max": float(r[5]) if r[5] is not None else None,
                "loan_amount_min": float(r[6]) if r[6] is not None else None,
                "loan_amount_max": float(r[7]) if r[7] is not None else None,
                "min_credit_score": r[8],
                "source": r[9],
                "is_active": r[10],
                "stored_at": r[11].isoformat() if r[11] else None,
            }
            for r in rows
        ],
    }


@router.get("/analytics")
def get_analytics():
    """Return aggregated analytics for dashboard charts & visualizations."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # 1. Funnel from latest completed batch
            cur.execute(
                """
                SELECT batch_id, filename, status, rows_total, rows_valid,
                       pairs_total, pairs_after_sql, pairs_after_rules, pairs_matched, emails_sent
                FROM upload_batches
                WHERE status = 'completed'
                ORDER BY completed_at DESC NULLS LAST
                LIMIT 1
                """
            )
            batch_row = cur.fetchone()

            # 2. Match counts by lender
            cur.execute(
                """
                SELECT lp.lender_name, COUNT(m.match_id) AS match_count
                FROM matches m
                JOIN loan_products lp ON m.product_id = lp.id
                GROUP BY lp.lender_name
                ORDER BY match_count DESC
                """
            )
            lender_stats = [{"lender": r[0], "count": r[1]} for r in cur.fetchall()]

            # 3. Credit score distribution of borrowers
            cur.execute(
                """
                SELECT 
                    CASE 
                        WHEN credit_score < 600 THEN 'Poor (<600)'
                        WHEN credit_score < 700 THEN 'Fair (600-699)'
                        WHEN credit_score < 750 THEN 'Good (700-749)'
                        WHEN credit_score < 800 THEN 'Very Good (750-799)'
                        ELSE 'Excellent (800+)'
                    END AS score_bracket,
                    COUNT(*) AS count
                FROM users
                GROUP BY 1
                ORDER BY 1
                """
            )
            credit_stats = [{"bracket": r[0], "count": r[1]} for r in cur.fetchall()]

            # 4. Income distribution of borrowers
            cur.execute(
                """
                SELECT 
                    CASE 
                        WHEN monthly_income < 30000 THEN '< ₹30k'
                        WHEN monthly_income < 60000 THEN '₹30k - ₹60k'
                        WHEN monthly_income < 100000 THEN '₹60k - ₹100k'
                        ELSE '> ₹100k'
                    END AS income_bracket,
                    COUNT(*) AS count
                FROM users
                GROUP BY 1
                ORDER BY 1
                """
            )
            income_stats = [{"bracket": r[0], "count": r[1]} for r in cur.fetchall()]

            # 5. Product summary
            cur.execute(
                """
                SELECT 
                    COUNT(*) AS total_products,
                    COUNT(*) FILTER (WHERE source = 'crawl') AS crawled_count,
                    COUNT(*) FILTER (WHERE source = 'seed') AS seed_count
                FROM loan_products
                WHERE is_active = TRUE
                """
            )
            prod_row = cur.fetchone()

            # 6. Top matched products
            cur.execute(
                """
                SELECT lp.lender_name, lp.product_name, lp.interest_rate_min, COUNT(m.match_id) AS matches
                FROM matches m
                JOIN loan_products lp ON m.product_id = lp.id
                GROUP BY lp.lender_name, lp.product_name, lp.interest_rate_min
                ORDER BY matches DESC
                LIMIT 5
                """
            )
            top_products = [
                {"lender": r[0], "product": r[1], "rate": float(r[2]) if r[2] else None, "matches": r[3]}
                for r in cur.fetchall()
            ]

    funnel = None
    if batch_row:
        funnel = {
            "batch_id": str(batch_row[0]),
            "filename": batch_row[1],
            "status": batch_row[2],
            "rows_total": batch_row[3],
            "rows_valid": batch_row[4],
            "pairs_total": batch_row[5],
            "pairs_after_sql": batch_row[6],
            "pairs_after_rules": batch_row[7],
            "pairs_matched": batch_row[8],
            "emails_sent": batch_row[9],
        }

    return {
        "funnel": funnel,
        "lender_stats": lender_stats,
        "credit_stats": credit_stats,
        "income_stats": income_stats,
        "product_counts": {
            "total": prod_row[0] if prod_row else 0,
            "crawled": prod_row[1] if prod_row else 0,
            "seed": prod_row[2] if prod_row else 0,
        },
        "top_products": top_products,
    }


