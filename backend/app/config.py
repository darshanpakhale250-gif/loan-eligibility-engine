import os
from pydantic import BaseModel

class Settings(BaseModel):
    postgres_host: str = os.getenv("POSTGRES_HOST", "postgres")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    postgres_user: str = os.getenv("POSTGRES_USER", "loan_admin")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "")
    postgres_db: str = os.getenv("POSTGRES_DB", "loan_engine")

    internal_token: str = os.getenv("INTERNAL_TOKEN", "secret-internal-token")
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "secret-webhook")
    n8n_webhook_base_internal: str = os.getenv("N8N_WEBHOOK_BASE_INTERNAL", "http://n8n:5678/webhook")

    storage_mode: str = os.getenv("STORAGE_MODE", "local")
    s3_bucket_name: str = os.getenv("S3_BUCKET_NAME", "loan-eligibility-uploads")
    aws_region: str = os.getenv("AWS_REGION", "ap-south-1")
    presign_expiration_seconds: int = int(os.getenv("PRESIGN_EXPIRATION_SECONDS", "900"))
    upload_dir: str = os.getenv("UPLOAD_DIR", "/data/uploads")
    crawl_dir: str = os.getenv("CRAWL_DIR", "/data/crawl")

    max_pages: int = int(os.getenv("MAX_PAGES", "5"))
    max_depth: int = int(os.getenv("MAX_DEPTH", "1"))
    page_timeout_ms: int = int(os.getenv("PAGE_TIMEOUT_MS", "30000"))
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

settings = Settings()
