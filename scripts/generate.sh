#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
METRICS_OUT="${METRICS_OUT:-${REPO_ROOT}/metrics.json}"
TEMPLATE="${TEMPLATE:-${REPO_ROOT}/scripts/template.html}"
REPORT_OUT="${REPORT_OUT:-${REPO_ROOT}/docs/pipeline-report.html}"

echo "==> Stage 1: fetch metrics"
python3 "${REPO_ROOT}/scripts/fetch_metrics.py" --output "${METRICS_OUT}"

echo "==> Stage 2: render report"
python3 "${REPO_ROOT}/scripts/render_report.py" \
  --metrics "${METRICS_OUT}" \
  --template "${TEMPLATE}" \
  --output "${REPORT_OUT}"

echo "Done. Report: ${REPORT_OUT}"
