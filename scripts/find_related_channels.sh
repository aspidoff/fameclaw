#!/bin/bash
# Find related YouTube channels by checking recommended/related videos
# on a creator's top 3 most-viewed videos.
#
# Usage: ./find_related_channels.sh <youtube_channel_url> [count]
# Example: ./find_related_channels.sh "https://youtube.com/@DerekKumo" 10
#
# Outputs unique channel handles sorted by frequency (most recommended first)

set -euo pipefail

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
CHANNEL_URL="${1:-}"
COUNT="${2:-10}"
TMPDIR_WORK=$(mktemp -d)
trap "rm -rf $TMPDIR_WORK" EXIT

if [ -z "$CHANNEL_URL" ]; then
  echo "Usage: $0 <youtube_channel_url> [count]"
  exit 1
fi

CHANNEL_URL=$(echo "$CHANNEL_URL" | sed 's/[?#].*//' | sed 's:/*$::')

echo "=== Find Related Channels ==="
echo "Source: $CHANNEL_URL"
echo ""

# Step 1: Get channel's videos page and find top videos by view count
echo "[1/3] Fetching channel videos..."
# Sort by popular to get highest-viewed videos
curl -sL "${CHANNEL_URL}/videos?view=0&sort=p" -H "User-Agent: $UA" > "$TMPDIR_WORK/videos.html" 2>/dev/null || true

# Extract source channel handle to exclude it
SOURCE_HANDLE=$(echo "$CHANNEL_URL" | grep -oE '@[^/]+' | sed 's/@//' || true)
if [ -z "$SOURCE_HANDLE" ]; then
  # Try to get it from the page
  SOURCE_HANDLE=$(python3 -c "
import re
with open('$TMPDIR_WORK/videos.html', 'r', errors='replace') as f:
    html = f.read()
m = re.search(r'\"vanityChannelUrl\":\"[^\"]*/@([^\"]+)\"', html)
print(m.group(1) if m else '')
" 2>/dev/null || true)
fi
echo "  Source handle: @${SOURCE_HANDLE}"

# Get video IDs with view counts, pick top 3
python3 - "$TMPDIR_WORK/videos.html" "$TMPDIR_WORK/top_videos.txt" << 'PYEOF'
import sys, re

with open(sys.argv[1], 'r', errors='replace') as f:
    html = f.read()

# Find videos with view counts
videos = {}
# Pattern: videoId near viewCountText
for m in re.finditer(r'"videoId":"([^"]+)"', html):
    vid = m.group(1)
    if vid not in videos:
        videos[vid] = 0

# Get view counts - they appear in order matching videos
view_texts = re.findall(r'"viewCountText":\{"simpleText":"([\d,]+) views?"', html)
short_views = re.findall(r'"simpleText":"([\d.]+)([KMB]) views?"', html)

# Map views to video IDs (they appear in order)
vid_list = list(dict.fromkeys(re.findall(r'"videoId":"([^"]+)"', html)))

all_views = []
for vt in view_texts:
    try: all_views.append(int(vt.replace(',', '')))
    except: pass
for sv, mult in short_views:
    try:
        m = {'K': 1000, 'M': 1_000_000, 'B': 1_000_000_000}[mult]
        all_views.append(int(float(sv) * m))
    except: pass

# Pair them up
paired = []
for i, vid in enumerate(vid_list[:len(all_views)]):
    paired.append((vid, all_views[i] if i < len(all_views) else 0))

# Sort by views descending, take top 3
paired.sort(key=lambda x: x[1], reverse=True)
top3 = paired[:3]

with open(sys.argv[2], 'w') as f:
    for vid, views in top3:
        f.write(f'{vid}\t{views}\n')
        print(f'  Video {vid} ({views:,} views)')
PYEOF

echo ""
echo "[2/3] Fetching related videos from top 3..."

# Step 2: For each top video, fetch the watch page and extract related video channels
RELATED_FILE="$TMPDIR_WORK/related_channels.txt"
touch "$RELATED_FILE"

while IFS=$'\t' read -r VIDEO_ID VIEW_COUNT; do
  [ -z "$VIDEO_ID" ] && continue
  echo "  Scanning related videos for $VIDEO_ID..."
  
  curl -sL "https://www.youtube.com/watch?v=${VIDEO_ID}" \
    -H "User-Agent: $UA" > "$TMPDIR_WORK/watch_${VIDEO_ID}.html" 2>/dev/null || true
  
  python3 - "$TMPDIR_WORK/watch_${VIDEO_ID}.html" "$SOURCE_HANDLE" >> "$RELATED_FILE" << 'PYEOF'
import sys, re

with open(sys.argv[1], 'r', errors='replace') as f:
    html = f.read()
source_handle = sys.argv[2].lower()

# Extract channels from related/recommended videos
# Look for compactVideoRenderer (sidebar recommendations)
channels = {}

# Pattern 1: channel info in compact video renderers
for m in re.finditer(
    r'"compactVideoRenderer":\{.*?"videoId":"([^"]+)".*?"(?:longBylineText|shortBylineText)":\{"runs":\[\{"text":"([^"]+)".*?"canonicalBaseUrl":"/@([^"]+)"',
    html
):
    vid, name, handle = m.group(1), m.group(2), m.group(3)
    if handle.lower() != source_handle:
        channels[handle] = name

# Pattern 2: broader - any channel reference in recommendation sections  
for m in re.finditer(r'"ownerText":\{"runs":\[\{"text":"([^"]+)".*?"canonicalBaseUrl":"/@([^"]+)"', html):
    name, handle = m.group(1), m.group(2)
    if handle.lower() != source_handle:
        channels[handle] = name

# Pattern 3: handle near a channel name (reversed order)
for m in re.finditer(r'"text":"([^"]{2,50})","navigationEndpoint".*?"canonicalBaseUrl":"/@([^"]+)"', html):
    name, handle = m.group(1), m.group(2)
    if handle.lower() != source_handle and not any(c in name for c in [':']):
        if handle not in channels:
            channels[handle] = name

for handle, name in channels.items():
    print(f'{handle}\t{name}')
PYEOF

done < "$TMPDIR_WORK/top_videos.txt"

echo ""
echo "[3/3] Ranking related channels..."

# Step 3: Count frequency (channels appearing in multiple video recommendations rank higher)
python3 - "$RELATED_FILE" "$COUNT" << 'PYEOF'
import sys
from collections import Counter

channel_counts = Counter()
channel_names = {}

with open(sys.argv[1]) as f:
    for line in f:
        line = line.strip()
        if '\t' not in line:
            continue
        handle, name = line.split('\t', 1)
        channel_counts[handle] += 1
        channel_names[handle] = name

count = int(sys.argv[2])

print(f"\nFound {len(channel_counts)} unique related channels")
print(f"Top {min(count, len(channel_counts))} by recommendation frequency:\n")
print(f"{'#':<4} {'Channel':<35} {'Handle':<25} {'Freq'}")
print("-" * 70)

for i, (handle, freq) in enumerate(channel_counts.most_common(count), 1):
    name = channel_names[handle]
    print(f"{i:<4} {name:<35} @{handle:<24} {freq}x")
    # Also output in machine-readable format to stderr
    print(f"HANDLE:@{handle}", file=sys.stderr)
PYEOF
