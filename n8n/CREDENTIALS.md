# n8n Credentials Configuration & Manual Fallback

In standard operation, `n8n/bootstrap.sh` automatically reads credentials from `.env`, renders `n8n/credentials.template.json`, and imports them into n8n via the CLI upon container startup.

However, if you ever need to configure, inspect, or verify them manually inside the n8n UI (`http://localhost:5678`), follow these instructions.

---

## 0. n8n Web UI Login Credentials
When accessing `http://localhost:5678`:
- **Email**: `admin@admin.com`
- **Password**: `Admin123456!`

---

## 1. Postgres Credential (`cred-postgres-01`)
Used by Workflows A, B, and C to query and persist batches, products, and matches.

- **Name**: `Postgres Account`
- **Type**: `PostgreSQL`
- **Host**: `postgres`
- **Database**: `loan_engine` (from `POSTGRES_DB`)
- **User**: `loan_admin` (from `POSTGRES_USER`)
- **Password**: `admin123` (from `POSTGRES_PASSWORD`)
- **Port**: `5432`
- **SSL**: `Disable`

---

## 2. Internal Token Header Auth (`cred-header-internal`)
Used by Workflow A to call the internal backend crawler endpoint (`http://backend:8000/internal/crawl`).

- **Name**: `Internal Token Header`
- **Type**: `Header Auth`
- **Header Name**: `X-Internal-Token`
- **Header Value**: Value of `INTERNAL_TOKEN` from `.env` (default: `secret-internal-token`)

---

## 3. Webhook Secret Header Auth (`cred-header-webhook`)
Used by Workflow B & C for secure webhook calls between backend and n8n.

- **Name**: `Webhook Secret Header`
- **Type**: `Header Auth`
- **Header Name**: `X-Webhook-Secret`
- **Header Value**: Value of `WEBHOOK_SECRET` from `.env` (default: `secret-webhook`)

---

## 4. Google Gemini API Key (`cred-gemini-01`)
Optional: Used by Workflow B for resolving ambiguous loan eligibility matches.

- **Name**: `Gemini API Header`
- **Type**: `Header Auth`
- **Header Name**: `x-goog-api-key`
- **Header Value**: Your Gemini API key (from `GEMINI_API_KEY`)

---

## 5. AWS SES Account (`cred-aws-ses-01`)
Optional: Used by Workflow C to send user loan recommendation emails when `EMAIL_DRY_RUN=false`.

- **Name**: `AWS SES Account`
- **Type**: `AWS`
- **Region**: `us-east-1` (or your configured AWS region)
- **Access Key ID**: Value of `AWS_ACCESS_KEY_ID`
- **Secret Access Key**: Value of `AWS_SECRET_ACCESS_KEY`

> [!NOTE]
> If your AWS SES account is in sandbox mode, both `SES_FROM_EMAIL` and all recipient email addresses (e.g. `user+u1@domain.com`) must be verified in the AWS SES Console before real emails can be delivered.
