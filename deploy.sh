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

if gcloud run jobs describe daily-sector-job --region "$REGION" --project "$PROJECT_ID" &>/dev/null; then
  gcloud run jobs update daily-sector-job \
    --image "$IMAGE" \
    --command python \
    --args "src/jobs/daily_sector_opportunities.py" \
    --region "$REGION" \
    --project "$PROJECT_ID"
else
  gcloud run jobs create daily-sector-job \
    --image "$IMAGE" \
    --command python \
    --args "src/jobs/daily_sector_opportunities.py" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --service-account "$SA"
fi

if gcloud run jobs describe daily-anomaly-job --region "$REGION" --project "$PROJECT_ID" &>/dev/null; then
  gcloud run jobs update daily-anomaly-job \
    --image "$IMAGE" \
    --command python \
    --args "src/jobs/daily_anomaly_radar.py" \
    --region "$REGION" \
    --project "$PROJECT_ID"
else
  gcloud run jobs create daily-anomaly-job \
    --image "$IMAGE" \
    --command python \
    --args "src/jobs/daily_anomaly_radar.py" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --service-account "$SA"
fi

if gcloud run jobs describe daily-news-job --region "$REGION" --project "$PROJECT_ID" &>/dev/null; then
  gcloud run jobs update daily-news-job \
    --image "$IMAGE" \
    --command python \
    --args "src/jobs/daily_news_enrich.py" \
    --region "$REGION" \
    --project "$PROJECT_ID"
else
  gcloud run jobs create daily-news-job \
    --image "$IMAGE" \
    --command python \
    --args "src/jobs/daily_news_enrich.py" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --service-account "$SA"
fi

# narrative job: always delete+create to avoid secret/env-var type conflicts
if gcloud run jobs describe daily-narrative-job --region "$REGION" --project "$PROJECT_ID" &>/dev/null; then
  gcloud run jobs delete daily-narrative-job \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --quiet
fi
gcloud run jobs create daily-narrative-job \
  --image "$IMAGE" \
  --command python \
  --args "src/jobs/daily_narrative.py" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --service-account "$SA" \
  --update-env-vars "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"

# newsletter job: always delete+create to avoid secret/env-var type conflicts
if gcloud run jobs describe daily-newsletter-job --region "$REGION" --project "$PROJECT_ID" &>/dev/null; then
  gcloud run jobs delete daily-newsletter-job \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --quiet
fi
gcloud run jobs create daily-newsletter-job \
  --image "$IMAGE" \
  --command python \
  --args "src/jobs/daily_newsletter.py" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --service-account "$SA" \
  --update-env-vars "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"

# Remove obsolete job (pointed to daily_picks.py which no longer exists)
if gcloud run jobs describe daily-scanner-job --region "$REGION" --project "$PROJECT_ID" &>/dev/null; then
  echo "Deleting obsolete daily-scanner-job..."
  gcloud run jobs delete daily-scanner-job \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --quiet
fi

gcloud run jobs update weekly-companies \
  --image "$IMAGE" \
  --region "$REGION" \
  --project "$PROJECT_ID"

echo "=== Ensuring Cloud Scheduler triggers ==="

SCHEDULER_SA="425504558294-compute@developer.gserviceaccount.com"
SCHEDULER_BASE="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs"

declare -A SCHEDULES=(
  ["daily-prices-cron"]="daily-prices-job|0 5 * * *"
  ["daily-enrich-cron"]="daily-enrich-job|30 5 * * 1-5"
  ["daily-sector-cron"]="daily-sector-job|0 7 * * 1-5"
  ["daily-anomaly-cron"]="daily-anomaly-job|0 7 * * 1-5"
  ["daily-news-cron"]="daily-news-job|0 8 * * 1-5"
  ["daily-narrative-cron"]="daily-narrative-job|0 9 * * 1-5"
  ["daily-newsletter-cron"]="daily-newsletter-job|30 9 * * 1-5"
  ["weekly-companies-cron"]="weekly-companies|0 10 * * 0"
)

for CRON_NAME in "${!SCHEDULES[@]}"; do
  IFS='|' read -r JOB_NAME CRON_SCHEDULE <<< "${SCHEDULES[$CRON_NAME]}"
  if gcloud scheduler jobs describe "$CRON_NAME" --location "$REGION" --project "$PROJECT_ID" &>/dev/null; then
    gcloud scheduler jobs update http "$CRON_NAME" \
      --schedule "$CRON_SCHEDULE" \
      --time-zone "Europe/Madrid" \
      --uri "$SCHEDULER_BASE/$JOB_NAME:run" \
      --oauth-service-account-email "$SCHEDULER_SA" \
      --location "$REGION" \
      --project "$PROJECT_ID"
  else
    gcloud scheduler jobs create http "$CRON_NAME" \
      --schedule "$CRON_SCHEDULE" \
      --time-zone "Europe/Madrid" \
      --uri "$SCHEDULER_BASE/$JOB_NAME:run" \
      --oauth-service-account-email "$SCHEDULER_SA" \
      --location "$REGION" \
      --project "$PROJECT_ID"
  fi
done

echo "=== Done. All jobs updated ==="
echo ""
echo "Jobs running in europe-west1:"
gcloud run jobs list --project="$PROJECT_ID" --region="$REGION"
echo ""
echo "Scheduler triggers:"
gcloud scheduler jobs list --project="$PROJECT_ID" --location="$REGION"
