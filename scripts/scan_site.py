#!/usr/bin/env python3
"""FameClaw Site Scanner — Extract brand intelligence from a website."""

import argparse
import json
import re
import subprocess
import sys

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def fetch(url, timeout=15):
    try:
        result = subprocess.run(
            ["curl", "-sL", url, "-H", f"User-Agent: {UA}", "--max-time", str(timeout)],
            capture_output=True, text=True, timeout=timeout + 5
        )
        return result.stdout
    except Exception:
        return ""


def scan(brand, url):
    html = fetch(url)
    about_html = ""
    for path in ["/about", "/about-us", "/pages/about"]:
        about_html += fetch(url + path, timeout=10)

    combined = html + "\n" + about_html
    r = {"brand": brand, "url": url}

    # Title
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    r["title"] = m.group(1).strip() if m else ""

    # Meta description
    for pattern in [
        r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']',
        r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']description["\']',
    ]:
        m = re.search(pattern, html, re.I)
        if m:
            r["meta_description"] = m.group(1).strip()
            break
    else:
        r["meta_description"] = ""

    # OG description
    m = re.search(r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
    r["og_description"] = m.group(1).strip() if m else ""

    # H1 / H2 tags
    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", combined, re.I | re.S)
    r["h1_tags"] = [re.sub(r"<[^>]+>", "", h).strip() for h in h1s[:5]]
    h2s = re.findall(r"<h2[^>]*>(.*?)</h2>", combined, re.I | re.S)
    r["h2_tags"] = [re.sub(r"<[^>]+>", "", h).strip() for h in h2s[:10]]

    # Meta keywords
    m = re.search(r'<meta[^>]*name=["\']keywords["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
    r["meta_keywords"] = [k.strip() for k in m.group(1).split(",")] if m else []

    # JSON-LD
    ld_blocks = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S)
    ld_types, ld_descs = [], []
    for block in ld_blocks:
        try:
            data = json.loads(block)
            items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
            for item in items:
                if isinstance(item, dict):
                    if "@type" in item:
                        ld_types.append(item["@type"])
                    if "description" in item:
                        ld_descs.append(item["description"][:200])
        except Exception:
            pass
    r["ld_types"] = ld_types[:5]
    r["ld_descriptions"] = ld_descs[:3]

    # Nav items
    nav_blocks = re.findall(r"<(?:nav|header)[^>]*>(.*?)</(?:nav|header)>", html, re.I | re.S)
    nav_text = " ".join(nav_blocks)
    nav_items = [re.sub(r"<[^>]+>", "", a).strip() for a in re.findall(r"<a[^>]*>(.*?)</a>", nav_text, re.I | re.S)]
    r["nav_items"] = [n for n in nav_items if 1 < len(n) < 40][:15]

    # Platform detection
    platforms = []
    checks = [("Shopify", r"shopify|myshopify"), ("WooCommerce", r"woocommerce|wp-content"),
              ("BigCommerce", r"bigcommerce"), ("Squarespace", r"squarespace"), ("WordPress", r"wordpress")]
    for name, pat in checks:
        if re.search(pat, html, re.I):
            platforms.append(name)
    r["platforms"] = platforms

    # Social links
    social = {}
    social_patterns = [
        ("youtube", r'youtube\.com/(?:@|channel/|c/)([^\s"\'?/]+)'),
        ("tiktok", r'tiktok\.com/@([^\s"\'?/]+)'),
        ("instagram", r'instagram\.com/([^\s"\'?/]+)'),
        ("twitter", r'(?:twitter|x)\.com/([^\s"\'?/]+)'),
    ]
    for platform, pat in social_patterns:
        m = re.search(pat, html, re.I)
        if m:
            social[platform] = m.group(1)
    r["social"] = social

    # Body text preview
    body = re.sub(r"<script[^>]*>.*?</script>", "", combined, flags=re.I | re.S)
    body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.I | re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    r["body_preview"] = body[:1500]

    # Industry signals
    body_lower = body.lower()
    categories = {
        "E-commerce": ["shop", "store", "buy", "cart", "checkout", "product", "price", "shipping", "order"],
        "Creator/Influencer": ["creator", "influencer", "content", "brand deal", "ugc", "monetize", "affiliate"],
        "SaaS/Software": ["saas", "platform", "dashboard", "api", "integration", "software", "pricing plan"],
        "Agency/Services": ["agency", "service", "client", "portfolio", "case study", "consultation"],
        "Education/Courses": ["course", "academy", "masterclass", "enroll", "module", "lesson", "certification"],
        "Marketplace": ["marketplace", "listing", "seller", "buyer", "auction", "bid"],
    }
    signals = []
    for label, terms in categories.items():
        hits = sum(1 for t in terms if t in body_lower)
        if hits >= 2:
            signals.append(f"{label} ({hits}/{len(terms)})")
    r["industry_signals"] = signals

    return r


def display(data):
    print(f"\n=== Site Analysis: {data['brand']} ===")
    if data.get("title"):
        print(f"  Title: {data['title']}")
    if data.get("meta_description"):
        print(f"  Description: {data['meta_description'][:150]}")
    if data.get("og_description") and data["og_description"] != data.get("meta_description", ""):
        print(f"  OG: {data['og_description'][:150]}")
    if data.get("platforms"):
        print(f"  Platform: {', '.join(data['platforms'])}")
    if data.get("industry_signals"):
        print(f"  Industry: {', '.join(data['industry_signals'])}")
    if data.get("social"):
        socials = [f"{k}: @{v}" for k, v in data["social"].items()]
        print(f"  Social: {', '.join(socials)}")
    if data.get("nav_items"):
        print(f"  Nav: {', '.join(data['nav_items'][:10])}")
    if data.get("ld_types"):
        print(f"  Schema: {', '.join(data['ld_types'])}")
    if data.get("h1_tags"):
        print(f"  Headlines: {' | '.join(data['h1_tags'][:3])}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FameClaw Site Scanner")
    parser.add_argument("--brand", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", default="fameclaw_scan.json")
    args = parser.parse_args()

    data = scan(args.brand, args.url)
    display(data)

    with open(args.output, "w") as f:
        json.dump(data, f, indent=2)
    # Also generate a starter audience profile
    base = args.output.rsplit(".", 1)[0]
    base = base.replace("_scan", "")
    profile_path = f"{base}_audience.json"

    audience = {
        "brand": args.brand,
        "url": args.url,
        "target_categories": [],
        "target_demographics": {
            "age_range": "",
            "gender": "all",
            "interests": [],
            "location": "",
        },
        "authority_preferred": False,
        "notes": "Fill in after clarifying with user. target_categories should match keys from score_channels.py categories.",
        "available_categories": [
            "Beauty & Skincare", "Fitness & Health", "Tech & Gadgets",
            "Fashion & Lifestyle", "Food & Cooking", "E-commerce & Business",
            "TikTok & Social Media", "Finance & Investing", "Gaming",
            "Education & Tutorial", "Home & DIY", "Parenting & Family",
            "Pets & Animals", "Travel & Outdoor",
        ],
    }

    # Auto-fill from scan signals
    signal_to_category = {
        "E-commerce": ["E-commerce & Business"],
        "Creator/Influencer": ["TikTok & Social Media"],
        "SaaS/Software": ["Tech & Gadgets", "Education & Tutorial"],
        "Agency/Services": ["E-commerce & Business"],
        "Education/Courses": ["Education & Tutorial"],
        "Marketplace": ["E-commerce & Business"],
    }
    for signal in data.get("industry_signals", []):
        label = signal.split(" (")[0]
        if label in signal_to_category:
            for cat in signal_to_category[label]:
                if cat not in audience["target_categories"]:
                    audience["target_categories"].append(cat)

    with open(profile_path, "w") as f:
        json.dump(audience, f, indent=2)
    print(f"Audience profile template saved to {profile_path}")
    print(f"Scan saved to {args.output}")
