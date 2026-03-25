#!/bin/bash
# Extract X (Twitter) profile data: followers, engagement, email, partnership signals
# Appends a row to a CSV file
#
# Usage: ./extract_x.sh <x_profile_url_or_handle> [output_file]
# Example: ./extract_x.sh "https://x.com/gregisenberg" x_data.csv
# Example: ./extract_x.sh gregisenberg x_data.csv
# Example: ./extract_x.sh @gregisenberg x_data.csv

set -euo pipefail

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
EMAIL_RE='[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
JUNK_EMAILS='example\.\|email\.com\|sentry\.\|domain\.\|wixpress\.\|placeholder\|noreply\|no-reply\|@google\.\|@x\.com\|@twitter\.com\|twimg\.com'

INPUT="${1:-}"
OUTPUT="${2:-x_data.csv}"
TMPDIR_WORK=$(mktemp -d)
trap "rm -rf $TMPDIR_WORK" EXIT

if [ -z "$INPUT" ]; then
  echo "Usage: $0 <x_profile_url_or_handle> [output_file.csv]"
  exit 1
fi

# Normalize input to just handle
HANDLE=$(echo "$INPUT" | sed 's|https\?://\(x\|twitter\)\.com/||' | sed 's|^@||' | sed 's|[?#].*||' | sed 's|/*$||')

echo "=== X (Twitter) Profile Extractor ==="
echo "Handle: @$HANDLE"
echo ""

# Fetch profile via syndication API
echo "[1/3] Fetching profile..."
SYNDICATION_URL="https://syndication.twitter.com/srv/timeline-profile/screen-name/${HANDLE}"
curl -sL "$SYNDICATION_URL" -H "User-Agent: $UA" > "$TMPDIR_WORK/main.html" 2>/dev/null || true

# Extract data with Python
echo "[2/3] Extracting stats..."
python3 - "$TMPDIR_WORK/main.html" "$HANDLE" "$TMPDIR_WORK/stats.txt" << 'PYEOF'
import sys, re, json

html_file, handle, out_file = sys.argv[1], sys.argv[2], sys.argv[3]

with open(html_file, 'r', errors='replace') as f:
    html = f.read()

r = {}
r['handle'] = handle
r['x_handle'] = handle
r['x_url'] = f'https://x.com/{handle}'

# Extract __NEXT_DATA__ JSON
next_data = {}
m = re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">\s*(\{.*?\})\s*</script>', html, re.DOTALL)
if m:
    try:
        next_data = json.loads(m.group(1))
    except:
        pass

# Navigate to timeline entries
props = next_data.get('props', {}).get('pageProps', {})
timeline = props.get('timeline', {})
entries = timeline.get('entries', [])

# Extract user info from first available tweet entry
user_info = {}
for entry in entries:
    content = entry.get('content', {})
    tweet = content.get('tweet', {})
    user = tweet.get('user', {})
    if user:
        user_info = user
        break

# Also check if user info is at top level
if not user_info:
    user_info = props.get('user', {})

r['name'] = user_info.get('name', '')
r['bio'] = user_info.get('description', '').replace('\n', ' ').strip()[:300]
r['followers'] = str(user_info.get('followers_count', ''))
r['following'] = str(user_info.get('friends_count', ''))
r['tweet_count'] = str(user_info.get('statuses_count', ''))
r['verified'] = 'true' if user_info.get('is_blue_verified', False) or user_info.get('verified', False) else 'false'

# Profile website URL
url_info = user_info.get('url', '')
# Try to get expanded URL from entities
entities = user_info.get('entities', {})
url_entities = entities.get('url', {}).get('urls', [])
for ue in url_entities:
    expanded = ue.get('expanded_url', '')
    if expanded:
        url_info = expanded
        break
r['url'] = url_info

# Collect tweets for engagement stats and partnership signals
tweets = []
for entry in entries:
    content = entry.get('content', {})
    tweet = content.get('tweet', {})
    if tweet and 'id_str' in tweet:
        tweets.append(tweet)

# Engagement averages
likes = []
retweets = []
replies = []
for t in tweets:
    likes.append(t.get('favorite_count', 0))
    retweets.append(t.get('retweet_count', 0))
    replies.append(t.get('reply_count', t.get('conversation_count', 0)))

r['avg_likes'] = str(int(sum(likes) / len(likes))) if likes else ''
r['avg_retweets'] = str(int(sum(retweets) / len(retweets))) if retweets else ''
r['avg_replies'] = str(int(sum(replies) / len(replies))) if replies else ''

# Partnership signals
partnership_count = 0
partner_keywords = ['partner', 'sponsored', '#ad', 'paid partnership']
for t in tweets:
    text = t.get('text', '').lower()
    full_text = t.get('full_text', text).lower()
    combined = full_text

    # Check for partnership keywords
    for kw in partner_keywords:
        if kw in combined:
            partnership_count += 1
            break
    else:
        # Check for brand @mentions (mentions that aren't replies)
        entities = t.get('entities', {})
        mentions = entities.get('user_mentions', [])
        if mentions and not combined.startswith('@'):
            # Has mentions but isn't a reply — could be brand mention
            pass  # Don't count all mentions, too noisy

        # Check for UTM links, affiliate links, /ref/ URLs
        urls = entities.get('urls', [])
        for u in urls:
            expanded = u.get('expanded_url', '')
            if any(sig in expanded.lower() for sig in ['utm_', 'affiliate', '/ref/', 'aff=', 'partner']):
                partnership_count += 1
                break

r['partnership_signals'] = str(partnership_count)

# Emails in bio
bio_text = r['bio']
r['bio_emails'] = ' '.join(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', bio_text))

with open(out_file, 'w') as f:
    for k, v in r.items():
        f.write(f'{k}={v}\n')
PYEOF

# Read stats
get_stat() { grep "^$1=" "$TMPDIR_WORK/stats.txt" 2>/dev/null | sed "s/^$1=//" | head -1 || echo ""; }

NAME=$(get_stat name)
HANDLE_VAL=$(get_stat handle)
BIO=$(get_stat bio)
FOLLOWERS=$(get_stat followers)
FOLLOWING=$(get_stat following)
TWEET_COUNT=$(get_stat tweet_count)
VERIFIED=$(get_stat verified)
AVG_LIKES=$(get_stat avg_likes)
AVG_RETWEETS=$(get_stat avg_retweets)
AVG_REPLIES=$(get_stat avg_replies)
URL=$(get_stat url)
X_HANDLE=$(get_stat x_handle)
X_URL=$(get_stat x_url)
PARTNERSHIP_SIGNALS=$(get_stat partnership_signals)
BIO_EMAILS=$(get_stat bio_emails)

echo "  Name:        $NAME"
echo "  Handle:      @$HANDLE_VAL"
echo "  Followers:   ${FOLLOWERS:-n/a}"
echo "  Following:   ${FOLLOWING:-n/a}"
echo "  Tweets:      ${TWEET_COUNT:-n/a}"
echo "  Verified:    $VERIFIED"
echo "  Avg likes:   ${AVG_LIKES:-n/a}"
echo "  Avg RTs:     ${AVG_RETWEETS:-n/a}"
echo "  Avg replies: ${AVG_REPLIES:-n/a}"
echo "  Website:     ${URL:-none}"
echo "  Partnerships: ${PARTNERSHIP_SIGNALS:-0} signals"

# --- Find emails ---
echo ""
echo "[3/3] Finding emails..."
ALL_EMAILS="$BIO_EMAILS"

# Emails from the HTML page itself
PAGE_EMAILS=$(grep -oiE "$EMAIL_RE" "$TMPDIR_WORK/main.html" 2>/dev/null | sort -u | grep -v "$JUNK_EMAILS" || true)
if [ -n "$PAGE_EMAILS" ]; then
  echo "  From X page:"
  echo "$PAGE_EMAILS" | while read -r e; do echo "    $e"; done
  ALL_EMAILS=$(printf "%s\n%s" "$ALL_EMAILS" "$PAGE_EMAILS")
fi

# If there's a profile website, try to find emails on that site
if [ -n "$URL" ]; then
  LINK_DOMAIN=$(echo "$URL" | sed 's|https\?://||;s|/.*||')
  LINK_URL="$URL"
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
HANDLE_CLEAN="$HANDLE_VAL"
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
  echo "handle,name,bio,followers,following,tweet_count,verified,avg_likes,avg_retweets,avg_replies,email,url,partnership_signals" > "$OUTPUT"
fi

csv_escape() { printf '"%s"' "$(echo "$1" | sed 's/"/""/g')"; }

ROW="$(csv_escape "$HANDLE_VAL"),$(csv_escape "$NAME"),$(csv_escape "$BIO"),$(csv_escape "$FOLLOWERS"),$(csv_escape "$FOLLOWING"),$(csv_escape "$TWEET_COUNT"),$(csv_escape "$VERIFIED"),$(csv_escape "$AVG_LIKES"),$(csv_escape "$AVG_RETWEETS"),$(csv_escape "$AVG_REPLIES"),$(csv_escape "$EMAIL_STR"),$(csv_escape "$URL"),$(csv_escape "$PARTNERSHIP_SIGNALS")"
echo "$ROW" >> "$OUTPUT"

echo "Saved to $OUTPUT"
echo ""
echo "=== Summary ==="
echo "  $NAME (@$HANDLE_VAL)"
echo "  📊 $FOLLOWERS followers | $TWEET_COUNT tweets | ~${AVG_LIKES:-?} avg likes"
[ -n "$EMAIL_STR" ] && [ "$EMAIL_STR" != ";" ] && echo "  📧 $EMAIL_STR" || echo "  📧 no email found"
echo "  🤝 ${PARTNERSHIP_SIGNALS:-0} partnership signals"
