#!/bin/sh
set -e

echo "[n8n bootstrap] Starting initialization..."

# Check if credentials template exists and n8n CLI is available
if [ -f /n8n/credentials.template.json ]; then
    echo "[n8n bootstrap] Rendering credentials from environment..."
    sed -e "s|\${POSTGRES_USER}|${POSTGRES_USER}|g" \
        -e "s|\${POSTGRES_PASSWORD}|${POSTGRES_PASSWORD}|g" \
        -e "s|\${POSTGRES_DB}|${POSTGRES_DB}|g" \
        -e "s|\${INTERNAL_TOKEN}|${INTERNAL_TOKEN}|g" \
        -e "s|\${WEBHOOK_SECRET}|${WEBHOOK_SECRET}|g" \
        -e "s|\${GEMINI_API_KEY}|${GEMINI_API_KEY}|g" \
        -e "s|\${AWS_REGION}|${AWS_REGION}|g" \
        -e "s|\${AWS_ACCESS_KEY_ID}|${AWS_ACCESS_KEY_ID}|g" \
        -e "s|\${AWS_SECRET_ACCESS_KEY}|${AWS_SECRET_ACCESS_KEY}|g" \
        /n8n/credentials.template.json > /tmp/credentials.json || true
    
    if [ -s /tmp/credentials.json ]; then
        echo "[n8n bootstrap] Importing credentials..."
        n8n import:credentials --input=/tmp/credentials.json || true
        rm -f /tmp/credentials.json
    fi
fi

# Import and activate workflows if directory exists
if [ -d /n8n/workflows ]; then
    echo "[n8n bootstrap] Importing workflows directory..."
    n8n import:workflow --separate --input=/n8n/workflows || true
    echo "[n8n bootstrap] Activating all imported workflows..."
    n8n update:workflow --all --active=true || true
fi

echo "[n8n bootstrap] Bootstrap complete. Launching n8n server..."
exec n8n start
