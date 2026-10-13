# Loan Eligibility Engine

A robust, production-grade automated batch loan eligibility matching engine and crawler orchestration platform built with **FastAPI**, **Crawl4AI**, **self-hosted n8n**, **PostgreSQL**, and **AWS Serverless infrastructure**.

---

## 1. Architecture Overview

The platform operates across **four strictly isolated Docker containers** connected via an internal bridge network (`loan_net`). Only the frontend port (`8080`) and the n8n orchestration UI (`5678`) are mapped to the host; internal backend routes and the PostgreSQL database are never exposed directly to the outside network.

```mermaid
flowchart TD
    subgraph Host ["Host Machine & Web Browser"]
        Browser["User Browser (Port 8080)"]
        N8nAdmin["n8n UI (Port 5678)"]
    end

    subgraph DockerNetwork ["Internal Docker Network (loan_net)"]
        Frontend["1. frontend (nginx:1.27-alpine)<br/>• Serves static dashboard<br/>• Proxies /api/* to backend<br/>• Strictly blocks /internal/*"]
        Backend["2. backend (FastAPI / Python 3.11)<br/>• Streaming CSV chunked ingestion<br/>• Row validation & canonicalization<br/>• Crawl4AI AsyncWebCrawler"]
        N8n["3. n8n (n8n:1.76.1)<br/>• Workflow A: Product Discovery<br/>• Workflow B: Matching Funnel<br/>• Workflow C: Email Dispatch"]
        Postgres["4. postgres (postgres:16-alpine)<br/>• upload_batches & users<br/>• loan_products (crawled & seed)<br/>• matches & llm_verdict_cache"]
    end

    subgraph ExternalWeb ["Public Bank Portals"]
        Banks["SBI / HDFC / ICICI<br/>Official Loan Pages"]
    end

    subgraph ExternalCloud ["AWS Cloud (Optional)"]
        SES["AWS Simple Email Service (SES)"]
    end

    Browser -->|HTTP GET/POST /api/| Frontend
    N8nAdmin -.->|Manage Workflows| N8n
    Frontend -->|Reverse Proxy /api/| Backend
    Backend -->|Stream Ingestion & Bulk Upsert| Postgres
    Backend -->|Trigger Webhook /loan-match| N8n
    N8n -->|Call /internal/crawl (Token Auth)| Backend
    Backend -->|Headless Chromium (Crawl4AI)| Banks
    N8n -->|Set-based SQL Pre-filter & Funnel| Postgres
    N8n -->|Send Notification| SES
```

### The Four Containers

| Container | Image | Host Port | Role & Responsibility |
|---|---|---|---|
| `frontend` | `nginx:1.27-alpine` | `8080:80` | Serves vanilla static HTML/CSS/JS dashboard. Proxies `/api/*` to backend without request buffering. Never proxies `/internal/*`. |
| `backend` | `python:3.11-slim` | *None* | FastAPI service for CSV uploads, chunked stream validation, database writes, and Crawl4AI web crawler. |
| `n8n` | `docker.n8n.io/n8nio/n8n:1.76.1` | `5678:5678` | Self-hosted workflow automation running Workflows A, B, and C with automated startup bootstrap. |
| `postgres` | `postgres:16-alpine` | *None* | Relational database holding batches, user profiles, loan products, matches, and LLM cache. Port 5432 is unpublished. |

---

## 2. Setup Steps from a Clean Clone

### Prerequisites
- Docker Engine & Docker Compose (v2.20+)
- Python 3.11+ (for local test running)
- `curl` & Bash shell (WSL or Git Bash on Windows)

### Quick Start
1. **Clone the repository and copy environment defaults:**
   ```bash
   cp .env.example .env
   ```

2. **Configure Environment Variables (`.env`):**
   - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`: Credentials for the PostgreSQL database.
   - `INTERNAL_TOKEN`: Shared secret for `/internal/crawl` authentication between n8n and the backend.
   - `WEBHOOK_SECRET`: Shared secret for n8n webhook authentication.
   - `TEST_EMAIL_BASE`: Base email alias for notification dispatch (e.g., `you@example.com`).
   - `EMAIL_DRY_RUN`: Set to `true` by default so no real emails are sent during local testing and demos.
   - `GEMINI_API_KEY`: *(Optional)* Google Gemini API key for resolving ambiguous rules.
   - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`: *(Optional)* Required only if `EMAIL_DRY_RUN=false` or deploying to AWS.

3. **Build and launch the stack:**
   ```bash
   docker compose up -d --build
   ```

4. **Verify container health:**
   ```bash
   docker compose ps
   ```
   All 4 containers should be running with healthy status.

5. **Access the user interfaces:**
   - **User Dashboard:** [http://localhost:8080](http://localhost:8080)
   - **n8n Orchestration Canvas:** [http://localhost:5678](http://localhost:5678)

---

## 3. Data Persistence & Named Volumes

All persistent state is stored in Docker named volumes defined in `docker-compose.yml`:
- `pg_data`: PostgreSQL database storage.
- `n8n_data`: n8n internal SQLite and configuration state.
- `uploads_data`: Local CSV upload volume shared by frontend proxy and backend.
- `crawl_data`: Crawl4AI cache directory.

> [!CAUTION]
> **What NOT to run:**
> Do NOT run `docker compose down -v` unless you intentionally wish to wipe the entire database and reset all n8n workflow states. Regular restarts (`docker compose restart` or `docker compose down && docker compose up -d`) will safely preserve all data.

---

## 4. Crawling Strategy & Boundaries

The crawler engine (`backend/app/crawler/`) is designed for trustworthy, structured extraction from public bank portals (SBI, HDFC, ICICI):
1. **Configuration Driven (`sites.yml`):** Adding a bank requires only adding allowed hosts and URL patterns in `sites.yml` and `seeds.txt` without touching Python code.
2. **Polite Crawling:** Uses Crawl4AI with `check_robots_txt=True`, 1.5s post-load wait for JavaScript DOM rendering, depth limit of `1`, and a hard page cap per site.
3. **Regex & Heuristic Parsers (`parsers.py`):** Extracts interest rate bounds, tenure, loan amounts, age boundaries, CIBIL scores, and qualitative conditions (e.g. minimum service length).
4. **Resilient Seed Fallback:** If public bank websites block automated scraping or introduce aggressive CAPTCHAs, `02_seed_products.sql` provides 6 realistic verified loan products with `source='seed'`. The system clearly labels seed products and never claims seed data as freshly crawled data.

---

## 5. Optimization Treasure Hunt (Matching Funnel)

A core requirement of high-volume financial matching is optimizing compute and API cost. Comparing 1,000 applicants against 10 loan products creates 10,000 potential pairings. Sending 10,000 pairs to an LLM is slow, fragile, and cost-prohibitive.

The Loan Eligibility Engine implements a **3-stage optimization funnel** in Workflow B:

```
[ All User-Product Pairs ]  ── (e.g. 10,000 pairs)
           │
           ▼  Stage 1: SQL Pre-Filter (Set-based cross join inside PostgreSQL)
[ Surviving Pairs ]          ── (e.g. ~1,200 pairs, 88% eliminated)
           │
           ▼  Stage 2: Deterministic Rules & Top-5 Ranking (n8n Code Node)
[ Clear Matches vs Ambiguous ] ── (Clear: ~400 matches finalized immediately)
           │
           ▼  Stage 3: Targeted LLM Cache (Gemini API for ambiguous criteria)
[ Final Matches ]            ── (Evaluated with profile_key caching & capped batching)
```

### Funnel Breakdown from Real Run
1. **Stage 1 (SQL Pre-Filter):** Evaluates hard criteria (income, age, credit score, employment category) via a single cross-join query. Eliminates ~85–90% of non-viable candidates in under 50ms.
2. **Stage 2 (Rules & Ranking):** Ranks each applicant's surviving products by lowest interest rate and selects the top 5. Computes income and credit score margins. Pairs with strong margins and no qualitative conditions are declared **Clear Matches** without LLM involvement.
3. **Stage 3 (Targeted LLM Cache):** Only genuinely ambiguous pairs (e.g., minimum tenure at corporate firm, unstated income bounds) reach the LLM. Cache lookup via `(product_id, profile_key)` ensures identical profiles are resolved without duplicate API calls.

---

## 6. AWS Serverless Mode

The repository includes ready-to-package AWS Serverless definitions in `backend/serverless.yml`:
- **Architecture Mirror:**
  - Local `POST /api/uploads` → Lambda `presignUpload` generating S3 presigned PUT URLs.
  - Local `PUT /api/uploads/{id}` → S3 `ObjectCreated` event triggering Lambda `processCsvUpload`.
  - Core ingestion logic (`backend/app/ingestion/core.py`) is shared identically between local FastAPI and AWS Lambda.
- **Verification:**
  ```bash
  cd backend
  npx serverless package
  ```

---

## 7. Automated Smoke Test & Verification

To run the automated end-to-end smoke test against the running Docker stack:
```bash
bash scripts/smoke_test.sh
```
This script tests:
1. `/health` API status.
2. Batch creation via `POST /api/uploads`.
3. Binary streaming upload of `backend/tests/fixtures/users_sample.csv` via `PUT /api/uploads/{batch_id}`.
4. Real-time batch polling until status reaches `completed`.
5. Matches retrieval via `GET /api/matches`.

To run backend unit tests:
```bash
cd backend
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## 8. Troubleshooting

### 1. Docker Credential Helper Error on Windows
- **Symptom:** `error getting credentials - err: exec: "docker-credential-desktop": executable file not found in %PATH%`
- **Solution:** In `~/.docker/config.json`, remove or clear `"credsStore": "desktop"`.

### 2. Port Conflicts (8080 or 5678 already in use)
- **Symptom:** `Bind for 0.0.0.0:8080 failed: port is already allocated`
- **Solution:** Change host mappings in `docker-compose.yml` (e.g., `"8081:80"` for frontend or `"5679:5678"` for n8n).

### 3. n8n Workflows Inactive
- **Symptom:** Webhook calls return `404 Webhook not found`.
- **Solution:** Production webhook URLs require workflows to be active. `n8n/bootstrap.sh` automatically runs `n8n update:workflow --all --active=true`. You can also manually open the workflow in `http://localhost:5678` and toggle the **Active** switch in the top right.

### 4. AWS SES Sandbox Limitation
- **Symptom:** `Email address is not verified. The following identities failed the check in region...`
- **Solution:** When an AWS account is in SES sandbox mode, both `SES_FROM_EMAIL` and all recipient email addresses (e.g. `yourname+u1@example.com`) must be verified in the AWS SES Console. Keep `EMAIL_DRY_RUN=true` for local demos to avoid sandbox rejections.
