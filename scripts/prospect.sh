#!/bin/bash
# FameClaw — Batch YouTube Channel Prospector
# Discovers channels by niche, extracts stats + emails, expands via related channels.
# Designed to run standalone or on a cron schedule.
#
# Usage:
#   ./prospect.sh --queries "query1" "query2" ... --target 100 --output channels.csv [--max-subs 100000] [--batch-size 200]
#   ./prospect.sh --config config.json
#
# Config JSON:
#   { "queries": [...], "target_emails": 100, "output": "channels.csv", "max_subs": 100000, "batch_size": 200 }

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# --- Defaults ---
TARGET_EMAILS=100
OUTPUT_CSV="fameclaw_channels.csv"
MAX_SUBS=0  # 0 = no limit
BATCH_SIZE=200
QUERIES=()
WORK_DIR=""
CRON_NAME=""

# --- Parse args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG="$2"; shift 2
      eval "$(python3 -c "
import json, shlex
with open('$CONFIG') as f: c = json.load(f)
qs = ' '.join(shlex.quote(q) for q in c.get('queries', []))
print(f'TARGET_EMAILS={c.get(\"target_emails\", 100)}')
print(f'OUTPUT_CSV={shlex.quote(c.get(\"output\", \"fameclaw_channels.csv\"))}')
print(f'MAX_SUBS={c.get(\"max_subs\", 0)}')
print(f'BATCH_SIZE={c.get(\"batch_size\", 200)}')
print(f'QUERIES=({qs})')
print(f'WORK_DIR={shlex.quote(c.get(\"work_dir\", \"\"))}')
print(f'CRON_NAME={shlex.quote(c.get(\"cron_name\", \"\"))}')
")"
      ;;
    --queries) shift
      while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
        QUERIES+=("$1"); shift
      done ;;
    --target) TARGET_EMAILS="$2"; shift 2 ;;
    --output) OUTPUT_CSV="$2"; shift 2 ;;
    --max-subs) MAX_SUBS="$2"; shift 2 ;;
    --batch-size) BATCH_SIZE="$2"; shift 2 ;;
    --work-dir) WORK_DIR="$2"; shift 2 ;;
    --cron-name) CRON_NAME="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [ ${#QUERIES[@]} -eq 0 ]; then
  echo "Error: No search queries provided. Use --queries or --config."
  exit 1
fi

# --- Setup working directory ---
if [ -z "$WORK_DIR" ]; then
  WORK_DIR="$(dirname "$OUTPUT_CSV")"
  [ "$WORK_DIR" = "." ] && WORK_DIR="$(pwd)"
fi
mkdir -p "$WORK_DIR/logs"

QUEUE_FILE="$WORK_DIR/.fameclaw_queue.txt"
DONE_FILE="$WORK_DIR/.fameclaw_done.txt"
USED_QUERIES_FILE="$WORK_DIR/.fameclaw_used_queries.txt"
STATE_FILE="$WORK_DIR/fameclaw_state.json"
LOG_FILE="$WORK_DIR/logs/run_$(date +%Y%m%d_%H%M%S).log"

touch "$QUEUE_FILE" "$DONE_FILE" "$USED_QUERIES_FILE"

exec > >(tee -a "$LOG_FILE") 2>&1
echo "=== FameClaw Prospector Run: $(date) ==="

# --- Check current email count ---
EMAILS_TOTAL=0
if [ -f "$OUTPUT_CSV" ]; then
  EMAILS_TOTAL=$(tail -n +2 "$OUTPUT_CSV" | python3 -c "
import sys, csv
count = 0
for row in csv.reader(sys.stdin):
    if len(row) > 9 and row[9].strip() and row[9].strip() != ';':
        count += 1
print(count)
" 2>/dev/null || echo "0")
fi
echo "Emails: $EMAILS_TOTAL / $TARGET_EMAILS"

if [ "$EMAILS_TOTAL" -ge "$TARGET_EMAILS" ]; then
  echo "✅ Target reached!"
  [ -n "$CRON_NAME" ] && openclaw cron rm "$CRON_NAME" 2>/dev/null || true
  exit 0
fi

# --- Seed phase ---
QUEUE_COUNT=$(wc -l < "$QUEUE_FILE" | tr -d ' ')
if [ "$QUEUE_COUNT" -lt 100 ]; then
  echo ""
  echo "--- Seeding ---"
  SEEDS_FOUND=0

  for QUERY in "${QUERIES[@]}"; do
    if grep -qF "$QUERY" "$USED_QUERIES_FILE" 2>/dev/null; then
      continue
    fi

    # URL-encode spaces as +
    ENCODED_QUERY=$(echo "$QUERY" | sed 's/ /+/g')
    echo "  Search: $QUERY"
    echo "$QUERY" >> "$USED_QUERIES_FILE"

    SEARCH_HTML=$(curl -sL "https://www.youtube.com/results?search_query=${ENCODED_QUERY}" \
      -H "User-Agent: $UA" 2>/dev/null || true)

    NEW_HANDLES=$(echo "$SEARCH_HTML" | python3 -c "
import sys, re
html = sys.stdin.read()
for m in set(re.findall(r'\"canonicalBaseUrl\":\"/@([^\"]+)\"', html)):
    print(m)
" 2>/dev/null || true)

    while IFS= read -r handle; do
      [ -z "$handle" ] && continue
      if ! grep -qiF "$handle" "$DONE_FILE" 2>/dev/null && ! grep -qiF "$handle" "$QUEUE_FILE" 2>/dev/null; then
        echo "$handle" >> "$QUEUE_FILE"
        SEEDS_FOUND=$((SEEDS_FOUND + 1))
      fi
    done <<< "$NEW_HANDLES"

    sleep 1
    [ "$SEEDS_FOUND" -ge 80 ] && break
  done

  echo "  Added $SEEDS_FOUND channels to queue"
fi

# --- Process phase ---
echo ""
echo "--- Processing (batch $BATCH_SIZE, max subs: ${MAX_SUBS:-unlimited}) ---"

PROCESSED=0
EMAILS_RUN=0
SKIPPED_BIG=0

while [ "$PROCESSED" -lt "$BATCH_SIZE" ]; do
  # Check target
  if [ -f "$OUTPUT_CSV" ]; then
    CUR_EMAILS=$(tail -n +2 "$OUTPUT_CSV" | python3 -c "
import sys, csv
c = 0
for r in csv.reader(sys.stdin):
    if len(r)>9 and r[9].strip() and r[9].strip()!=';': c+=1
print(c)" 2>/dev/null || echo "0")
    [ "$CUR_EMAILS" -ge "$TARGET_EMAILS" ] && break
  fi

  HANDLE=$(head -1 "$QUEUE_FILE" 2>/dev/null || true)
  [ -z "$HANDLE" ] && { echo "Queue empty!"; break; }

  tail -n +2 "$QUEUE_FILE" > "$QUEUE_FILE.tmp" && mv "$QUEUE_FILE.tmp" "$QUEUE_FILE"

  if grep -qiF "$HANDLE" "$DONE_FILE" 2>/dev/null; then continue; fi

  echo ""
  echo "[$((PROCESSED + 1))] @${HANDLE}"

  # Pre-check subs if max_subs is set
  if [ "$MAX_SUBS" -gt 0 ]; then
    TMPF=$(mktemp)
    curl -sL "https://youtube.com/@${HANDLE}" -H "User-Agent: $UA" > "$TMPF" 2>/dev/null || true
    SUBS_NUM=$(python3 - "$TMPF" << 'PYEOF'
import re, sys
with open(sys.argv[1],'r',errors='replace') as f: html=f.read()
patterns = [
    r'"subscriberCountText":\{"simpleText":"([^"]+)"',
    r'"subscriberCountText":"([^"]+)"',
    r'"content":"([\d.]+[KMB]? subscribers)"',
    r'"subscriberCountText":\{"accessibility":\{"accessibilityData":\{"label":"([^"]+)"',
]
for p in patterns:
    m=re.search(p,html)
    if m:
        s=m.group(1).replace(' subscribers','').strip().replace(',','')
        try:
            if 'M' in s: print(int(float(s.replace('M',''))*1000000))
            elif 'K' in s: print(int(float(s.replace('K',''))*1000))
            elif 'B' in s: print(int(float(s.replace('B',''))*1000000000))
            else: print(int(float(s)))
        except: print(0)
        break
else: print(0)
PYEOF
)
    rm -f "$TMPF"

    if [ "$SUBS_NUM" -gt "$MAX_SUBS" ] 2>/dev/null; then
      echo "  ⏭ ${SUBS_NUM} subs (skip)"
      echo "$HANDLE" >> "$DONE_FILE"
      SKIPPED_BIG=$((SKIPPED_BIG + 1))
      PROCESSED=$((PROCESSED + 1))
      continue
    fi
  fi

  # Full extraction
  bash "$SCRIPT_DIR/extract_channel_data.sh" "https://youtube.com/@${HANDLE}" "$OUTPUT_CSV" 2>&1 | tail -5 || true
  echo "$HANDLE" >> "$DONE_FILE"
  PROCESSED=$((PROCESSED + 1))

  # Check email
  HAS_EMAIL=$(tail -1 "$OUTPUT_CSV" 2>/dev/null | python3 -c "
import sys,csv
for r in csv.reader(sys.stdin):
    print('yes' if len(r)>9 and r[9].strip() and r[9].strip()!=';' else 'no')
    break
" 2>/dev/null || echo "no")
  [ "$HAS_EMAIL" = "yes" ] && EMAILS_RUN=$((EMAILS_RUN + 1))

  # Expand via related channels every 8th
  if [ $((PROCESSED % 8)) -eq 0 ] && [ "$HAS_EMAIL" = "yes" ]; then
    echo "  🔄 Related channels from @${HANDLE}..."
    RELATED=$(bash "$SCRIPT_DIR/find_related_channels.sh" "https://youtube.com/@${HANDLE}" 25 2>&1 | grep "^HANDLE:" | sed 's/HANDLE:@//' || true)
    RNEW=0
    while IFS= read -r rh; do
      [ -z "$rh" ] && continue
      if ! grep -qiF "$rh" "$DONE_FILE" 2>/dev/null && ! grep -qiF "$rh" "$QUEUE_FILE" 2>/dev/null; then
        echo "$rh" >> "$QUEUE_FILE"
        RNEW=$((RNEW + 1))
      fi
    done <<< "$RELATED"
    echo "  +$RNEW related"
    sleep 1
  fi

  sleep 0.5
done

# --- Status ---
DONE_COUNT=$(wc -l < "$DONE_FILE" | tr -d ' ')
QUEUE_COUNT=$(wc -l < "$QUEUE_FILE" | tr -d ' ')
FINAL_EMAILS=0
TOTAL_ROWS=0
if [ -f "$OUTPUT_CSV" ]; then
  read TOTAL_ROWS FINAL_EMAILS <<< $(tail -n +2 "$OUTPUT_CSV" | python3 -c "
import sys,csv
t=e=0
for r in csv.reader(sys.stdin):
    t+=1
    if len(r)>9 and r[9].strip() and r[9].strip()!=';': e+=1
print(t,e)
" 2>/dev/null || echo "0 0")
fi

echo ""
echo "=== Run Complete ==="
echo "  Processed: $PROCESSED | Emails this run: $EMAILS_RUN | Skipped (too big): $SKIPPED_BIG"
echo "  Total: $TOTAL_ROWS channels | $FINAL_EMAILS emails | Queue: $QUEUE_COUNT"
echo "  Target: $TARGET_EMAILS | CSV: $OUTPUT_CSV"

cat > "$STATE_FILE" << EOF
{
  "last_run": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "total_channels": $TOTAL_ROWS,
  "total_emails": $FINAL_EMAILS,
  "target_emails": $TARGET_EMAILS,
  "queue_size": $QUEUE_COUNT,
  "total_checked": $DONE_COUNT
}
EOF

echo "=== End $(date) ==="
