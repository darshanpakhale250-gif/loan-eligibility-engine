from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from app.db import check_db_health, init_db
from app.routes.uploads import router as uploads_router
from app.routes.batches import router as batches_router
from app.routes.internal import router as internal_router

app = FastAPI(
    title="Loan Eligibility Engine API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(uploads_router)
app.include_router(batches_router)
app.include_router(internal_router)

@app.on_event("startup")
def on_startup():
    try:
        init_db()
    except Exception:
        pass

@app.get("/")
@app.get("/api")
@app.get("/api/")
def root():
    return {
        "title": "Loan Eligibility Engine API",
        "status": "online",
        "docs": "/docs",
        "health": "/health",
        "batches": "/api/batches"
    }

@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    db_ok = check_db_health()
    if not db_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unhealthy", "database": "disconnected"}
        )
    return {"status": "healthy", "database": "connected"}

@app.get("/api/ping")
def ping():
    return {"message": "pong"}

