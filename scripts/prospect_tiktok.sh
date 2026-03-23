#!/bin/bash
# FameClaw — TikTok Creator Prospector
# Discovers creators from hashtag pages via Playwright, then enriches each via extract_tiktok.sh.
#
# Usage:
#   ./prospect_tiktok.sh --hashtags "youtubeautomation" "facelesschannel" --target 50 --output tiktok_creators.csv [--max-followers 100000] [--scrolls 3]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Defaults ---
TARGET_EMAILS=100
OUTPUT_CSV="tiktok_creators.csv"
MAX_FOLLOWERS=0  # 0 = no limit
SCROLLS=3
HASHTAGS=()

# --- Parse args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hashtags)
      shift
      while [[ $# -gt 0 ]] && [[ ! "$1" =~ ^-- ]]; do
        HASHTAGS+=("$1")
        shift
      done
      ;;
    --target)
      TARGET_EMAILS="$2"; shift 2
      ;;
    --output)
      OUTPUT_CSV="$2"; shift 2
      ;;
    --max-followers)
      MAX_FOLLOWERS="$2"; shift 2
      ;;
    --scrolls)
      SCROLLS="$2"; shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [ ${#HASHTAGS[@]} -eq 0 ]; then
  echo "Usage: $0 --hashtags tag1 tag2 ... [--target 100] [--output file.csv] [--max-followers 100000] [--scrolls 3]" >&2
  exit 1
fi

# --- Check dependencies ---
if ! command -v node &>/dev/null; then
  echo "Error: Node.js is required but not installed." >&2
  echo "Install it from https://nodejs.org/ or via your package manager." >&2
  exit 1
fi

if ! node -e "require('playwright')" 2>/dev/null; then
  echo "" >&2
  echo "TikTok prospecting requires Playwright (headless browser)." >&2
  echo "Install it with:" >&2
  echo "  npm install playwright" >&2
  echo "  npx playwright install chromium" >&2
  echo "" >&2
  echo "Then re-run this command." >&2
  exit 1
fi

# --- Phase 1: Discover creators from hashtag pages ---
echo "=== Phase 1: Discovering creators from hashtag pages ===" >&2
echo "Hashtags: ${HASHTAGS[*]}" >&2
echo "Scrolls per page: $SCROLLS" >&2
echo "" >&2

TMPDIR_WORK=$(mktemp -d)
trap "rm -rf $TMPDIR_WORK" EXIT

HANDLES_FILE="$TMPDIR_WORK/handles.jsonl"

node "$SCRIPT_DIR/prospect_tiktok_worker.js" \
  --hashtags "${HASHTAGS[@]}" \
  --scrolls "$SCROLLS" \
  > "$HANDLES_FILE"

TOTAL_DISCOVERED=$(wc -l < "$HANDLES_FILE" | tr -d ' ')
if [ "$TOTAL_DISCOVERED" -eq 0 ]; then
  echo "No creators found. Try different hashtags or more scrolls." >&2
  exit 1
fi

echo "" >&2
echo "=== Phase 2: Enriching $TOTAL_DISCOVERED creators ===" >&2
echo "Target: $TARGET_EMAILS creators with emails" >&2
echo "Output: $OUTPUT_CSV" >&2
echo "" >&2

# --- Phase 2: Enrich each handle via extract_tiktok.sh ---
EMAIL_COUNT=0
PROCESSED=0

# Parse follower count string (e.g., "1.2K" -> 1200, "3.5M" -> 3500000)
parse_count() {
  local val="$1"
  if [ -z "$val" ] || [ "$val" = "0" ]; then
    echo "0"
    return
  fi
  python3 -c "
import re, sys
v = '''$val'''.strip()
m = re.match(r'^([\\d.]+)([KMBkmb]?)$', v)
if not m:
    print('0')
    sys.exit()
n = float(m.group(1))
s = m.group(2).upper()
if s == 'K': n *= 1000
elif s == 'M': n *= 1000000
elif s == 'B': n *= 1000000000
print(int(n))
" 2>/dev/null || echo "0"
}

while IFS= read -r line; do
  HANDLE=$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['handle'])" 2>/dev/null || true)
  if [ -z "$HANDLE" ]; then continue; fi

  PROCESSED=$((PROCESSED + 1))
  PROFILE_URL="https://www.tiktok.com/@${HANDLE}"

  echo "Enriching $PROCESSED/$TOTAL_DISCOVERED: @${HANDLE}..." >&2

  # Run extract_tiktok.sh — it appends to the CSV
  bash "$SCRIPT_DIR/extract_tiktok.sh" "$PROFILE_URL" "$OUTPUT_CSV" 2>/dev/null || {
    echo "  (skipped — extraction failed)" >&2
    continue
  }

  # Check the last row for follower filter and email
  LAST_ROW=$(tail -1 "$OUTPUT_CSV" 2>/dev/null || true)

  if [ -n "$LAST_ROW" ] && [ "$MAX_FOLLOWERS" -gt 0 ]; then
    # followers is column 3 (index 2) in TikTok CSV
    FOLLOWERS_RAW=$(echo "$LAST_ROW" | python3 -c "
import csv, sys
row = next(csv.reader(sys.stdin))
print(row[2] if len(row) > 2 else '0')
" 2>/dev/null || echo "0")
    FOLLOWER_NUM=$(parse_count "$FOLLOWERS_RAW")
    if [ "$FOLLOWER_NUM" -gt "$MAX_FOLLOWERS" ]; then
      # Remove the last line (over follower limit)
      head -n -1 "$OUTPUT_CSV" > "$TMPDIR_WORK/trimmed.csv" && mv "$TMPDIR_WORK/trimmed.csv" "$OUTPUT_CSV"
      echo "  (skipped — ${FOLLOWERS_RAW} followers exceeds limit)" >&2
      continue
    fi
  fi

  # Check if email was found (column 8, index 7)
  if [ -n "$LAST_ROW" ]; then
    EMAIL_VAL=$(echo "$LAST_ROW" | python3 -c "
import csv, sys
row = next(csv.reader(sys.stdin))
print(row[7] if len(row) > 7 else '')
" 2>/dev/null || echo "")
    if [ -n "$EMAIL_VAL" ] && [ "$EMAIL_VAL" != "" ]; then
      EMAIL_COUNT=$((EMAIL_COUNT + 1))
      echo "  ✓ email found ($EMAIL_COUNT/$TARGET_EMAILS)" >&2
    fi
  fi

  # Check if we've hit the target
  if [ "$EMAIL_COUNT" -ge "$TARGET_EMAILS" ]; then
    echo "" >&2
    echo "🎯 Target reached: $EMAIL_COUNT emails found!" >&2
    break
  fi

  # Brief pause to avoid rate limiting
  sleep 1

done < "$HANDLES_FILE"

# --- Summary ---
TOTAL_ROWS=0
if [ -f "$OUTPUT_CSV" ]; then
  TOTAL_ROWS=$(( $(wc -l < "$OUTPUT_CSV" | tr -d ' ') - 1 ))  # minus header
  [ "$TOTAL_ROWS" -lt 0 ] && TOTAL_ROWS=0
fi

echo "" >&2
echo "=== Done ===" >&2
echo "Processed: $PROCESSED / $TOTAL_DISCOVERED creators" >&2
echo "In CSV: $TOTAL_ROWS creators" >&2
echo "With email: $EMAIL_COUNT" >&2
echo "Output: $OUTPUT_CSV" >&2
