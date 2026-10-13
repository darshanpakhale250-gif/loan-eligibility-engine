# REBUILD PROMPT: Loan Eligibility Engine (end to end, four containers)

You are rebuilding an existing repo into a complete, working system for the "Loan Eligibility Engine" SDE Intern take-home. Read this whole file before touching anything. Work in the stages in section 12. After each stage, STOP and wait for my "continue".

---

## 0. Working rules (token and error control)

1. One stage at a time. After a stage reply ONLY with: files changed, the exact commands for me to run, and the output I should expect. No long explanations.
2. Do not re-read files you have not changed. Do not print large files back to me. Do not explore the repo beyond what a stage needs.
3. Never hardcode secrets. Real values live in `.env` (gitignored). Commit only `.env.example`. Remove the hardcoded DB password currently in `docker-compose.yml` and `README.md`.
4. Do not assume library APIs, n8n node parameter shapes, or n8n CLI flags. Verify against the docs for the exact versions you pin (Crawl4AI, n8n, FastAPI, psycopg). If you cannot verify something, say so instead of guessing.
5. Pin versions. Never use `latest` for n8n or Postgres images.
6. Every acceptance test in section 12 must pass before you say a stage is done. If a test cannot be run by you (needs my browser or my AWS account), say exactly what I must check.
7. Never email addresses from the CSV. Only the test inbox in `.env`.
8. Do not run `docker compose down -v`, `docker system prune --volumes`, or anything that deletes volumes unless I ask.

---

## 1. Existing repo (what to reuse)

The current repo (`loan-crawler`) is a crawler-only pipeline: `crawler.py` (Crawl4AI, SBI + HDFC seeds), `extract_data.py` -> `extract_fields.py` (regex field extraction) -> `validate_loans.py` -> `db.py` (psycopg2 upsert into `loan_products`), driven by `run_pipeline.py` and `scheduler.py` through intermediate JSON files in `data/`.

**Reuse:** the Crawl4AI crawling logic, the regex parsers in `extract_fields.py` (amount, age, income, credit score, rate, fee, tenure, employment, mojibake repair), the validation rules, and the `loan_products` column ideas.

**Replace or delete:** `scheduler.py` and the Windows Task Scheduler instructions (scheduling must be an n8n Schedule Trigger), the file-to-file script chain (collapse into one Python package that returns data in memory), `extract_fields_backup.py`, `inspect_pages.py` (move to `scripts/` as a dev tool), the crawler container that runs `run_pipeline.py` as its CMD.

---

## 2. Target architecture: exactly four containers on one network

```
Browser ──► frontend (nginx, :8080) ──/api/──► backend (FastAPI, internal :8000) ──► postgres (internal :5432)
                                                  │  ▲                                  ▲
                                   POST webhook   │  │ POST /internal/crawl             │
                                   (after ingest) ▼  │ (token)                          │
                                              n8n (:5678, UI on localhost only) ───────┘
                                                  │ Workflow A: schedule → crawl → upsert loan_products
                                                  │ Workflow B: webhook → funnel → matches → triggers C
                                                  │ Workflow C: webhook → build emails → AWS SES → mark sent
                                                  ▼
                                             AWS SES → test inbox
```

| Container | Image | Published to host | Purpose |
|---|---|---|---|
| `frontend` | nginx:alpine (pinned) | `8080:80` | Static UI; proxies `/api/` to backend |
| `backend` | built from `./backend` (python:3.11-slim) | none (internal only) | CSV ingestion API, Crawl4AI crawler service, batch status |
| `n8n` | pinned n8nio/n8n tag | `127.0.0.1:5678:5678` | All three workflows |
| `postgres` | postgres:16-alpine | none (internal only) | App data (and nothing else) |

Rules:
- One bridge network `loan_net`. Containers reach each other by service name (`postgres`, `backend`, `n8n`), never `localhost`.
- Only `frontend` (8080) and `n8n` (5678, bound to 127.0.0.1) are reachable from the host. Backend and Postgres are internal. For debugging use `docker compose exec postgres psql ...`.
- Workflow triggers are n8n **Webhook trigger nodes**. The backend's only webhook-related code is a single outbound POST (with retry) to n8n's Workflow B webhook after ingestion. No webhook receiver logic, no business logic, in backend or frontend.
- Because there are only four containers, Chromium (Crawl4AI) lives inside `backend`. Run uvicorn with ONE worker so only one browser runs at a time.

---

## 3. Repo layout

```
loan-eligibility-engine/
├── README.md  SPEC.md  REBUILD_PROMPT.md  .gitignore  .dockerignore  .env.example
├── docker-compose.yml
├── database/
│   ├── 01_schema.sql              # mounted into postgres init, idempotent
│   └── 02_seed_products.sql       # fallback sample products (source='seed')
├── backend/
│   ├── Dockerfile  requirements.txt
│   ├── app/
│   │   ├── main.py                # FastAPI app, routers, /health
│   │   ├── config.py  db.py
│   │   ├── ingestion/             # csv_reader.py, validation.py, loader.py, core.py (shared with Lambda)
│   │   ├── crawler/               # crawl.py, sites.yml, parsers.py (from extract_fields.py), normalize.py
│   │   └── routes/                # uploads.py, batches.py, internal.py
│   ├── lambda_handlers/           # presign.py, process_csv.py (AWS mode, reuse ingestion/core.py)
│   ├── serverless.yml
│   └── tests/ (fixtures/users_sample.csv, test_validation.py, test_parsers.py)
├── frontend/
│   ├── Dockerfile  nginx.conf
│   └── index.html  app.js  style.css
├── n8n/
│   ├── bootstrap.sh               # import credentials + workflows, activate, then start n8n
│   ├── credentials.template.json  # rendered from env at start, fixed credential IDs
│   ├── workflows/ A_loan_product_discovery.json  B_user_loan_matching.json  C_user_notification.json
│   └── CREDENTIALS.md             # manual fallback steps
├── scripts/ smoke_test.sh  inspect_pages.py
└── docs/ architecture.md (Mermaid)  demo-script.md
```

---

## 4. docker-compose.yml requirements

- Named volumes: `pgdata`, `n8n_data`, `uploads`, `crawl_data`. All app state lives in these. Nothing important in the container filesystem.
- Postgres: `./database` mounted read-only at `/docker-entrypoint-initdb.d`. Healthcheck with `pg_isready`.
- Backend: `depends_on` postgres healthy; healthcheck on `/health`; `shm_size: 1gb` and `init: true` (Chromium is unstable without them); volumes `uploads:/data/uploads`, `crawl_data:/data/crawl`.
- n8n: `depends_on` postgres and backend healthy. Custom entrypoint runs `n8n/bootstrap.sh` then `exec n8n start`. Env: `GENERIC_TIMEZONE=Asia/Kolkata`, `TZ=Asia/Kolkata`, `N8N_ENCRYPTION_KEY` from `.env`, `WEBHOOK_URL=http://localhost:5678/`, `EXECUTIONS_DATA_PRUNE=true`, `EXECUTIONS_DATA_MAX_AGE=168`. Volume `n8n_data:/home/node/.n8n` (SQLite is fine).
- Every service: `restart: unless-stopped` and `logging: {driver: json-file, options: {max-size: "10m", max-file: "3"}}` so logs cannot eat the disk.
- **Disk-size controls:** `backend/Dockerfile` installs only Chromium (`playwright install --with-deps chromium`, never all browsers), uses `--no-install-recommends`, `pip install --no-cache-dir`, removes apt lists, and has a `.dockerignore` that excludes `.git`, `data/`, `.venv`, `__pycache__`, `*.jsonl`. Set Crawl4AI's cache/base directory to `/data/crawl` if the current Crawl4AI version supports it (verify in docs). No dev tools in the final image.

---

## 5. Database (`database/01_schema.sql`, idempotent, all `IF NOT EXISTS`)

Derive column types and validation limits from the real file `backend/tests/fixtures/users_sample.csv`. **Profile that CSV first (Stage 0)** and report columns, types, value ranges, nulls, duplicates, and the distinct `employment_status` values. Do not assume age or score ranges.

- `upload_batches`: `batch_id UUID PK`, `filename`, `storage_ref`, `status` (`created|uploading|processing|processed|matching|completed|failed`), `rows_total`, `rows_valid`, `rows_rejected`, funnel counters (`pairs_total`, `pairs_after_sql`, `pairs_after_rules`, `pairs_sent_to_llm`, `pairs_matched`), `emails_sent`, `error_message`, `created_at`, `processed_at`, `completed_at`.
- `batch_rejections`: `batch_id`, `row_number`, `reason`, `raw_row JSONB`.
- `users`: `user_id TEXT PK`, `batch_id FK`, `email`, `monthly_income NUMERIC`, `credit_score INT`, `employment_status TEXT` (canonicalized, see section 6), `age INT`, `created_at`. Index on `batch_id`.
- `loan_products`: keep the existing columns (lender_name, product_name, source_url, interest_rate_min/max/basis, loan_amount_min/max, age_min/max, min_credit_score, max_credit_score, eligible_employment TEXT[], min_monthly_income_rules JSONB, processing_fee JSONB, eligibility_criteria TEXT, raw_criteria JSONB, crawled_at, stored_at, verification_status) and ADD: `min_monthly_income NUMERIC` (flat, derived as the lowest threshold in the rules, used by SQL matching), `has_qualitative_rules BOOLEAN` (true when eligibility text contains conditions the structured columns cannot express: work experience, employer category, residence, etc.), `source TEXT` (`crawl|seed`), `is_active BOOLEAN DEFAULT TRUE`. Keep `UNIQUE (lender_name, product_name, source_url)`.
- `matches`: `match_id`, `user_id FK`, `product_id FK`, `stage TEXT` (`sql|rules|llm`), `score NUMERIC`, `reason TEXT`, `notification_status TEXT DEFAULT 'pending'` (`pending|sent|skipped|failed`), `created_at`, `UNIQUE (user_id, product_id)`.
- `llm_verdict_cache`: `product_id`, `profile_key TEXT` (bucketed income, score band, age band, employment), `verdict BOOLEAN`, `reason`, `created_at`, `UNIQUE (product_id, profile_key)`.
- `02_seed_products.sql`: 5 to 8 realistic sample products with `source='seed'`, so matching and the demo work even if live crawling is blocked. Label them clearly as sample data in the README. Never present seed rows as crawled.

All writes use `ON CONFLICT` so re-running anything is safe. Postgres runs init scripts only on an empty volume, so also make the backend run the same idempotent schema on startup (harmless re-run).

---

## 6. Backend (FastAPI, Python 3.11)

Endpoints (all JSON; only `/api/*` is proxied by nginx; `/internal/*` is never exposed to the host):

- `GET /health`
- `POST /api/uploads` body `{filename}` -> creates a batch, returns `{batch_id, upload_url}`. This mirrors the S3 presigned-URL pattern.
- `PUT /api/uploads/{batch_id}` streams the raw CSV body to the `uploads` volume (never load the whole file into memory), then starts ingestion as a background task. A real S3 presigned URL replaces this in AWS mode via `STORAGE_MODE=s3`.
- `GET /api/batches/{batch_id}` -> status, row counts, funnel counters, matches count, emails sent (computed from DB).
- `GET /api/batches` -> recent batches.
- `GET /api/matches?batch_id=&limit=` -> small result sample for the UI.
- `POST /internal/crawl` (header `X-Internal-Token`) -> runs the crawler, returns `{products: [...], stats: {...}}`. Called by n8n Workflow A. It does NOT write to the DB; n8n does.

**Ingestion core** (`ingestion/core.py`, shared by the local route and the Lambda handler): stream-parse with `csv`; handle UTF-8 BOM and header case/whitespace; validate each row (email format, numeric parsing, ranges taken from the real CSV profile, non-empty employment); canonicalize `employment_status` into a small fixed set that matches both the CSV values and the product `eligible_employment` values; collect rejects into `batch_rejections`; upsert valid rows in chunks of 1000 with `execute_values` and `ON CONFLICT (user_id) DO UPDATE`; update counters; set status `processed`; then POST `{batch_id}` to n8n Workflow B with header `X-Webhook-Secret`, retry 3 times with backoff, set batch `matching` on success or `failed` with `error_message` otherwise. A bad row must never fail the batch.

---

## 7. Crawler (Crawl4AI, inside backend)

Goal: good, structured, trustworthy data from 3 public bank sites (keep SBI and HDFC; add a third such as ICICI or Axis. Verify the URL loads and has real eligibility text before committing it).

- `crawler/sites.yml`: per site: seed URLs, allowed host, URL patterns, optional CSS/JSON extraction schema. Adding a site must not require code changes.
- Use `AsyncWebCrawler` with a sensible `CrawlerRunConfig`: page timeout, `wait_until`, a short post-load delay for JS-rendered content, cache bypass. Use limited depth (1) with a page cap to reach eligibility, fees and interest-rate subpages. Respect robots.txt (`check_robots_txt=True`) and add a polite delay between pages. Verify exact option names in the current Crawl4AI docs.
- Extraction order: (1) site CSS/JSON schema where it works, (2) the regex parsers reused from `extract_fields.py`, (3) optional LLM extraction (Gemini) only for fields still missing. Never invent values; leave a field null when it is not on the page.
- Normalize into the `loan_products` shape, including flat `min_monthly_income`, canonical `eligible_employment`, and `has_qualitative_rules`.
- Per-seed isolation and retries (reuse the existing logic). One failed site must not fail the run.
- Fallback: if every live crawl fails, return stats saying so. The seed products from `02_seed_products.sql` remain in place. Never return an empty product list as success.
- `stats`: pages attempted/succeeded/failed, products extracted per site, fields missing per site. Workflow A logs this.

---

## 8. n8n workflows (exported JSON with stable `id`s, committed under `n8n/workflows/`)

Credentials are created automatically by `n8n/bootstrap.sh` from env (Postgres, AWS SES, Header Auth for the internal token, optional Gemini key) with fixed credential IDs that the workflow JSON references. If an n8n CLI flag or credential format differs in the pinned version, adapt it and document the manual fallback in `CREDENTIALS.md`. Import, then activate workflows before `n8n start`; production webhook URLs (`/webhook/...`, not `/webhook-test/...`) only work for ACTIVE workflows. For every node type you use, check its `typeVersion` and parameter shape against the pinned n8n version (create one in the editor or consult docs) because hand-written node JSON is easy to get subtly wrong.

### Workflow A: Loan Product Discovery
Schedule Trigger (daily 02:00 Asia/Kolkata) + a Manual Trigger for demos -> HTTP Request `POST http://backend:8000/internal/crawl` (Header Auth credential, long timeout) -> Code (validate: name, lender, URL present; rate within 0 to 100; drop junk) -> IF (any valid products?) -> Postgres Execute Query: one bulk upsert using `jsonb_to_recordset($1::jsonb)` with `ON CONFLICT ... DO UPDATE` -> Code (summary: inserted, updated, per-site counts) -> end. Error branch logs and keeps old data untouched.

### Workflow B: User-Loan Matching (Optimization Treasure Hunt)
Webhook trigger `POST /webhook/loan-match` with Header Auth (`X-Webhook-Secret`), body `{batch_id}`, respond immediately (202) so the backend is not blocked. Then a multi-stage funnel. Record the pair count after each stage in `upload_batches`.

1. **Stage 1, SQL pre-filter (set-based, one query).** Cross join the batch's users with active products inside Postgres and keep only pairs that pass the hard criteria: income >= `min_monthly_income` (null = unknown, keep as ambiguous), credit score within min/max, age within bounds, employment in `eligible_employment` (empty = any). Insert survivors into `matches` with `stage='sql'`. This removes the vast majority of pairs without any row-by-row work.
2. **Stage 2, rules in n8n (Code node).** Rank per user, keep the top K (default 5) products by lowest interest rate; compute a margin score; split pairs into `clear` (comfortably above all thresholds, no qualitative rules) and `ambiguous` (thin margin, null criteria, or `has_qualitative_rules`). Clear pairs are final matches.
3. **Stage 3, LLM only for ambiguous pairs.** First look up `llm_verdict_cache` by `(product_id, profile_key)`. Profile key = bucketed income, score band, age band, employment. Identical profiles share one verdict. For cache misses, batch up to 20 pairs per Gemini call (HTTP Request node), require a strict JSON response, validate it, write verdicts to the cache, and cap total calls per run with `LLM_MAX_PAIRS`. If no API key or the call fails, fall back to a conservative rule (exclude ambiguous pairs) and log it. The LLM never sees clear pairs.

Then: Postgres update (`batch` funnel counters, status) -> HTTP Request to Workflow C webhook `http://n8n:5678/webhook/loan-notify` with the secret header and `{batch_id}`.

### Workflow C: User Notification
Webhook trigger `POST /webhook/loan-notify` (Header Auth) -> Postgres: users in the batch with `pending` matches, products aggregated per user with `json_agg` -> Code: build a personalized plain, minimal HTML email per user (greeting, top matched products with lender, name, rate range, amount range, source link; footer states it is a test) and map each user to a test alias `<local>+uN@<domain>` from `TEST_EMAIL_BASE`. Never use the CSV email. Cap the number of emails per run with `MAX_EMAILS_PER_RUN` (default 3) -> Split In Batches with a short Wait (SES rate limit) -> IF `EMAIL_DRY_RUN` -> AWS SES node (send) -> on success Postgres update `notification_status='sent'` (on failure `failed`, workflow continues) -> final Postgres update: batch `emails_sent`, status `completed`.

Document in the README that a new SES account is in sandbox mode: the sender address and every recipient alias (`name+u1@gmail.com`, etc.) must be verified in SES first.

---

## 9. Frontend (nginx + static files)

Minimal, calm design. NO neon, no gradients, no glow. Off-white background, dark slate text, one muted accent (a desaturated blue or green), thin borders, system font stack, plenty of whitespace.

- A drag-and-drop zone plus a file-picker fallback; accept `.csv` only, with a size check.
- Flow: create batch -> PUT the file (show upload progress) -> poll `GET /api/batches/{id}` every 2 seconds.
- A simple stepper: Uploaded -> Parsed -> Matched -> Emails sent. Show counts: rows total, valid, rejected; funnel counts per stage; matches; emails sent. Show clear error text on failure.
- A small "recent batches" table. Fully usable on mobile width. No framework, no build step.
- `nginx.conf`: serve static files, proxy `/api/` to `http://backend:8000`, allow large request bodies, disable proxy buffering for uploads, never proxy `/internal/`.

---

## 10. `.env.example` (placeholders only)

`POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, N8N_ENCRYPTION_KEY, WEBHOOK_SECRET, INTERNAL_TOKEN, N8N_WEBHOOK_BASE_INTERNAL=http://n8n:5678/webhook, STORAGE_MODE=local, MAX_PAGES, MAX_DEPTH, PAGE_TIMEOUT_MS, GEMINI_API_KEY (optional), LLM_MAX_PAIRS, AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, SES_FROM_EMAIL, TEST_EMAIL_BASE, MAX_EMAILS_PER_RUN, EMAIL_DRY_RUN`.

---

## 11. AWS mode (assignment deliverables; local stack must not depend on it)

- `backend/serverless.yml`: S3 bucket, HTTP API + `presign` Lambda, S3 `ObjectCreated` event -> `process_csv` Lambda, least-privilege IAM, env vars, a documented RDS/VPC note. Handlers are thin wrappers around `ingestion/core.py`. It must pass `serverless package` locally. Say clearly that it was validated but not deployed unless I deploy it.
- Explain in the README that the local `PUT /api/uploads/{id}` path is the local stand-in for the S3 presigned upload + S3 event pattern.

---

## 12. Stages and acceptance tests (stop after each)

**Stage 0: Audit and reorganize.** Move files into the layout, delete what section 1 says to delete, profile `users_sample.csv`, report findings. Test: `git status` clean tree structure; CSV profile reported.

**Stage 1: Compose skeleton.** Postgres + volumes + schema + healthchecks (other services as stubs). Test: `docker compose up -d --build` -> all healthy; insert a row, `docker compose restart`, row still there; `docker compose ps` shows no host ports except 8080 and 5678.

**Stage 2: Backend ingestion.** Test: `curl` create batch + PUT `users_sample.csv` -> `users` filled, rejects counted, batch `processed`; upload the same file again -> no duplicates.

**Stage 3: Crawler service.** Test: `POST /internal/crawl` returns products from at least 2 sites with sensible numbers, or a clear failure report plus seed fallback; `stats` populated.

**Stage 4: n8n bootstrap + Workflow A.** Test: `docker compose up -d` from a clean volume -> workflows imported and active, credentials present with no manual clicking; run A -> `loan_products` rows; `docker compose restart n8n` -> workflows and credentials still there.

**Stage 5: Workflow B.** Test: `curl` the webhook with the secret and a real `batch_id` -> `matches` filled; funnel counters show pairs shrinking at each stage; a wrong secret returns 401/403.

**Stage 6: Workflow C.** Test: with `EMAIL_DRY_RUN=true` the run completes and logs the emails it would send; then with real SES one email arrives at a `+uN` alias; `notification_status='sent'`; running C again sends nothing new.

**Stage 7: Frontend.** Test: open `http://localhost:8080`, drag the sample CSV, watch the stepper reach "Emails sent". Check on a narrow window.

**Stage 8: Hardening and docs.** `scripts/smoke_test.sh` runs the whole pipeline with `EMAIL_DRY_RUN=true` and exits non-zero on failure; `serverless package` passes; README complete; Mermaid architecture diagram; `docs/demo-script.md` for the 5 to 10 minute video. Test: clean clone -> copy `.env.example` -> `docker compose up -d --build` -> smoke test passes.

---

## 13. README must contain

Architecture diagram; the four-container explanation; setup steps from a clean clone (including SES sandbox verification and where each credential goes); how persistence works (named volumes) and what NOT to run; the crawling strategy and its limits; the Optimization Treasure Hunt write-up with the per-stage pair counts from a real run; AWS mode notes; troubleshooting (Docker credential helper error on Windows, port conflicts, n8n inactive workflows, SES sandbox).

---

## 14. Do not

Add a fifth container. Publish backend or Postgres ports. Put business logic in the backend webhook call or in the frontend. Use `latest` tags. Commit secrets. Present seed or sample data as crawled data. Claim something was tested if you did not run it.
