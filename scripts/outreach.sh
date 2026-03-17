#!/bin/bash
# FameClaw Outreach — Send personalized emails to scraped creators via gws CLI
#
# Usage:
#   ./outreach.sh --csv scored.csv --template template.html --rate 30 [--dry-run]
#   ./outreach.sh --csv scored.csv --template template.txt --rate 30 --subject "Collab with {{brand}}?"
#
# Prerequisites:
#   1. Install gws: https://github.com/googleworkspace/cli
#   2. Run: gws auth login -s gmail
#
# Template variables (replaced per-channel):
#   {{channel_name}}  — Creator's channel name
#   {{handle}}        — @handle
#   {{subscribers}}   — Subscriber count
#   {{avg_views}}     — Average views
#   {{email}}         — Creator's email
#   {{brand}}         — Your brand name (from --brand)
#   {{website}}       — Your website (from --website)

set -euo pipefail

CSV=""
TEMPLATE=""
SUBJECT="Partnership opportunity with {{brand}}"
BRAND=""
WEBSITE=""
RATE=30  # emails per hour
DRY_RUN=false
MIN_SCORE=0
LOG_DIR=""
SENT_LOG=""
FROM=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --csv) CSV="$2"; shift 2 ;;
    --template) TEMPLATE="$2"; shift 2 ;;
    --subject) SUBJECT="$2"; shift 2 ;;
    --brand) BRAND="$2"; shift 2 ;;
    --website) WEBSITE="$2"; shift 2 ;;
    --rate) RATE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --min-score) MIN_SCORE="$2"; shift 2 ;;
    --from) FROM="$2"; shift 2 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

# Validate
if [ -z "$CSV" ] || [ -z "$TEMPLATE" ]; then
  echo "Usage: $0 --csv <scored.csv> --template <template.html> [--brand name] [--website url] [--rate 30] [--min-score 25] [--dry-run]"
  exit 1
fi

if ! command -v gws &>/dev/null; then
  echo "Error: gws CLI not found. Install from https://github.com/googleworkspace/cli"
  echo "Then run: gws auth login -s gmail"
  exit 1
fi

# Check auth
if ! gws auth status &>/dev/null; then
  echo "Error: Not authenticated. Run: gws auth login -s gmail"
  exit 1
fi

# Setup logging
LOG_DIR="$(dirname "$CSV")/outreach_logs"
mkdir -p "$LOG_DIR"
SENT_LOG="$LOG_DIR/sent.txt"
FAILED_LOG="$LOG_DIR/failed.txt"
RUN_LOG="$LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"
touch "$SENT_LOG" "$FAILED_LOG"

# Detect HTML
IS_HTML=false
if [[ "$TEMPLATE" == *.html ]] || [[ "$TEMPLATE" == *.htm ]]; then
  IS_HTML=true
fi

TEMPLATE_BODY=$(cat "$TEMPLATE")

# Calculate delay between emails
DELAY=$(python3 -c "print(round(3600 / $RATE, 1))")

echo "=== FameClaw Outreach ===" | tee -a "$RUN_LOG"
echo "  CSV: $CSV" | tee -a "$RUN_LOG"
echo "  Template: $TEMPLATE ($([ "$IS_HTML" = true ] && echo 'HTML' || echo 'plain text'))" | tee -a "$RUN_LOG"
echo "  Rate: $RATE/hour (${DELAY}s between sends)" | tee -a "$RUN_LOG"
echo "  Min score: $MIN_SCORE" | tee -a "$RUN_LOG"
echo "  Dry run: $DRY_RUN" | tee -a "$RUN_LOG"
echo "" | tee -a "$RUN_LOG"

# Process CSV
SENT=0
SKIPPED=0
FAILED=0
TOTAL=0

python3 -c "
import csv, sys

with open('$CSV', newline='') as f:
    reader = csv.reader(f)
    header = next(reader)
    
    # Find column indices
    cols = {h.lower().strip(): i for i, h in enumerate(header)}
    name_i = cols.get('channel_name', 0)
    handle_i = cols.get('handle', 1)
    subs_i = cols.get('subscribers', 2)
    views_i = cols.get('avg_views', 4)
    email_i = cols.get('email', 9)
    score_i = cols.get('match_score', -1)
    
    for row in reader:
        email = row[email_i].strip().rstrip(';') if len(row) > email_i else ''
        # Clean emails — take first valid one
        emails = [e.strip() for e in email.replace(';', ',').split(',') if '@' in e and '.' in e.split('@')[-1]]
        # Filter out junk
        emails = [e for e in emails if not any(j in e.lower() for j in ['png', 'jpg', 'gif', 'svg', 'noreply', 'no-reply', 'example', 'test@'])]
        
        if not emails:
            continue
        
        score = 0
        if score_i >= 0 and len(row) > score_i:
            try: score = int(row[score_i])
            except: pass
        
        if score < $MIN_SCORE:
            continue
        
        name = row[name_i] if len(row) > name_i else ''
        handle = row[handle_i] if len(row) > handle_i else ''
        subs = row[subs_i] if len(row) > subs_i else ''
        avg_views = row[views_i] if len(row) > views_i else ''
        
        # Output tab-separated for bash to consume
        print(f'{emails[0]}\t{name}\t{handle}\t{subs}\t{avg_views}\t{score}')
" | while IFS=$'\t' read -r EMAIL NAME HANDLE SUBS VIEWS SCORE; do
  TOTAL=$((TOTAL + 1))
  
  # Skip if already sent
  if grep -qiF "$EMAIL" "$SENT_LOG" 2>/dev/null; then
    SKIPPED=$((SKIPPED + 1))
    continue
  fi
  
  # Personalize template
  BODY=$(echo "$TEMPLATE_BODY" | sed \
    -e "s|{{channel_name}}|$NAME|g" \
    -e "s|{{handle}}|$HANDLE|g" \
    -e "s|{{subscribers}}|$SUBS|g" \
    -e "s|{{avg_views}}|$VIEWS|g" \
    -e "s|{{email}}|$EMAIL|g" \
    -e "s|{{brand}}|$BRAND|g" \
    -e "s|{{website}}|$WEBSITE|g")
  
  SUBJ=$(echo "$SUBJECT" | sed \
    -e "s|{{channel_name}}|$NAME|g" \
    -e "s|{{handle}}|$HANDLE|g" \
    -e "s|{{brand}}|$BRAND|g")
  
  if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] To: $EMAIL | Subject: $SUBJ | Score: $SCORE" | tee -a "$RUN_LOG"
    echo "  Name: $NAME ($HANDLE) | ${SUBS} subs" | tee -a "$RUN_LOG"
    echo "" | tee -a "$RUN_LOG"
    SENT=$((SENT + 1))
    continue
  fi
  
  # Build gws command
  GWS_ARGS=(gws gmail +send --to "$EMAIL" --subject "$SUBJ" --body "$BODY")
  [ "$IS_HTML" = true ] && GWS_ARGS+=(--html)
  [ -n "$FROM" ] && GWS_ARGS+=(--from "$FROM")
  
  # Send
  echo -n "[$(date +%H:%M:%S)] Sending to $EMAIL ($NAME)... " | tee -a "$RUN_LOG"
  
  if "${GWS_ARGS[@]}" >> "$RUN_LOG" 2>&1; then
    echo "✅" | tee -a "$RUN_LOG"
    echo "$EMAIL|$NAME|$HANDLE|$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$SENT_LOG"
    SENT=$((SENT + 1))
  else
    echo "❌" | tee -a "$RUN_LOG"
    echo "$EMAIL|$NAME|$HANDLE|$(date -u +%Y-%m-%dT%H:%M:%SZ)|error" >> "$FAILED_LOG"
    FAILED=$((FAILED + 1))
  fi
  
  # Rate limit
  sleep "$DELAY"
done

echo "" | tee -a "$RUN_LOG"
echo "=== Outreach Complete ===" | tee -a "$RUN_LOG"
echo "  Sent: $SENT" | tee -a "$RUN_LOG"
echo "  Skipped (already sent): $SKIPPED" | tee -a "$RUN_LOG"
echo "  Failed: $FAILED" | tee -a "$RUN_LOG"
echo "  Log: $RUN_LOG" | tee -a "$RUN_LOG"
echo "  Sent log: $SENT_LOG" | tee -a "$RUN_LOG"
