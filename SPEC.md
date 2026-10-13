# SPEC.md: Loan Eligibility Engine

> Source of truth for this project. Read this file fully before writing any code.
> If something here conflicts with a suggestion, this file wins. Ask before deviating.

## 1. Mission

Build an automated system that:
1. Ingests user data from a bulk CSV upload (event-driven, scalable).
2. Discovers personal loan products from public financial websites (daily crawl).
3. Matches users to loan products they are likely eligible for (optimized, multi-stage).
4. Emails matched users (test inbox only).

This is an SDE Intern backend take-home with a 72-hour deadline. It is judged on workflow design, cloud architecture, code quality, and documentation.

## 2. Fixed tech stack

| Area | Choice |
|---|---|
| Backend language | Python 3.11 |
| Cloud | AWS Lambda, S3, RDS PostgreSQL, SES (API Gateway for the presign endpoint only) |
| Automation | Self-hosted n8n via Docker Compose |
| Database (dev) | Local Postgres in Docker, moved to RDS only after the local flow works |
| AWS deployment | Serverless Framework (`serverless.yml`) |
| LLM | Any API with a free tier (Gemini preferred), used only in the last matching stage |
| Frontend | Static HTML/JS, no framework |

## 3. Architecture and data flow

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

## 4. Database schema (draft; verify against the real users.csv before finalizing)

**upload_batches**: `batch_id` (UUID PK), `s3_key`, `status` (uploaded/processed/failed), `rows_total`, `rows_valid`, `rows_rejected`, `created_at`, `processed_at`

**users**: `user_id` (PK), `batch_id` (FK), `email`, `monthly_income`, `credit_score`, `employment_status`, `age`, `created_at`

**loan_products**: `product_id` (serial PK), `provider`, `product_name`, `source_url`, `interest_rate_min`, `interest_rate_max`, `min_monthly_income`, `min_credit_score`, `max_credit_score`, `min_age`, `max_age`, `allowed_employment` (text[]), `raw_eligibility_text`, `last_scraped_at`, `UNIQUE(provider, product_name)`

**matches**: `match_id` (PK), `user_id` (FK), `product_id` (FK), `match_stage` (sql / rules / llm), `confidence`, `notified` (boolean, default false), `created_at`, `UNIQUE(user_id, product_id)`

Rules:
- All inserts are idempotent (upsert / ON CONFLICT). Re-running any step must not create duplicates.
- Money and score columns use numeric types, not text.

## 5. Functional requirements

### 5.1 Ingestion (Lambda)
- `presign_upload`: returns a presigned S3 PUT URL and creates an `upload_batches` row.
- `process_csv`: triggered by S3 event. Stream-parse the CSV, validate each row (email format, numeric fields, age 18-100, credit score 300-900, non-empty employment_status), upsert valid rows, count rejected rows, set batch status, then call the n8n webhook with `batch_id`.
- Bad rows must never crash the batch. Log them and count them.

### 5.2 Workflow A: Loan Product Discovery
- Trigger: Schedule (daily).
- Crawl 2-3 public sites with personal loan listings.
- Extract: product_name, interest_rate, min income, credit score range, age limits, employment criteria.
- Normalize into the `loan_products` columns. Keep the raw eligibility text too.
- Upsert on (provider, product_name). Layout-change handling is optional.
- Prefer HTTP Request + HTML Extract nodes; use the LLM only to parse messy eligibility text.

### 5.3 Workflow B: User-Loan Matching
- Trigger: Webhook (receives `batch_id`).
- Fetch users for that batch and all loan products.
- Multi-stage funnel (the Optimization Treasure Hunt):
  1. **Stage 1, SQL pre-filter:** one set-based query that joins users to products on hard criteria (income, credit score range, age, employment). Eliminates the vast majority of pairs cheaply.
  2. **Stage 2, rules in n8n (Code node):** tie-breakers and soft rules, such as a margin check near thresholds and a debt-to-income proxy.
  3. **Stage 3, LLM, only for ambiguous cases:** pairs that pass Stage 1 but are borderline or have unstructured eligibility text. Batch many pairs per LLM call.
- Insert results into `matches` with `match_stage`.
- Log how many pairs each stage removed (this goes in the README and the demo).

### 5.4 Workflow C: User Notification
- Trigger: runs after Workflow B completes.
- For each user with matches where `notified = false`, build one personalized email listing the matched products.
- Send via AWS SES node to test aliases only (e.g. `yourname+one@gmail.com`). **Never email addresses from the CSV.**
- Set `notified = true` after a successful send.

### 5.5 Frontend
- One page: choose a CSV, upload it via the presigned URL, show progress and success/failure.

## 6. Rules for the coding agent

1. Build in stages (section 7). Stop after each stage and tell me how to test it.
2. Never hardcode secrets. Use `.env` (gitignored); commit only `.env.example`.
3. Local first. No AWS deployment until stages 1-5 work locally.
4. Inside Docker, n8n reaches Postgres at host `postgres`, port 5432.
5. Set `N8N_ENCRYPTION_KEY` and `WEBHOOK_URL` in docker-compose; persist n8n data in a volume.
6. Lambda cannot reach `localhost`. Use a tunnel (ngrok/cloudflared) or serverless-offline when testing the webhook call.
7. Keep code modular and commented. Small functions, clear names.
8. Small commits, one per stage, with clear messages.

## 7. Build stages and "done" criteria

| # | Stage | Done when |
|---|---|---|
| 0 | Repo and folders, .gitignore, .env.example | Pushed to private GitHub repo |
| 1 | docker-compose.yml, schema.sql | n8n opens at localhost:5678 and a Postgres node connects |
| 2 | CSV validation, db helper, local_ingest.py | Sample users.csv loads into `users` locally |
| 3 | Workflow A | `loan_products` fills on a manual run |
| 4 | Workflow B | A curl to the webhook produces rows in `matches` |
| 5 | Workflow C | One email arrives in the Gmail alias |
| 6 | Lambdas and serverless.yml | S3 upload loads the DB and triggers the webhook |
| 7 | Frontend | Browser upload runs the pipeline end to end |
| 8 | README, diagram, demo script | Docs match what actually works |

## 8. Folder structure

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

## 9. Deliverables

- Private GitHub repo with collaborators: ujjwalkala-clickpe, HarshSrivastav-Dailype, ManishBiswal-clickpe, tushar-clickpe
- `serverless.yml`, `docker-compose.yml`, and the three n8n workflow JSON exports
- README with architecture diagram, setup and deployment steps (including n8n credentials for AWS and the database), and design decisions (workflow design, crawling strategy, treasure-hunt solution)
- 5-10 minute demo video: node-by-node workflow walkthrough, live end-to-end run, received email shown in the test inbox
- Submit repo and video links via the Google Form within 72 hours

## 10. Evaluation criteria (100 points)

| Category | Points |
|---|---|
| n8n workflow design and automation (treasure hunt is key) | 30 |
| Backend functionality and code quality | 30 |
| Cloud architecture and integration | 20 |
| Documentation and presentation | 20 |
