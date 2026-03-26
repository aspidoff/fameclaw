#!/bin/bash
# Extract creators promoting products on TikTok Shop via Googlebot SSR
# Scrapes product page for creator videos and product info
#
# Usage: ./extract_tiktokshop.sh <product_url_or_id> [output_file.csv]
# Example: ./extract_tiktokshop.sh "https://www.tiktok.com/shop/pdp/some-product/1729398461940339414" shop.csv

set -euo pipefail

UA="Googlebot/2.1 (+http://www.google.com/bot.html)"

INPUT="${1:-}"
OUTPUT="${2:-tiktokshop_data.csv}"
TMPDIR_WORK=$(mktemp -d)
trap "rm -rf $TMPDIR_WORK" EXIT

if [ -z "$INPUT" ]; then
  echo "Usage: $0 <product_url_or_id> [output_file.csv]"
  exit 1
fi

# Accept full URL or just product ID
if echo "$INPUT" | grep -q 'tiktok\.com'; then
  PRODUCT_URL=$(echo "$INPUT" | sed 's/[?#].*//' | sed 's:/*$::')
else
  PRODUCT_URL="https://www.tiktok.com/shop/pdp/-/${INPUT}"
fi

echo "=== TikTok Shop Extractor ==="
echo "Product: $PRODUCT_URL"
echo ""

# --- Phase 1: Fetch product page ---
echo "[1/2] Fetching product page..."
curl -sL "$PRODUCT_URL" -H "User-Agent: $UA" --max-time 15 > "$TMPDIR_WORK/page.html" 2>/dev/null || true

PAGE_SIZE=$(wc -c < "$TMPDIR_WORK/page.html" | tr -d ' ')
if [ "$PAGE_SIZE" -lt 500 ]; then
  echo "Error: Page too small ($PAGE_SIZE bytes). Product may not exist or TikTok blocked the request."
  exit 1
fi

# --- Phase 2: Extract product info + creator videos ---
echo "[2/2] Extracting data..."
PRODUCT_URL_FOR_PYTHON="$PRODUCT_URL" python3 - "$TMPDIR_WORK/page.html" "$TMPDIR_WORK/results.csv" "$TMPDIR_WORK/product.txt" << 'PYEOF'
import sys, re, json, csv, io

html_file, csv_file, product_file = sys.argv[1], sys.argv[2], sys.argv[3]

with open(html_file, 'r', errors='replace') as f:
    html = f.read()

# --- Extract JSON blobs from script tags ---
json_blobs = []
for m in re.finditer(r'<script[^>]*>\s*({.+?})\s*</script>', html, re.DOTALL):
    try:
        blob = json.loads(m.group(1))
        json_blobs.append(blob)
    except:
        pass

# Also try __NEXT_DATA__ / SIGI_STATE patterns
for pattern in [r'__NEXT_DATA__\s*=\s*({.+?});\s*</script>',
                r'SIGI_STATE\s*=\s*({.+?});\s*</script>',
                r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>\s*({.+?})\s*</script>']:
    for m in re.finditer(pattern, html, re.DOTALL):
        try:
            blob = json.loads(m.group(1))
            json_blobs.append(blob)
        except:
            pass

# --- Recursively search for product and video data ---
product_info = {}
creator_videos = []

def find_deep(obj, key):
    """Recursively find all values for a given key."""
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                results.append(v)
            results.extend(find_deep(v, key))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(find_deep(item, key))
    return results

def extract_product(obj):
    """Try to extract product info from a dict."""
    global product_info
    if not isinstance(obj, dict):
        return
    # Look for product-like objects
    if 'sold_count' in obj or 'soldCount' in obj or 'sales' in obj:
        product_info['sold_count'] = str(obj.get('sold_count', obj.get('soldCount', obj.get('sales', ''))))
    if 'price' in obj:
        p = obj['price']
        if isinstance(p, dict):
            product_info['price'] = str(p.get('original_price', p.get('originalPrice', p.get('price', ''))))
        else:
            product_info['price'] = str(p)
    if 'title' in obj and not product_info.get('name') and len(str(obj.get('title', ''))) > 10:
        product_info['name'] = str(obj['title'])
    if 'name' in obj and not product_info.get('name') and len(str(obj.get('name', ''))) > 10:
        product_info['name'] = str(obj['name'])
    if 'review_count' in obj or 'reviewCount' in obj:
        product_info['reviews'] = str(obj.get('review_count', obj.get('reviewCount', '')))
    if 'seller' in obj and isinstance(obj['seller'], dict):
        product_info['seller_name'] = obj['seller'].get('name', obj['seller'].get('shop_name', ''))
    if 'shop_name' in obj or 'shopName' in obj:
        product_info['seller_name'] = str(obj.get('shop_name', obj.get('shopName', '')))

def extract_videos(obj, path=""):
    """Recursively find creator video entries."""
    if isinstance(obj, dict):
        # A video entry typically has author_name/author_id or similar
        has_author = any(k in obj for k in ['author_name', 'authorName', 'author', 'nickname'])
        has_play = any(k in obj for k in ['play_count', 'playCount', 'plays', 'view_count', 'viewCount'])
        if has_author and has_play:
            video = {}
            video['author_name'] = str(obj.get('author_name', obj.get('authorName', obj.get('nickname', ''))))
            if not video['author_name'] and isinstance(obj.get('author'), dict):
                video['author_name'] = str(obj['author'].get('nickname', obj['author'].get('name', '')))
            video['author_id'] = str(obj.get('author_id', obj.get('authorId', obj.get('author_uid', ''))))
            if not video['author_id'] and isinstance(obj.get('author'), dict):
                video['author_id'] = str(obj['author'].get('id', obj['author'].get('uid', '')))
            video['play_count'] = str(obj.get('play_count', obj.get('playCount', obj.get('plays', obj.get('view_count', obj.get('viewCount', '0'))))))
            video['like_count'] = str(obj.get('like_count', obj.get('likeCount', obj.get('likes', obj.get('digg_count', obj.get('diggCount', '0'))))))
            video['upload_time'] = str(obj.get('upload_time', obj.get('uploadTime', obj.get('createTime', obj.get('create_time', '')))))
            video['content_url'] = str(obj.get('content_url', obj.get('contentUrl', obj.get('video_url', obj.get('url', '')))))
            video['title'] = str(obj.get('title', obj.get('desc', obj.get('description', ''))))[:200]
            if video['author_name'] or video['author_id']:
                creator_videos.append(video)
            return  # don't recurse into already-extracted
        for k, v in obj.items():
            extract_product(obj)
            extract_videos(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            extract_videos(item, f"{path}[{i}]")

for blob in json_blobs:
    extract_product(blob)
    extract_videos(blob)

# --- Fallback: try structured data (JSON-LD) ---
for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>\s*({.+?})\s*</script>', html, re.DOTALL):
    try:
        ld = json.loads(m.group(1))
        if isinstance(ld, dict):
            if ld.get('@type') == 'Product' or 'product' in str(ld.get('@type', '')).lower():
                if not product_info.get('name'):
                    product_info['name'] = str(ld.get('name', ''))
                if not product_info.get('price'):
                    offers = ld.get('offers', {})
                    if isinstance(offers, dict):
                        product_info['price'] = str(offers.get('price', ''))
    except:
        pass

# --- Fallback: regex extraction from raw HTML for product name ---
if not product_info.get('name'):
    m = re.search(r'"product_name"\s*:\s*"([^"]+)"', html)
    if m:
        product_info['name'] = m.group(1)

# --- Fallback: derive product name from URL slug ---
if not product_info.get('name') or '<a ' in product_info.get('name', ''):
    import os
    url = os.environ.get('PRODUCT_URL_FOR_PYTHON', '')
    if not url:
        # Try to get from the HTML og:url or canonical
        um = re.search(r'<link[^>]*rel="canonical"[^>]*href="([^"]+)"', html)
        if um:
            url = um.group(1)
    if '/shop/pdp/' in url:
        slug = url.split('/shop/pdp/')[-1].rsplit('/', 1)[0]
        if slug and slug != '-':
            product_info['name'] = slug.replace('-', ' ').title()

# --- Fallback: regex extraction for sold_count ---
if not product_info.get('sold_count'):
    m = re.search(r'"sold_count"\s*:\s*["\']?(\d+)', html)
    if m:
        product_info['sold_count'] = m.group(1)
    else:
        m = re.search(r'([\d,.]+[KkMm]?)\s+sold', html)
        if m:
            product_info['sold_count'] = m.group(1)

# --- Fallback: regex extraction for creator videos ---
if not creator_videos:
    # Try finding author data in raw HTML
    for m in re.finditer(r'"author_name"\s*:\s*"([^"]*)"', html):
        name = m.group(1)
        start = max(0, m.start() - 500)
        end = min(len(html), m.end() + 500)
        ctx = html[start:end]
        video = {'author_name': name}
        am = re.search(r'"author_id"\s*:\s*"?(\d+)', ctx)
        video['author_id'] = am.group(1) if am else ''
        pm = re.search(r'"play_count"\s*:\s*"?(\d+)', ctx)
        video['play_count'] = pm.group(1) if pm else '0'
        lm = re.search(r'"like_count"\s*:\s*"?(\d+)', ctx)
        video['like_count'] = lm.group(1) if lm else '0'
        tm = re.search(r'"upload_time"\s*:\s*"?(\d+)', ctx)
        video['upload_time'] = tm.group(1) if tm else ''
        um = re.search(r'"content_url"\s*:\s*"([^"]*)"', ctx)
        video['content_url'] = um.group(1) if um else ''
        dm = re.search(r'"title"\s*:\s*"([^"]*)"', ctx)
        video['title'] = dm.group(1)[:200] if dm else ''
        if video['author_name'] or video['author_id']:
            creator_videos.append(video)

# --- Write product info ---
with open(product_file, 'w') as f:
    for k, v in product_info.items():
        f.write(f'{k}={v}\n')

# --- Write creator CSV ---
pname = product_info.get('name', '').replace('"', '""')
pprice = product_info.get('price', '')
psold = product_info.get('sold_count', '')

with open(csv_file, 'w', newline='') as f:
    w = csv.writer(f)
    for v in creator_videos:
        w.writerow([
            v.get('author_name', ''),
            v.get('author_id', ''),
            v.get('play_count', '0'),
            v.get('like_count', '0'),
            v.get('upload_time', ''),
            pname,
            pprice,
            psold,
            v.get('content_url', ''),
            v.get('title', ''),
        ])

print(f"CREATORS_FOUND={len(creator_videos)}")
PYEOF

# Read product info
get_stat() { grep "^$1=" "$TMPDIR_WORK/product.txt" 2>/dev/null | sed "s/^$1=//" | head -1 || echo ""; }

PRODUCT_NAME=$(get_stat name)
PRODUCT_PRICE=$(get_stat price)
PRODUCT_SOLD=$(get_stat sold_count)
PRODUCT_REVIEWS=$(get_stat reviews)
SELLER_NAME=$(get_stat seller_name)

echo ""
echo "  Product:    ${PRODUCT_NAME:-n/a}"
echo "  Price:      ${PRODUCT_PRICE:-n/a}"
echo "  Sold:       ${PRODUCT_SOLD:-n/a}"
echo "  Reviews:    ${PRODUCT_REVIEWS:-n/a}"
echo "  Seller:     ${SELLER_NAME:-n/a}"
echo ""

# Count extracted creators
CREATOR_COUNT=0
if [ -f "$TMPDIR_WORK/results.csv" ]; then
  CREATOR_COUNT=$(wc -l < "$TMPDIR_WORK/results.csv" | tr -d ' ')
fi

echo "  Creators found: $CREATOR_COUNT"

if [ "$CREATOR_COUNT" -eq 0 ]; then
  echo ""
  echo "No creator videos found on this product page."
  exit 0
fi

# --- Write to output CSV ---
csv_escape() { printf '"%s"' "$(echo "$1" | sed 's/"/""/g')"; }

if [ ! -s "$OUTPUT" ]; then
  echo "author_name,author_id,play_count,like_count,upload_time,product_name,product_price,product_sold_count,content_url,title" > "$OUTPUT"
fi

# Append extracted rows
cat "$TMPDIR_WORK/results.csv" >> "$OUTPUT"

echo ""
echo "Saved $CREATOR_COUNT creators to $OUTPUT"
echo ""
echo "=== Summary ==="
echo "  Product: ${PRODUCT_NAME:-unknown}"
echo "  Creators: $CREATOR_COUNT"
[ -n "$PRODUCT_SOLD" ] && echo "  Sold: $PRODUCT_SOLD"
