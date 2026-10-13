# Demo Walkthrough Script (5–10 Minutes)

This script outlines a concise, professional 5–10 minute video demonstration of the Loan Eligibility Engine.

---

## Preparation (Pre-Demo)

1. Ensure the stack is up and healthy:
   ```bash
   docker compose up -d --build
   ```
2. Verify all containers are running:
   ```bash
   docker compose ps
   ```
3. Open two browser windows:
   - Window 1: `http://localhost:8080` (Frontend Dashboard)
   - Window 2: `http://localhost:5678` (n8n Workflow Canvas)

---

## 1. Introduction & Architecture (0:00 – 1:30)

- **Speaker:** "Welcome to the Loan Eligibility Engine demonstration. This platform automates the entire lifecycle of retail loan matching: crawling live bank eligibility criteria, ingesting high-volume user datasets, filtering candidates through an optimized multi-stage funnel, and dispatching personalized notifications."
- **Visual:** Show `docs/architecture.md` diagram.
- **Key Points:**
  - Strict 4-container architecture (`frontend`, `backend`, `n8n`, `postgres`) on isolated network `loan_net`.
  - Zero exposed backend or database ports to host machine.
  - End-to-end asynchronous streaming ingestion.

---

## 2. Product Discovery & Crawling (1:30 – 3:30)

- **Speaker:** "First, let's explore how loan products are discovered and kept up-to-date."
- **Visual:** Navigate to n8n canvas (`http://localhost:5678`) and open **Workflow A: Loan Product Discovery**.
- **Actions:**
  - Click **Test step** / **Execute Workflow** on the Manual Trigger node.
  - Point out the HTTP request hitting `http://backend:8000/internal/crawl` with header `X-Internal-Token`.
  - Show the crawl logs: polite headless Crawl4AI browser visiting SBI, HDFC, and ICICI official loan portals.
  - Show the Code node normalizing interest rate bounds, max amounts, and eligibility clauses.
  - Highlight the PostgreSQL bulk upsert inserting/updating records into `loan_products`.

---

## 3. CSV Ingestion & Frontend Flow (3:30 – 5:30)

- **Speaker:** "Now let's ingest a realistic batch of loan applicants."
- **Visual:** Switch to frontend at `http://localhost:8080`.
- **Actions:**
  - Drag and drop `backend/tests/fixtures/users_sample.csv` onto the upload zone.
  - Notice the instant upload progress bar streaming directly through nginx into the backend.
  - Watch the live stepper transition: **Uploaded → Parsed → Matched → Completed**.
  - Review the batch metrics displayed:
    - Total rows read.
    - Valid rows stored in database.
    - Funnel counters showing pair reduction across each stage.

---

## 4. Optimization Treasure Hunt (Matching Funnel) (5:30 – 7:30)

- **Speaker:** "Here is the core optimization: the Matching Funnel in Workflow B."
- **Visual:** Open **Workflow B: User-Loan Matching** in n8n.
- **Explanation:**
  - **Stage 1 (SQL Pre-filter):** Set-based cross-join inside Postgres eliminates >85% of non-viable user-product pairs in milliseconds based on hard income, age, credit score, and employment constraints.
  - **Stage 2 (Rules & Ranking):** Top-K ranking (lowest interest rates first) and margin scoring separates pairs into clear vs ambiguous candidates. Clear pairs are matched immediately without touching any LLM.
  - **Stage 3 (Targeted LLM Cache):** The LLM is invoked only for genuinely ambiguous criteria (e.g., qualitative employer tier conditions) with caching by profile bucket.

---

## 5. Notification Dispatch & Safe Sandboxing (7:30 – 9:00)

- **Speaker:** "Finally, Workflow C prepares notifications."
- **Visual:** Open **Workflow C: User Notification** in n8n.
- **Actions:**
  - Show how pending matches are grouped per applicant.
  - Show the built-in safety safeguard: `TEST_EMAIL_BASE` alias mapping (`test+u1@domain.com`). The pipeline **never** sends emails to actual CSV addresses.
  - Point out `EMAIL_DRY_RUN=true` simulating delivery for local demos while allowing seamless production switch to AWS SES.

---

## 6. Wrap-up & Automated Smoke Test (9:00 – 10:00)

- **Speaker:** "To verify the complete pipeline programmatically, we run our smoke test suite."
- **Terminal Action:**
  ```bash
  bash scripts/smoke_test.sh
  ```
- **Conclusion:** "All five stages pass end-to-end with zero manual intervention. Thank you!"
