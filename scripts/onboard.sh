#!/bin/bash
# FameClaw Onboarding — Scan a brand's website and extract intelligence
# for targeted YouTube creator prospecting.
#
# Usage:
#   ./onboard.sh --brand "Acme" --url "https://acme.com" --output config_scan.json
#
# Output: JSON with site analysis (title, description, industry signals, social, etc.)
# The agent reads this scan and asks clarifying questions before generating prospect config.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BRAND=""
URL=""
OUTPUT="fameclaw_scan.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --brand) BRAND="$2"; shift 2 ;;
    --url) URL="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

if [ -z "$BRAND" ]; then
  printf "Brand name: "
  read -r BRAND
fi
if [ -z "$URL" ]; then
  printf "Website URL: "
  read -r URL
fi

# Normalize
URL=$(echo "$URL" | sed 's:/*$::')
[[ "$URL" =~ ^https?:// ]] || URL="https://$URL"

echo "Scanning $URL..."

python3 "$SCRIPT_DIR/scan_site.py" --brand "$BRAND" --url "$URL" --output "$OUTPUT"
