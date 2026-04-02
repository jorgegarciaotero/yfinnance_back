#!/bin/bash
# deploy.sh — Build image and update all Cloud Run Jobs
set -e

PROJECT_ID="yfinance-gcp"
REGION="europe-west1"
IMAGE="europe-west1-docker.pkg.dev/$PROJECT_ID/stock-jobs/stock-jobs:latest"
SA="425504558294-compute@developer.gserviceaccount.com"

echo "=== Building and pushing image via Cloud Build ==="
gcloud builds submit \
  --tag "$IMAGE" \
  --project "$PROJECT_ID"

echo "=== Updating Cloud Run Jobs ==="

gcloud run jobs update daily-prices-job \
  --image "$IMAGE" \
  --region "$REGION" \
  --project "$PROJECT_ID"

gcloud run jobs update daily-enrich-job \
  --image "$IMAGE" \
  --region "$REGION" \
  --project "$PROJECT_ID"

gcloud run jobs update daily-sector-job \
  --image "$IMAGE" \
  --args "src/jobs/daily_sector_opportunities.py" \
  --region "$REGION" \
  --project "$PROJECT_ID"

gcloud run jobs update weekly-companies \
  --image "$IMAGE" \
  --region "$REGION" \
  --project "$PROJECT_ID"

echo "=== Done. All jobs updated ==="
echo ""
echo "Jobs running in europe-west1:"
gcloud run jobs list --project="$PROJECT_ID" --region="$REGION"
