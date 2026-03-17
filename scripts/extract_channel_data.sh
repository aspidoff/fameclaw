#!/bin/bash
# Extract YouTube channel data: email, subscribers, avg views, and video stats
# Appends a row to a CSV file
#
# Usage: ./extract_channel_data.sh <youtube_channel_url> [output_file]
# Example: ./extract_channel_data.sh "https://youtube.com/@tbpnlive" channels.csv

set -euo pipefail

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
EMAIL_RE='[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
JUNK_EMAILS='example\.\|email\.com\|sentry\.\|domain\.\|wixpress\.\|placeholder\|noreply\|no-reply\|@google\.\|@youtube\.\|@gstatic\.'

CHANNEL_URL="${1:-}"
OUTPUT="${2:-channel_data.csv}"
TMPDIR_WORK=$(mktemp -d)
trap "rm -rf $TMPDIR_WORK" EXIT

if [ -z "$CHANNEL_URL" ]; then
  echo "Usage: $0 <youtube_channel_url> [output_file.csv]"
  exit 1
fi

CHANNEL_URL=$(echo "$CHANNEL_URL" | sed 's/[?#].*//' | sed 's:/*$::')

echo "=== YouTube Channel Data Extractor ==="
echo "Channel: $CHANNEL_URL"
echo ""

# Fetch pages and save to temp files
echo "[1/3] Fetching channel..."
curl -sL "$CHANNEL_URL" -H "User-Agent: $UA" > "$TMPDIR_WORK/main.html" 2>/dev/null || true
curl -sL "${CHANNEL_URL}/videos" -H "User-Agent: $UA" > "$TMPDIR_WORK/videos.html" 2>/dev/null || true

# Extract stats with Python (reads from temp files)
echo "[2/3] Extracting stats..."
python3 - "$TMPDIR_WORK/main.html" "$TMPDIR_WORK/videos.html" "$CHANNEL_URL" "$TMPDIR_WORK/stats.txt" << 'PYEOF'
import sys, re, urllib.parse

main_file, videos_file, channel_url, out_file = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

with open(main_file, 'r', errors='replace') as f:
    yt = f.read()
with open(videos_file, 'r', errors='replace') as f:
    vids = f.read()

r = {}

# Name
m = re.search(r'"channelMetadataRenderer":\{"title":"([^"]+)"', yt)
if not m:
    m = re.search(r'"pageTitle":"([^"]+)"', yt)
if not m:
    m = re.search(r'"ownerChannelName":"([^"]+)"', yt)
r['name'] = m.group(1) if m else 'unknown'

# Handle
m = re.search(r'@([a-zA-Z0-9_-]+)', channel_url)
r['handle'] = '@' + m.group(1) if m else ''

# Subscribers
for p in [r'"subscriberCountText":"([^"]+)"', r'"content":"([\d.]+[KMB]? subscribers)"']:
    m = re.search(p, yt)
    if m:
        r['subscribers'] = m.group(1).replace(' subscribers', '').strip()
        break
else:
    r['subscribers'] = ''

# Total videos
for p in [r'"([\d,.]+[KMB]?) videos"', r'([\d,.]+[KMB]?) videos']:
    m = re.search(p, yt)
    if m:
        r['total_videos'] = m.group(1).strip()
        break
else:
    r['total_videos'] = ''

# View counts from both pages
both = yt + vids
views = []

# Full view counts
for m in re.finditer(r'"viewCountText":\{"simpleText":"([\d,]+) views?"', both):
    try: views.append(int(m.group(1).replace(',', '')))
    except: pass

# Short view counts (e.g., "18K views")
for m in re.finditer(r'"simpleText":"([\d.]+)([KMB])? views?"', both):
    try:
        n = float(m.group(1))
        mult = {'K': 1000, 'M': 1_000_000, 'B': 1_000_000_000}.get(m.group(2) or '', 1)
        views.append(int(n * mult))
    except: pass

# Deduplicate (some appear twice)
views = sorted(set(views))

if views:
    r['avg_views'] = str(int(sum(views) / len(views)))
    r['median_views'] = str(views[len(views) // 2])
    r['min_views'] = str(min(views))
    r['max_views'] = str(max(views))
    r['videos_sampled'] = str(len(views))
else:
    r['avg_views'] = r['median_views'] = r['min_views'] = r['max_views'] = ''
    r['videos_sampled'] = '0'

# Description
m = re.search(r'channelMetadataRenderer.*?"description":"([^"]*)"', yt)
r['description'] = m.group(1).replace('\\n', ' ').strip()[:200] if m else ''

# External links
urls = set()
for m in re.finditer(r'youtube\.com/redirect\?[^"]+', yt):
    qm = re.search(r'[?&]q=([^&"]+)', m.group(0))
    if qm:
        urls.add(urllib.parse.unquote(qm.group(1)))
r['external_links'] = ' | '.join(sorted(urls))
r['channel_url'] = channel_url

with open(out_file, 'w') as f:
    for k, v in r.items():
        f.write(f'{k}={v}\n')
PYEOF

# Read stats
get_stat() { grep "^$1=" "$TMPDIR_WORK/stats.txt" 2>/dev/null | sed "s/^$1=//" | head -1 || echo ""; }

NAME=$(get_stat name)
HANDLE_VAL=$(get_stat handle)
SUBS=$(get_stat subscribers)
TOTAL_VIDS=$(get_stat total_videos)
AVG_VIEWS=$(get_stat avg_views)
MEDIAN_VIEWS=$(get_stat median_views)
MIN_VIEWS=$(get_stat min_views)
MAX_VIEWS=$(get_stat max_views)
SAMPLED=$(get_stat videos_sampled)
DESC=$(get_stat description)
EXT_LINKS=$(get_stat external_links)

echo "  Name:        $NAME"
echo "  Handle:      $HANDLE_VAL"
echo "  Subscribers: $SUBS"
echo "  Videos:      $TOTAL_VIDS"
echo "  Avg views:   ${AVG_VIEWS:-n/a} (sampled ${SAMPLED:-0} videos)"
echo "  Median:      ${MEDIAN_VIEWS:-n/a}"
echo "  Range:       ${MIN_VIEWS:-n/a} - ${MAX_VIEWS:-n/a}"

# --- Find emails ---
echo ""
echo "[3/3] Finding emails..."
YT_EMAILS=$(grep -oiE "$EMAIL_RE" "$TMPDIR_WORK/main.html" 2>/dev/null | sort -u | grep -v "$JUNK_EMAILS" || true)

HANDLE_CLEAN=$(echo "$HANDLE_VAL" | sed 's/@//')
BASE_HANDLE=$(echo "$HANDLE_CLEAN" | sed -E 's/(live|official|hq|tv|channel|yt|tube)$//i' | tr '[:upper:]' '[:lower:]')
VANITY_EMAILS=""
for d in "${BASE_HANDLE}.com" "${HANDLE_CLEAN}.com"; do
  CODE=$(curl -sL -o /dev/null -w "%{http_code}" "https://$d" --max-time 5 -H "User-Agent: $UA" 2>/dev/null || echo "000")
  if [ "$CODE" -ge 200 ] 2>/dev/null && [ "$CODE" -lt 500 ] 2>/dev/null; then
    # Scan root + common contact pages
    FOUND=""
    for path in "/" "/contact" "/about" "/contact-us"; do
      PAGE_EMAILS=$(curl -sL "https://${d}${path}" --max-time 8 -H "User-Agent: $UA" 2>/dev/null | grep -oiE "$EMAIL_RE" | sort -u | grep -v "$JUNK_EMAILS" || true)
      [ -n "$PAGE_EMAILS" ] && FOUND=$(printf "%s\n%s" "$FOUND" "$PAGE_EMAILS")
    done
    FOUND=$(echo "$FOUND" | sort -fu | grep -v '^$' || true)
    if [ -n "$FOUND" ]; then
      echo "  From $d:"
      echo "$FOUND" | while read -r e; do echo "    ✅ $e"; done
      VANITY_EMAILS=$(printf "%s\n%s" "$VANITY_EMAILS" "$FOUND")
    fi
  fi
done

ALL_EMAILS=$(printf "%s\n%s" "$YT_EMAILS" "$VANITY_EMAILS" | sort -fu | grep -v '^$' || true)
EMAIL_STR=$(echo "$ALL_EMAILS" | tr '\n' '; ' | sed 's/; $//')

# --- Write CSV ---
echo ""
if [ ! -s "$OUTPUT" ]; then
  echo "channel_name,handle,subscribers,total_videos,avg_views,median_views,min_views,max_views,videos_sampled,email,description,external_links,channel_url" > "$OUTPUT"
fi

csv_escape() { printf '"%s"' "$(echo "$1" | sed 's/"/""/g')"; }

ROW="$(csv_escape "$NAME"),$(csv_escape "$HANDLE_VAL"),$(csv_escape "$SUBS"),$(csv_escape "$TOTAL_VIDS"),$(csv_escape "$AVG_VIEWS"),$(csv_escape "$MEDIAN_VIEWS"),$(csv_escape "$MIN_VIEWS"),$(csv_escape "$MAX_VIEWS"),$(csv_escape "$SAMPLED"),$(csv_escape "$EMAIL_STR"),$(csv_escape "$DESC"),$(csv_escape "$EXT_LINKS"),$(csv_escape "$CHANNEL_URL")"
echo "$ROW" >> "$OUTPUT"

echo "✅ Saved to $OUTPUT"
echo ""
echo "=== Summary ==="
echo "  $NAME ($HANDLE_VAL)"
echo "  📊 $SUBS subs | $TOTAL_VIDS videos | ~${AVG_VIEWS:-?} avg views"
echo "  📧 ${EMAIL_STR:-no email found}"
