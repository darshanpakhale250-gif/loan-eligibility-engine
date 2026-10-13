import logging
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
from app.config import settings

logger = logging.getLogger(__name__)

def get_connection():
    return psycopg2.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        dbname=settings.postgres_db
    )

@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def check_db_health() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone()[0] == 1
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False

def init_db(schema_path: str = None):
    """Executes idempotent schema to ensure tables exist even if mounted volume was not empty."""
    import os
    candidates = [
        schema_path,
        "/app/database/01_schema.sql",
        os.path.join(os.path.dirname(__file__), "..", "..", "database", "01_schema.sql")
    ]
    path_to_use = next((p for p in candidates if p and os.path.exists(p)), None)
    if not path_to_use:
        logger.warning("01_schema.sql not found for backend startup check; relying on container initdb.")
        return

    try:
        with open(path_to_use, "r", encoding="utf-8") as f:
            sql = f.read()
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
        logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to execute init_db: {e}")
