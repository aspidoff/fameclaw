#!/bin/bash
# FameClaw — TikTok Shop Creator Prospector
# Discovers creators promoting products on TikTok Shop, deduplicates by author_id
#
# Usage:
#   ./prospect_tiktokshop.sh --product-urls urls.txt [--target 100] [output.csv]
#   ./prospect_tiktokshop.sh --category "beauty" [--target 100] [output.csv]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UA="Googlebot/2.1 (+http://www.google.com/bot.html)"

# --- Defaults ---
TARGET=100
OUTPUT_CSV=""
PRODUCT_URLS_FILE=""
CATEGORY=""
RATE_LIMIT=2

# --- Parse args ---
POSITIONAL=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --product-urls)
      PRODUCT_URLS_FILE="$2"; shift 2
      ;;
    --category)
      CATEGORY="$2"; shift 2
      ;;
    --target)
      TARGET="$2"; shift 2
      ;;
    *)
      POSITIONAL+=("$1"); shift
      ;;
  esac
done

# Positional arg = output file
if [ ${#POSITIONAL[@]} -gt 0 ]; then
  OUTPUT_CSV="${POSITIONAL[0]}"
fi
[ -z "$OUTPUT_CSV" ] && OUTPUT_CSV="tiktokshop_creators.csv"

if [ -z "$PRODUCT_URLS_FILE" ] && [ -z "$CATEGORY" ]; then
  echo "Usage: $0 --product-urls <file> [--target N] [output.csv]"
  echo "       $0 --category <category> [--target N] [output.csv]"
  exit 1
fi

TMPDIR_WORK=$(mktemp -d)
trap "rm -rf $TMPDIR_WORK" EXIT

echo "=== TikTok Shop Creator Prospector ==="
echo "Target: $TARGET unique creators"
echo "Output: $OUTPUT_CSV"
echo ""

# --- Category mode: discover products first ---
if [ -n "$CATEGORY" ]; then
  echo "[Discovery] Fetching TikTok Shop category: $CATEGORY"
  PRODUCT_URLS_FILE="$TMPDIR_WORK/product_urls.txt"
  touch "$PRODUCT_URLS_FILE"

  # Try shop.tiktok.com main page or category pages
  for SHOP_URL in "https://shop.tiktok.com" "https://shop.tiktok.com/search?q=${CATEGORY}" "https://www.tiktok.com/shop/search?q=${CATEGORY}"; do
    echo "  Trying: $SHOP_URL"
    curl -sL "$SHOP_URL" -H "User-Agent: $UA" --max-time 15 > "$TMPDIR_WORK/shop.html" 2>/dev/null || continue

    # Extract product URLs/IDs from the page
    python3 - "$TMPDIR_WORK/shop.html" "$TMPDIR_WORK/discovered.txt" << 'PYEOF'
import sys, re, json

html_file, out_file = sys.argv[1], sys.argv[2]

with open(html_file, 'r', errors='replace') as f:
    html = f.read()

urls = set()

# Find product URLs directly in HTML
for m in re.finditer(r'(?:href|url)\s*[=:]\s*["\']?(https?://(?:www\.)?tiktok\.com/shop/pdp/[^"\'>\s]+)', html):
    urls.add(m.group(1).split('?')[0])

# Find product IDs in JSON data
for m in re.finditer(r'<script[^>]*>\s*({.+?})\s*</script>', html, re.DOTALL):
    try:
        blob = json.loads(m.group(1))
        text = json.dumps(blob)
        for pm in re.finditer(r'"product_id"\s*:\s*"(\d+)"', text):
            urls.add(f"https://www.tiktok.com/shop/pdp/-/{pm.group(1)}")
        # Also look for productList pattern
        for pm in re.finditer(r'"id"\s*:\s*"(\d{15,})"', text):
            urls.add(f"https://www.tiktok.com/shop/pdp/-/{pm.group(1)}")
    except:
        pass

# Regex fallback for product IDs in raw HTML
for m in re.finditer(r'/shop/pdp/[^/]+/(\d+)', html):
    urls.add(f"https://www.tiktok.com/shop/pdp/-/{m.group(1)}")

with open(out_file, 'w') as f:
    for u in sorted(urls):
        f.write(u + '\n')

print(f"Discovered {len(urls)} products")
PYEOF

    if [ -s "$TMPDIR_WORK/discovered.txt" ]; then
      cat "$TMPDIR_WORK/discovered.txt" >> "$PRODUCT_URLS_FILE"
    fi
    sleep "$RATE_LIMIT"
  done

  # Deduplicate product URLs
  sort -u "$PRODUCT_URLS_FILE" -o "$PRODUCT_URLS_FILE"

  PRODUCT_COUNT=$(wc -l < "$PRODUCT_URLS_FILE" | tr -d ' ')
  echo ""
  echo "  Discovered $PRODUCT_COUNT product URLs"
  echo ""

  if [ "$PRODUCT_COUNT" -eq 0 ]; then
    echo "No products found for category '$CATEGORY'. Try --product-urls mode instead."
    exit 1
  fi
fi

# --- Process product URLs ---
TOTAL_PRODUCTS=$(wc -l < "$PRODUCT_URLS_FILE" | tr -d ' ')
echo "Processing $TOTAL_PRODUCTS products..."
echo ""

# Intermediate CSV with per-video rows
RAW_CSV="$TMPDIR_WORK/raw.csv"

PROCESSED=0
while IFS= read -r url; do
  [ -z "$url" ] && continue
  # Skip comments
  [[ "$url" =~ ^# ]] && continue

  PROCESSED=$((PROCESSED + 1))
  echo "[$PROCESSED/$TOTAL_PRODUCTS] $url"

  bash "$SCRIPT_DIR/extract_tiktokshop.sh" "$url" "$RAW_CSV" 2>/dev/null || {
    echo "  (skipped — extraction failed)"
    continue
  }

  # Rate limit
  if [ "$PROCESSED" -lt "$TOTAL_PRODUCTS" ]; then
    sleep "$RATE_LIMIT"
  fi
done < "$PRODUCT_URLS_FILE"

echo ""

# --- Deduplicate and aggregate by author_id ---
if [ ! -s "$RAW_CSV" ]; then
  echo "No creator data extracted."
  exit 1
fi

echo "Deduplicating creators by author_id..."

python3 - "$RAW_CSV" "$OUTPUT_CSV" "$TARGET" << 'PYEOF'
import sys, csv
from collections import defaultdict

raw_file, out_file, target = sys.argv[1], sys.argv[2], int(sys.argv[3])

# Read all rows (skip header)
creators = defaultdict(lambda: {
    'author_name': '',
    'total_play_count': 0,
    'total_like_count': 0,
    'products': set(),
    'total_est_gmv_usd': 0.0,
    'conversion_rates': [],
})

with open(raw_file, 'r', newline='') as f:
    reader = csv.reader(f)
    for row in reader:
        if len(row) < 8:
            continue
        # Skip header rows
        if row[0] == 'author_name':
            continue

        author_name = row[0]
        author_id = row[1]
        if not author_id and not author_name:
            continue

        key = author_id if author_id else author_name
        c = creators[key]
        if not c['author_name'] and author_name:
            c['author_name'] = author_name

        try:
            c['total_play_count'] += int(row[2]) if row[2] else 0
        except ValueError:
            pass
        try:
            c['total_like_count'] += int(row[3]) if row[3] else 0
        except ValueError:
            pass

        product_name = row[5] if len(row) > 5 else ''
        if product_name:
            c['products'].add(product_name)

        # GMV columns (indices 10, 11, 12)
        if len(row) > 11:
            est_gmv = row[11]
            if est_gmv and est_gmv != 'n/a':
                try:
                    c['total_est_gmv_usd'] += float(est_gmv)
                except ValueError:
                    pass
        if len(row) > 12:
            est_conv = row[12]
            if est_conv and est_conv != 'n/a':
                try:
                    c['conversion_rates'].append(float(est_conv))
                except ValueError:
                    pass

# Sort by total_est_gmv_usd descending (highest GMV first)
sorted_creators = sorted(
    creators.items(),
    key=lambda x: x[1]['total_est_gmv_usd'],
    reverse=True
)[:target]

# Write output
with open(out_file, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['author_name', 'author_id', 'total_play_count', 'total_like_count', 'num_products_promoted', 'product_names', 'total_est_gmv_usd', 'avg_conversion_rate'])
    for author_id, c in sorted_creators:
        product_list = '; '.join(sorted(c['products']))
        rates = c['conversion_rates']
        avg_conv = f"{sum(rates) / len(rates):.8f}" if rates else 'n/a'
        total_gmv = f"{c['total_est_gmv_usd']:.2f}" if c['total_est_gmv_usd'] > 0 else 'n/a'
        w.writerow([
            c['author_name'],
            author_id,
            c['total_play_count'],
            c['total_like_count'],
            len(c['products']),
            product_list,
            total_gmv,
            avg_conv,
        ])

print(f"Unique creators: {len(sorted_creators)}")
PYEOF

UNIQUE_COUNT=$(( $(wc -l < "$OUTPUT_CSV" | tr -d ' ') - 1 ))
[ "$UNIQUE_COUNT" -lt 0 ] && UNIQUE_COUNT=0

echo ""
echo "=== Done ==="
echo "Products processed: $PROCESSED"
echo "Unique creators: $UNIQUE_COUNT"
echo "Output: $OUTPUT_CSV"
