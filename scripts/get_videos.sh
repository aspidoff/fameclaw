#!/bin/bash
# Fetch recent video titles from a YouTube channel for email personalization
# Usage: ./get_videos.sh "https://youtube.com/@handle" [count]
# Output: one video title per line

set -euo pipefail

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
CHANNEL_URL="${1:-}"
COUNT="${2:-5}"

if [ -z "$CHANNEL_URL" ]; then
  echo "Usage: $0 <channel_url> [count]" >&2
  exit 1
fi

CHANNEL_URL=$(echo "$CHANNEL_URL" | sed 's/[?#].*//' | sed 's:/*$::')

curl -sL "${CHANNEL_URL}/videos" -H "User-Agent: $UA" 2>/dev/null | python3 -c "
import sys, re, json

html = sys.stdin.read()
titles = []

# Extract video titles from the page
for m in re.finditer(r'\"title\":\{\"runs\":\[\{\"text\":\"([^\"]+)\"\}\]', html):
    t = m.group(1)
    # Skip generic titles
    if t.lower() not in ('home', 'videos', 'shorts', 'live', 'playlists', 'community', 'channels', 'about'):
        if t not in titles:
            titles.append(t)

for t in titles[:int(sys.argv[1])]:
    print(t)
" "$COUNT" 2>/dev/null
