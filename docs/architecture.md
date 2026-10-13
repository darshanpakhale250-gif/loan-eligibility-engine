# Architecture Overview — Loan Eligibility Engine

The Loan Eligibility Engine is an automated batch ingestion, product discovery, matching, and notification platform structured strictly across **four isolated Docker containers** connected via an internal bridge network (`loan_net`).

---

## High-Level Architecture Diagram

```mermaid
flowchart TD
    subgraph Host ["Host System / User Browser"]
        UserBrowser["Browser (Port 8080)"]
        N8nUI["n8n Web UI (Port 5678)"]
    end

    subgraph DockerNetwork ["Internal Docker Network (loan_net)"]
        Frontend["1. frontend (nginx:1.27-alpine)<br/>Port 80 -> 8080<br/>Serves HTML/CSS/JS<br/>Proxies /api/* to backend"]
        Backend["2. backend (FastAPI / Py 3.11)<br/>Internal Port 8000<br/>• CSV Stream Ingestion<br/>• Row Validation & Bulk Upsert<br/>• AsyncWebCrawler (Crawl4AI)"]
        N8n["3. n8n (n8n:1.76.1)<br/>Internal 5678 -> Host 5678<br/>• Workflow A: Product Crawl<br/>• Workflow B: Matching Funnel<br/>• Workflow C: Email Dispatch"]
        Postgres["4. postgres (postgres:16-alpine)<br/>Internal Port 5432 (Unpublished)<br/>• upload_batches<br/>• users & batch_rejections<br/>• loan_products<br/>• matches & llm_verdict_cache"]
    end

    subgraph ExternalBankSites ["Public Bank Websites"]
        SBI["sbi.co.in"]
        HDFC["hdfcbank.com"]
        ICICI["icicibank.com"]
    end

    subgraph ExternalAWS ["AWS Cloud (Optional / Production)"]
        SES["AWS Simple Email Service (SES)"]
    end

    %% Connections
    UserBrowser -->|HTTP GET/POST /api/| Frontend
    N8nUI -.->|Direct Workflow Admin| N8n

    Frontend -->|Reverse Proxy /api/| Backend
    Backend -->|Stream chunks / SQL| Postgres
    Backend -->|Trigger Workflow B Webhook| N8n

    N8n -->|Trigger /internal/crawl (Token Auth)| Backend
    Backend -->|Crawl4AI Headless Chromium| ExternalBankSites

    N8n -->|SQL Pre-filter & Funnel Updates| Postgres
    N8n -->|SMTP / API Dispatch| SES
```

---

## The Four Containers

| Container | Image | Host Port | Purpose |
|---|---|---|---|
| `frontend` | `nginx:1.27-alpine` | `8080:80` | Serves vanilla static UI, proxies `/api/*` to backend with buffering disabled, strictly forbids `/internal/*`. |
| `backend` | `python:3.11-slim` | *None* | FastAPI application handling chunked CSV ingestion, validation, batch lifecycle, and Crawl4AI web crawler. |
| `n8n` | `docker.n8n.io/n8nio/n8n:1.76.1` | `5678:5678` | Low-code orchestration running Workflows A, B, and C with automated bootstrapper. |
| `postgres` | `postgres:16-alpine` | *None* | Relational persistence with indexed tables, constraints, and JSONB rules. |

---

## Security & Network Isolation

1. **No Database Exposure:** PostgreSQL runs on the internal bridge network (`loan_net`). Port 5432 is never mapped to the host, preventing external access.
2. **Internal Endpoints Protected:** The `/internal/crawl` endpoint is accessible only inside `loan_net` and guarded by `X-Internal-Token`. Nginx specifically blocks external routing to `/internal/`.
3. **Webhook Authentication:** All webhook communications between backend and n8n are authenticated via `X-Webhook-Secret`.
4. **Zero Dummy Data:** All match evaluations, funnel statistics, and product data originate either from live public bank crawls or verified seed tables in PostgreSQL.
