-- =============================================================================
-- Loan Eligibility Engine Schema (Idempotent)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Upload Batches
CREATE TABLE IF NOT EXISTS upload_batches (
    batch_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename TEXT NOT NULL,
    storage_ref TEXT,
    status TEXT NOT NULL DEFAULT 'created' 
        CHECK (status IN ('created', 'uploading', 'processing', 'processed', 'matching', 'completed', 'failed')),
    rows_total INT DEFAULT 0,
    rows_valid INT DEFAULT 0,
    rows_rejected INT DEFAULT 0,
    -- Funnel counters for matching optimization
    pairs_total INT DEFAULT 0,
    pairs_after_sql INT DEFAULT 0,
    pairs_after_rules INT DEFAULT 0,
    pairs_sent_to_llm INT DEFAULT 0,
    pairs_matched INT DEFAULT 0,
    emails_sent INT DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- 2. Batch Rejections (Rejected rows during ingestion)
CREATE TABLE IF NOT EXISTS batch_rejections (
    id SERIAL PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES upload_batches(batch_id) ON DELETE CASCADE,
    row_number INT,
    reason TEXT,
    raw_row JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_batch_rejections_batch_id ON batch_rejections(batch_id);

-- 3. Users (Derived from CSV ingestion)
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    batch_id UUID REFERENCES upload_batches(batch_id) ON DELETE SET NULL,
    name TEXT,
    email TEXT NOT NULL,
    monthly_income NUMERIC NOT NULL,
    credit_score INT NOT NULL,
    employment_status TEXT NOT NULL,
    age INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_batch_id ON users(batch_id);
CREATE INDEX IF NOT EXISTS idx_users_income_score ON users(monthly_income, credit_score);

-- 4. Loan Products (Crawled + Seed fallback)
CREATE TABLE IF NOT EXISTS loan_products (
    id SERIAL PRIMARY KEY,
    lender_name TEXT NOT NULL,
    product_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    interest_rate_min NUMERIC,
    interest_rate_max NUMERIC,
    interest_rate_basis TEXT,
    loan_amount_min NUMERIC,
    loan_amount_max NUMERIC,
    age_min INT,
    age_max INT,
    min_credit_score INT,
    max_credit_score INT,
    eligible_employment TEXT[],
    min_monthly_income_rules JSONB,
    processing_fee JSONB,
    eligibility_criteria TEXT,
    raw_criteria JSONB,
    crawled_at TIMESTAMPTZ DEFAULT NOW(),
    stored_at TIMESTAMPTZ DEFAULT NOW(),
    verification_status TEXT DEFAULT 'unverified',
    min_monthly_income NUMERIC,
    has_qualitative_rules BOOLEAN DEFAULT FALSE,
    source TEXT DEFAULT 'crawl' CHECK (source IN ('crawl', 'seed')),
    is_active BOOLEAN DEFAULT TRUE,
    CONSTRAINT uq_loan_product UNIQUE (lender_name, product_name, source_url)
);
CREATE INDEX IF NOT EXISTS idx_loan_products_active ON loan_products(is_active);
CREATE INDEX IF NOT EXISTS idx_loan_products_min_income ON loan_products(min_monthly_income);

-- 5. Matches (User to Loan Product pairings)
CREATE TABLE IF NOT EXISTS matches (
    match_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES loan_products(id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK (stage IN ('sql', 'rules', 'llm')),
    score NUMERIC,
    reason TEXT,
    notification_status TEXT DEFAULT 'pending' CHECK (notification_status IN ('pending', 'sent', 'skipped', 'failed')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_user_product_match UNIQUE (user_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_matches_user_id ON matches(user_id);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(notification_status);

-- 6. LLM Verdict Cache (Deduplication of LLM calls across similar borrower profiles)
CREATE TABLE IF NOT EXISTS llm_verdict_cache (
    id SERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES loan_products(id) ON DELETE CASCADE,
    profile_key TEXT NOT NULL,
    verdict BOOLEAN NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_product_profile UNIQUE (product_id, profile_key)
);
CREATE INDEX IF NOT EXISTS idx_llm_cache_lookup ON llm_verdict_cache(product_id, profile_key);
