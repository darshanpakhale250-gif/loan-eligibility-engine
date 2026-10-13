# Loan Eligibility Engine

An automated, event-driven loan eligibility and matching system built with Python, PostgreSQL, self-hosted n8n, and AWS serverless infrastructure.

## Architecture Overview

```
Browser UI
   │ 1. request presigned URL
   ▼
API Gateway ──► Lambda: presign_upload
   │ 2. returns presigned S3 PUT URL
   ▼
Browser uploads CSV directly to S3 (bypasses Lambda size/timeout limits)
   │ 3. S3 ObjectCreated event
   ▼
Lambda: process_csv
   │ 4. parse, validate, upsert into Postgres (users, upload_batches)
   │ 5. POST webhook to n8n with { batch_id }
   ▼
n8n Workflow B (matching) ──► writes `matches`
   │ 6. on completion, triggers
   ▼
n8n Workflow C (notification) ──► AWS SES ──► test inbox

n8n Workflow A (crawler, daily schedule) ──► writes `loan_products` (independent)
```

## Tech Stack

- **Backend:** Python 3.11 / Lambda
- **Database:** PostgreSQL (Docker for local dev, RDS for cloud)
- **Workflow Automation:** Self-hosted n8n
- **Cloud Infrastructure:** AWS (S3, Lambda, API Gateway, RDS, SES) via Serverless Framework
- **LLM Matching:** Google Gemini API (Stage 3 optimization funnel)
- **Frontend:** HTML5 / JavaScript

## Project Structure

```
loan-eligibility-engine/
├── README.md
├── SPEC.md
├── .gitignore
├── .env.example
├── docker-compose.yml
├── database/schema.sql
├── backend/
│   ├── serverless.yml
│   ├── requirements.txt
│   ├── src/handlers/{presign_upload.py, process_csv.py}
│   ├── src/common/{config.py, db.py, csv_validation.py}
│   └── tests/{fixtures/users_small.csv, test_process_csv.py}
├── frontend/{index.html, app.js, style.css}
├── n8n/workflows/{A_loan_product_discovery.json, B_user_loan_matching.json, C_user_notification.json}
├── n8n/CREDENTIALS.md
├── scripts/local_ingest.py
└── docs/{architecture.md, demo-script.md}
```

## Build Stages

- [x] **Stage 0:** Repository & folder setup, `.gitignore`, `.env.example`, private GitHub repo.
- [ ] **Stage 1:** `docker-compose.yml` (Postgres + n8n) & `schema.sql`.
- [ ] **Stage 2:** CSV validation, database helpers, `local_ingest.py`.
- [ ] **Stage 3:** n8n Workflow A (Loan Product Discovery crawler).
- [ ] **Stage 4:** n8n Workflow B (Optimization Treasure Hunt matching engine).
- [ ] **Stage 5:** n8n Workflow C (User notification via SES).
- [ ] **Stage 6:** AWS Lambdas and `serverless.yml`.
- [ ] **Stage 7:** Frontend CSV direct upload UI.
- [ ] **Stage 8:** Full documentation, architecture diagram, and demo walkthrough.
