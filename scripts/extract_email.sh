#!/bin/bash
# Extract email addresses from a YouTube channel by checking:
# 1. The YouTube channel page itself
# 2. The channel's linked/external websites
# 3. The channel handle's likely vanity domain
#
# Usage: ./extract_email.sh <youtube_channel_url>
# Example: ./extract_email.sh "https://youtube.com/@tbpnlive"

set -euo pipefail

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
EMAIL_RE='[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
JUNK_EMAILS='example\.\|email\.com\|sentry\.\|domain\.\|wixpress\.\|placeholder\|noreply\|no-reply\|@google\.\|@youtube\.\|@gstatic\.'
JUNK_DOMAINS='youtube\.com\|google\.com\|googlevideo\.com\|ggpht\.com\|ytimg\.com\|googleapis\.com\|gstatic\.com\|googleusercontent\.com\|doubleclick\.\|googlesyndication\.\|googleadservices\.'

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <youtube_channel_url>"
  exit 1
fi

CHANNEL_URL="$1"
CHANNEL_URL=$(echo "$CHANNEL_URL" | sed 's/[?#].*//' | sed 's:/*$::')

echo "=== YouTube Email Extractor ==="
echo "Channel: $CHANNEL_URL"
echo ""

# --- Step 1: Fetch YouTube page ---
echo "[1/4] Fetching YouTube channel page..."
YT_HTML=$(curl -sL "$CHANNEL_URL" -H "User-Agent: $UA" 2>/dev/null || true)

CHANNEL_NAME=$(echo "$YT_HTML" | python3 -c "
import sys, re, json
html = sys.stdin.read()
m = re.search(r'channelMetadataRenderer.*?\"title\":\"([^\"]+)', html)
print(m.group(1) if m else 'unknown')
" 2>/dev/null || echo "unknown")

HANDLE=$(echo "$CHANNEL_URL" | grep -oE '@[^/]+' | sed 's/@//' || true)
echo "  Channel: ${CHANNEL_NAME} (@${HANDLE:-unknown})"

# Emails on YouTube page
YT_EMAILS=$(echo "$YT_HTML" | grep -oiE "$EMAIL_RE" | sort -u | grep -v "$JUNK_EMAILS" || true)
if [ -n "$YT_EMAILS" ]; then
  echo "  Emails found on YouTube:"
  echo "$YT_EMAILS" | while read -r e; do echo "    ✅ $e"; done
fi

# --- Step 2: Extract real external links ---
echo ""
echo "[2/4] Finding external links..."

ALL_URLS=$(echo "$YT_HTML" | python3 -c "
import sys, re, urllib.parse

html = sys.stdin.read()
junk = {'youtube.com','google.com','googlevideo.com','ggpht.com','ytimg.com',
        'googleapis.com','gstatic.com','googleusercontent.com','doubleclick.net',
        'googlesyndication.com','googleadservices.com','play.google.com',
        'accounts.google.com','policies.google.com'}

urls = set()

# Method 1: YouTube redirect URLs
for m in re.finditer(r'youtube\.com/redirect\?[^\"]+', html):
    full = m.group(0)
    qm = re.search(r'[?&]q=([^&\"]+)', full)
    if qm:
        url = urllib.parse.unquote(qm.group(1))
        urls.add(url)

# Method 2: Direct URL fields in JSON
for m in re.finditer(r'\"url\":\"(https?://[^\"]+)\"', html):
    urls.add(m.group(1))

# Method 3: External link view models
for m in re.finditer(r'channelExternalLinkViewModel.*?\"url\":\"(https?://[^\"]+)\"', html):
    urls.add(m.group(1))

# Filter
for url in sorted(urls):
    try:
        domain = urllib.parse.urlparse(url).netloc.lower()
        if not any(j in domain for j in junk):
            print(url)
    except:
        pass
" 2>/dev/null || true)

if [ -n "$ALL_URLS" ]; then
  echo "  Found links:"
  echo "$ALL_URLS" | while read -r url; do echo "    - $url"; done
fi

# --- Step 3: Try vanity domains ---
echo ""
echo "[3/4] Checking vanity domains..."
if [ -n "$HANDLE" ]; then
  BASE=$(echo "$HANDLE" | sed -E 's/(live|official|hq|tv|channel|yt|tube)$//i' | tr '[:upper:]' '[:lower:]')
  for d in "${BASE}.com" "${HANDLE}.com"; do
    if echo "$ALL_URLS" | grep -q "$d" 2>/dev/null; then
      echo "  $d already in link list"
      continue
    fi
    CODE=$(curl -sL -o /dev/null -w "%{http_code}" "https://$d" --max-time 5 -H "User-Agent: $UA" 2>/dev/null || echo "000")
    if [ "$CODE" -ge 200 ] 2>/dev/null && [ "$CODE" -lt 500 ] 2>/dev/null; then
      echo "  ✅ https://$d (HTTP $CODE)"
      ALL_URLS=$(printf "%s\nhttps://%s" "$ALL_URLS" "$d")
    else
      echo "  ❌ $d (not reachable)"
    fi
  done
fi

# --- Step 4: Scan all URLs for emails ---
echo ""
echo "[4/4] Scanning for emails..."
ALL_FOUND_EMAILS="$YT_EMAILS"

if [ -n "$ALL_URLS" ]; then
  while IFS= read -r url; do
    [ -z "$url" ] && continue
    DOMAIN=$(echo "$url" | sed 's|https\?://||;s|/.*||')
    PAGE=$(curl -sL "$url" --max-time 10 -H "User-Agent: $UA" 2>/dev/null || true)
    EMAILS=$(echo "$PAGE" | grep -oiE "$EMAIL_RE" | sort -u | grep -v "$JUNK_EMAILS" || true)
    
    if [ -n "$EMAILS" ]; then
      echo "  From $DOMAIN:"
      echo "$EMAILS" | while read -r e; do echo "    ✅ $e"; done
      ALL_FOUND_EMAILS=$(printf "%s\n%s" "$ALL_FOUND_EMAILS" "$EMAILS")
    else
      echo "  $DOMAIN — no emails"
    fi
  done <<< "$ALL_URLS"
fi

ALL_FOUND_EMAILS=$(echo "$ALL_FOUND_EMAILS" | sort -u | grep -v '^$' || true)

echo ""
echo "=== RESULTS ==="
if [ -n "$ALL_FOUND_EMAILS" ]; then
  echo "📧 Emails found for ${CHANNEL_NAME}:"
  echo "$ALL_FOUND_EMAILS" | while read -r e; do echo "  $e"; done
else
  echo "No emails found automatically."
  echo ""
  echo "Try manually:"
  echo "  1. YouTube About page (business email behind captcha)"
  echo "  2. Social media bios (X, Instagram, LinkedIn)"
  echo "  3. Contact forms on their website"
fi
