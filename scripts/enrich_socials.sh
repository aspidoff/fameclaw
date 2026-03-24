#!/bin/bash
# Enrich a CSV with cross-platform social data (X followers/likes, TikTok followers/hearts)
#
# Usage: ./enrich_socials.sh <input.csv> [output.csv] [--platforms x,tiktok]
# Example: ./enrich_socials.sh channels.csv enriched.csv --platforms x,tiktok

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

INPUT="${1:-}"
OUTPUT="${2:-}"
PLATFORMS="x,tiktok"

# Parse args
shift 2 2>/dev/null || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --platforms) PLATFORMS="$2"; shift 2 ;;
    *) shift ;;
  esac
done

if [ -z "$INPUT" ]; then
  echo "Usage: $0 <input.csv> [output.csv] [--platforms x,tiktok]"
  exit 1
fi

if [ ! -f "$INPUT" ]; then
  echo "Error: Input file '$INPUT' not found"
  exit 1
fi

if [ -z "$OUTPUT" ]; then
  OUTPUT="${INPUT%.csv}_enriched.csv"
fi

DO_X=false
DO_TIKTOK=false
[[ "$PLATFORMS" == *"x"* ]] && DO_X=true
[[ "$PLATFORMS" == *"tiktok"* ]] && DO_TIKTOK=true

echo "=== Social Enrichment ==="
echo "Input:     $INPUT"
echo "Output:    $OUTPUT"
echo "Platforms: $PLATFORMS"
echo ""

# --- Python: X profile fetcher + CSV enrichment ---
python3 - "$INPUT" "$OUTPUT" "$DO_X" "$DO_TIKTOK" "$SCRIPT_DIR" << 'PYEOF'
import sys, csv, subprocess, time, os

input_file, output_file, do_x, do_tiktok, script_dir = sys.argv[1], sys.argv[2], sys.argv[3] == "true", sys.argv[4] == "true", sys.argv[5]

def get_x_profile(handle):
    """Fetch X profile via syndication API — no auth needed"""
    import urllib.request, json, re
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="replace")
        m = re.search(r"<script[^>]*id=\"__NEXT_DATA__\"[^>]*>(.*?)</script>", html, re.DOTALL)
        if not m: return {}
        data = json.loads(m.group(1))
        entries = data["props"]["pageProps"]["timeline"]["entries"]
        # Get user from first tweet
        for entry in entries:
            if entry["type"] == "tweet":
                user = entry["content"]["tweet"].get("user", {})
                if user:
                    # Calc avg likes from recent tweets
                    likes = []
                    for e in entries[:20]:
                        if e["type"] == "tweet":
                            likes.append(e["content"]["tweet"].get("favorite_count", 0))
                    return {
                        "followers": user.get("followers_count", ""),
                        "bio": user.get("description", ""),
                        "avg_likes": int(sum(likes)/len(likes)) if likes else "",
                    }
    except:
        pass
    return {}

def get_tiktok_stats(handle, script_dir):
    """Call extract_tiktok.sh and parse the output for followers/hearts"""
    import tempfile, re
    tmpdir = tempfile.mkdtemp()
    tmp_csv = os.path.join(tmpdir, "tt.csv")
    url = f"https://www.tiktok.com/@{handle}"
    try:
        result = subprocess.run(
            ["bash", os.path.join(script_dir, "extract_tiktok.sh"), url, tmp_csv],
            capture_output=True, text=True, timeout=30
        )
        if os.path.exists(tmp_csv):
            with open(tmp_csv) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    return {
                        "followers": row.get("followers", ""),
                        "hearts": row.get("hearts", row.get("likes", "")),
                    }
    except:
        pass
    finally:
        subprocess.run(["rm", "-rf", tmpdir], capture_output=True)
    return {}

# Read input CSV
with open(input_file, newline='', errors='replace') as f:
    reader = csv.DictReader(f)
    fieldnames = list(reader.fieldnames)
    rows = list(reader)

# Determine column indices
has_x_col = "x_handle" in fieldnames
has_tt_col = "tiktok_handle" in fieldnames

# Add new columns
new_cols = []
if do_x:
    for c in ["x_followers", "x_avg_likes"]:
        if c not in fieldnames:
            new_cols.append(c)
if do_tiktok:
    for c in ["tiktok_followers", "tiktok_hearts"]:
        if c not in fieldnames:
            new_cols.append(c)

out_fieldnames = fieldnames + new_cols
total = len(rows)

for i, row in enumerate(rows):
    x_handle = row.get("x_handle", "").strip() if has_x_col else ""
    tt_handle = row.get("tiktok_handle", "").strip() if has_tt_col else ""

    label_parts = []
    if x_handle and do_x: label_parts.append("X")
    if tt_handle and do_tiktok: label_parts.append("TikTok")
    handle_display = x_handle or tt_handle or "—"
    platforms_label = " + ".join(label_parts) if label_parts else "skip"

    print(f"Enriching {i+1}/{total}: @{handle_display} ({platforms_label})...")

    # X enrichment
    if do_x and x_handle:
        xdata = get_x_profile(x_handle)
        row["x_followers"] = str(xdata.get("followers", ""))
        row["x_avg_likes"] = str(xdata.get("avg_likes", ""))
        time.sleep(1.5)
    else:
        row.setdefault("x_followers", "")
        row.setdefault("x_avg_likes", "")

    # TikTok enrichment
    if do_tiktok and tt_handle:
        ttdata = get_tiktok_stats(tt_handle, script_dir)
        row["tiktok_followers"] = str(ttdata.get("followers", ""))
        row["tiktok_hearts"] = str(ttdata.get("hearts", ""))
        time.sleep(1.5)
    else:
        row.setdefault("tiktok_followers", "")
        row.setdefault("tiktok_hearts", "")

# Write output
with open(output_file, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=out_fieldnames, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

print(f"\n✅ Enriched {total} rows → {output_file}")
PYEOF
