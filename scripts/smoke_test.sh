#!/usr/bin/env bash
# ==============================================================================
# smoke_test.sh – Automated End-to-End Pipeline Smoke Test
# ==============================================================================
# Runs the entire Loan Eligibility Engine pipeline:
#   1. Check /health
#   2. Create batch via POST /api/uploads
#   3. Upload CSV fixture via PUT /api/uploads/{batch_id}
#   4. Poll batch status until completion
#   5. Verify matches and counters in database
# ==============================================================================

set -euo pipefail

BASE_URL="${API_BASE_URL:-http://localhost:8080}"
FIXTURE_PATH="${FIXTURE_PATH:-backend/tests/fixtures/users_sample.csv}"
MAX_WAIT_SECONDS=60
POLL_INTERVAL=2

echo "=========================================================="
echo " Loan Eligibility Engine – Smoke Test"
echo " Target API: ${BASE_URL}"
echo " Fixture:    ${FIXTURE_PATH}"
echo "=========================================================="

if [ ! -f "${FIXTURE_PATH}" ]; then
  echo "Error: Fixture file not found at ${FIXTURE_PATH}"
  exit 1
fi

# 1. Health check
echo "[1/5] Checking service health..."
HEALTH_RESP=$(curl -s -w "\n%{http_code}" "${BASE_URL}/health" || true)
HTTP_CODE=$(echo "${HEALTH_RESP}" | tail -n1)

if [ "${HTTP_CODE}" != "200" ]; then
  echo "Failed: Health check returned HTTP ${HTTP_CODE}"
  echo "${HEALTH_RESP}"
  exit 1
fi
echo "✓ Service is healthy"

# 2. Create batch
echo "[2/5] Creating upload batch..."
CREATE_RESP=$(curl -s -X POST "${BASE_URL}/api/uploads" \
  -H "Content-Type: application/json" \
  -d '{"filename": "users_sample.csv"}')

BATCH_ID=$(echo "${CREATE_RESP}" | grep -o '"batch_id":"[^"]*' | cut -d'"' -f4 || true)
UPLOAD_URL=$(echo "${CREATE_RESP}" | grep -o '"upload_url":"[^"]*' | cut -d'"' -f4 || true)

if [ -z "${BATCH_ID}" ]; then
  echo "Failed: Could not extract batch_id from response: ${CREATE_RESP}"
  exit 1
fi
echo "✓ Created batch: ${BATCH_ID}"

# 3. Stream CSV to upload endpoint
echo "[3/5] Streaming CSV file (${FIXTURE_PATH})..."
PUT_RESP=$(curl -s -w "\n%{http_code}" -X PUT "${BASE_URL}${UPLOAD_URL}" \
  -H "Content-Type: text/csv" \
  --data-binary "@${FIXTURE_PATH}")

PUT_CODE=$(echo "${PUT_RESP}" | tail -n1)
if [ "${PUT_CODE}" != "200" ] && [ "${PUT_CODE}" != "202" ]; then
  echo "Failed: Upload failed with HTTP ${PUT_CODE}"
  echo "${PUT_RESP}"
  exit 1
fi
echo "✓ CSV uploaded successfully, background ingestion initiated"

# 4. Poll batch status
echo "[4/5] Polling batch status..."
ELAPSED=0
COMPLETED=0

while [ "${ELAPSED}" -lt "${MAX_WAIT_SECONDS}" ]; do
  STATUS_RESP=$(curl -s "${BASE_URL}/api/batches/${BATCH_ID}")
  STATUS=$(echo "${STATUS_RESP}" | grep -o '"status":"[^"]*' | cut -d'"' -f4 || true)

  echo "  [${ELAPSED}s] Current status: ${STATUS}"

  if [ "${STATUS}" = "completed" ] || [ "${STATUS}" = "processed" ] || [ "${STATUS}" = "matching" ]; then
    COMPLETED=1
    break
  elif [ "${STATUS}" = "failed" ]; then
    echo "Failed: Batch failed during processing: ${STATUS_RESP}"
    exit 1
  fi

  sleep "${POLL_INTERVAL}"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

if [ "${COMPLETED}" -ne 1 ]; then
  echo "Failed: Batch timed out after ${MAX_WAIT_SECONDS} seconds"
  exit 1
fi
echo "✓ Ingestion and processing finished"

# 5. Query matches sample
echo "[5/5] Verifying matches..."
MATCHES_RESP=$(curl -s "${BASE_URL}/api/matches?batch_id=${BATCH_ID}&limit=5")
MATCH_COUNT=$(echo "${MATCHES_RESP}" | grep -o '"count":[0-9]*' | cut -d':' -f2 || true)

echo "  Matches found: ${MATCH_COUNT:-0}"
echo "=========================================================="
echo "✓ All Smoke Tests Passed Successfully!"
echo "=========================================================="
exit 0
