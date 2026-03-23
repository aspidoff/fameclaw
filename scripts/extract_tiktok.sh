#!/bin/bash
# Extract TikTok profile data: followers, hearts, video count, email, bio
# Appends a row to a CSV file
#
# Usage: ./extract_tiktok.sh <tiktok_profile_url> [output_file]
# Example: ./extract_tiktok.sh "https://www.tiktok.com/@charlidamelio" tiktok.csv

set -euo pipefail

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
EMAIL_RE='[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
JUNK_EMAILS='example\.\|email\.com\|sentry\.\|domain\.\|wixpress\.\|placeholder\|noreply\|no-reply\|@google\.\|@tiktok\.\|@bytedance\.\|u002F@\|u002f@\|tiktokcdn\|musical\.ly'

PROFILE_URL="${1:-}"
OUTPUT="${2:-tiktok_data.csv}"
TMPDIR_WORK=$(mktemp -d)
trap "rm -rf $TMPDIR_WORK" EXIT

if [ -z "$PROFILE_URL" ]; then
  echo "Usage: $0 <tiktok_profile_url> [output_file.csv]"
  exit 1
fi

PROFILE_URL=$(echo "$PROFILE_URL" | sed 's/[?#].*//' | sed 's:/*$::')

echo "=== TikTok Profile Extractor ==="
echo "Profile: $PROFILE_URL"
echo ""

# Fetch profile page
echo "[1/3] Fetching profile..."
curl -sL "$PROFILE_URL" -H "User-Agent: $UA" > "$TMPDIR_WORK/main.html" 2>/dev/null || true

# Extract stats with Python
echo "[2/3] Extracting stats..."
python3 - "$TMPDIR_WORK/main.html" "$PROFILE_URL" "$TMPDIR_WORK/stats.txt" << 'PYEOF'
import sys, re, json

main_file, profile_url, out_file = sys.argv[1], sys.argv[2], sys.argv[3]

with open(main_file, 'r', errors='replace') as f:
    html = f.read()

r = {}

# Handle from URL
m = re.search(r'@([a-zA-Z0-9_.]+)', profile_url)
r['handle'] = '@' + m.group(1) if m else ''

# Try to find the user stats JSON blob
stats_match = re.search(r'"stats"\s*:\s*\{[^}]+\}', html)
stats = {}
if stats_match:
    try:
        stats = json.loads('{' + stats_match.group(0).split('{', 1)[1])
    except:
        pass

r['followers'] = str(stats.get('followerCount', ''))
r['following'] = str(stats.get('followingCount', ''))
# heartCount can overflow int32 for big creators; prefer the raw JSON string
hearts_val = stats.get('heartCount', stats.get('heart', ''))
if isinstance(hearts_val, int) and hearts_val < 0:
    # Overflow — try to grab directly from raw JSON string
    hm = re.search(r'"heartCount"\s*:\s*(\d+)', html)
    if hm:
        hearts_val = hm.group(1)
    else:
        hm = re.search(r'"heart"\s*:\s*(\d+)', html)
        hearts_val = hm.group(1) if hm else ''
r['hearts'] = str(hearts_val)
r['video_count'] = str(stats.get('videoCount', ''))

# Try to find user info JSON blob
# Look for uniqueId, nickname, signature, verified, bioLink
user_match = re.search(r'"user"\s*:\s*\{', html)
user = {}
if user_match:
    # Extract a reasonable chunk after the match and try to parse
    start = user_match.start()
    chunk = html[start:]
    # Find the key after "user":
    inner = chunk[chunk.index('{'):]
    depth = 0
    end = 0
    for i, ch in enumerate(inner):
        if ch == '{': depth += 1
        elif ch == '}': depth -= 1
        if depth == 0:
            end = i + 1
            break
    if end > 0:
        try:
            user = json.loads(inner[:end])
        except:
            pass

# Nickname / display name
name = user.get('nickname', '')
if not name:
    m = re.search(r'"nickname"\s*:\s*"([^"]+)"', html)
    name = m.group(1) if m else ''
r['name'] = name

# Unique ID (handle without @)
uid = user.get('uniqueId', '')
if not uid:
    m = re.search(r'"uniqueId"\s*:\s*"([^"]+)"', html)
    uid = m.group(1) if m else ''
if uid and not r['handle']:
    r['handle'] = '@' + uid

# Signature / bio
sig = user.get('signature', '')
if not sig:
    m = re.search(r'"signature"\s*:\s*"([^"]*)"', html)
    sig = m.group(1) if m else ''
r['bio'] = sig.replace('\\n', ' ').strip()[:300]

# Verified
verified = user.get('verified', False)
if not verified:
    m = re.search(r'"verified"\s*:\s*(true|false)', html)
    verified = m and m.group(1) == 'true'
r['verified'] = 'true' if verified else 'false'

# Bio link
bio_link = ''
bl = user.get('bioLink', {})
if isinstance(bl, dict):
    bio_link = bl.get('link', '')
if not bio_link:
    m = re.search(r'"bioLink"\s*:\s*\{[^}]*"link"\s*:\s*"([^"]+)"', html)
    bio_link = m.group(1) if m else ''
r['bio_link'] = bio_link

# Emails in bio
r['bio_emails'] = ' '.join(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', r['bio']))

r['profile_url'] = profile_url

with open(out_file, 'w') as f:
    for k, v in r.items():
        f.write(f'{k}={v}\n')
PYEOF

# Read stats
get_stat() { grep "^$1=" "$TMPDIR_WORK/stats.txt" 2>/dev/null | sed "s/^$1=//" | head -1 || echo ""; }

NAME=$(get_stat name)
HANDLE_VAL=$(get_stat handle)
FOLLOWERS=$(get_stat followers)
FOLLOWING=$(get_stat following)
HEARTS=$(get_stat hearts)
VIDEO_COUNT=$(get_stat video_count)
VERIFIED=$(get_stat verified)
BIO=$(get_stat bio)
BIO_LINK=$(get_stat bio_link)
BIO_EMAILS=$(get_stat bio_emails)

echo "  Name:       $NAME"
echo "  Handle:     $HANDLE_VAL"
echo "  Followers:  ${FOLLOWERS:-n/a}"
echo "  Following:  ${FOLLOWING:-n/a}"
echo "  Hearts:     ${HEARTS:-n/a}"
echo "  Videos:     ${VIDEO_COUNT:-n/a}"
echo "  Verified:   $VERIFIED"
echo "  Bio link:   ${BIO_LINK:-none}"

# --- Find emails ---
echo ""
echo "[3/3] Finding emails..."
ALL_EMAILS="$BIO_EMAILS"

# Emails from the HTML page itself
PAGE_EMAILS=$(grep -oiE "$EMAIL_RE" "$TMPDIR_WORK/main.html" 2>/dev/null | sort -u | grep -v "$JUNK_EMAILS" || true)
if [ -n "$PAGE_EMAILS" ]; then
  echo "  From TikTok page:"
  echo "$PAGE_EMAILS" | while read -r e; do echo "    $e"; done
  ALL_EMAILS=$(printf "%s\n%s" "$ALL_EMAILS" "$PAGE_EMAILS")
fi

# If there's a bio link, try to find emails on that site
if [ -n "$BIO_LINK" ]; then
  LINK_DOMAIN=$(echo "$BIO_LINK" | sed 's|https\?://||;s|/.*||')
  # Ensure it has a scheme
  LINK_URL="$BIO_LINK"
  echo "$LINK_URL" | grep -q '^https\?://' || LINK_URL="https://$LINK_URL"
  FOUND=""
  for url_path in "/" "/contact" "/about" "/contact-us"; do
    BASE_URL=$(echo "$LINK_URL" | sed 's|/[^/]*$||;s:/*$::')
    [ "$url_path" = "/" ] && SCAN_URL="$LINK_URL" || SCAN_URL="${BASE_URL}${url_path}"
    LINK_EMAILS=$(curl -sL "$SCAN_URL" --max-time 8 -H "User-Agent: $UA" 2>/dev/null | grep -oiE "$EMAIL_RE" | sort -u | grep -v "$JUNK_EMAILS" || true)
    [ -n "$LINK_EMAILS" ] && FOUND=$(printf "%s\n%s" "$FOUND" "$LINK_EMAILS")
  done
  FOUND=$(echo "$FOUND" | sort -fu | grep -v '^$' || true)
  if [ -n "$FOUND" ]; then
    echo "  From $LINK_DOMAIN:"
    echo "$FOUND" | while read -r e; do echo "    $e"; done
    ALL_EMAILS=$(printf "%s\n%s" "$ALL_EMAILS" "$FOUND")
  fi
fi

# Try vanity domains from handle
HANDLE_CLEAN=$(echo "$HANDLE_VAL" | sed 's/@//')
if [ -n "$HANDLE_CLEAN" ]; then
  BASE_HANDLE=$(echo "$HANDLE_CLEAN" | sed -E 's/(live|official|hq|tv|channel)$//i' | tr '[:upper:]' '[:lower:]')
  for d in "${BASE_HANDLE}.com" "${HANDLE_CLEAN}.com"; do
    CODE=$(curl -sL -o /dev/null -w "%{http_code}" "https://$d" --max-time 5 -H "User-Agent: $UA" 2>/dev/null || echo "000")
    if [ "$CODE" -ge 200 ] 2>/dev/null && [ "$CODE" -lt 500 ] 2>/dev/null; then
      FOUND=""
      for url_path in "/" "/contact" "/about" "/contact-us"; do
        VANITY_EMAILS=$(curl -sL "https://${d}${url_path}" --max-time 8 -H "User-Agent: $UA" 2>/dev/null | grep -oiE "$EMAIL_RE" | sort -u | grep -v "$JUNK_EMAILS" || true)
        [ -n "$VANITY_EMAILS" ] && FOUND=$(printf "%s\n%s" "$FOUND" "$VANITY_EMAILS")
      done
      FOUND=$(echo "$FOUND" | sort -fu | grep -v '^$' || true)
      if [ -n "$FOUND" ]; then
        echo "  From $d:"
        echo "$FOUND" | while read -r e; do echo "    $e"; done
        ALL_EMAILS=$(printf "%s\n%s" "$ALL_EMAILS" "$FOUND")
      fi
    fi
  done
fi

ALL_EMAILS=$(echo "$ALL_EMAILS" | sort -fu | grep -v '^$' || true)
EMAIL_STR=$(echo "$ALL_EMAILS" | tr '\n' '; ' | sed 's/; $//;s/^; $//;s/^;$//')

# --- Write CSV ---
echo ""
if [ ! -s "$OUTPUT" ]; then
  echo "creator_name,handle,followers,following,hearts,video_count,verified,email,bio,bio_link,profile_url" > "$OUTPUT"
fi

csv_escape() { printf '"%s"' "$(echo "$1" | sed 's/"/""/g')"; }

ROW="$(csv_escape "$NAME"),$(csv_escape "$HANDLE_VAL"),$(csv_escape "$FOLLOWERS"),$(csv_escape "$FOLLOWING"),$(csv_escape "$HEARTS"),$(csv_escape "$VIDEO_COUNT"),$(csv_escape "$VERIFIED"),$(csv_escape "$EMAIL_STR"),$(csv_escape "$BIO"),$(csv_escape "$BIO_LINK"),$(csv_escape "$PROFILE_URL")"
echo "$ROW" >> "$OUTPUT"

echo "Saved to $OUTPUT"
echo ""
echo "=== Summary ==="
echo "  $NAME ($HANDLE_VAL)"
echo "  📊 $FOLLOWERS followers | $VIDEO_COUNT videos | $HEARTS hearts"
[ -n "$EMAIL_STR" ] && [ "$EMAIL_STR" != ";" ] && echo "  📧 $EMAIL_STR" || echo "  📧 no email found"
