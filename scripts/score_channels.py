#!/usr/bin/env python3
# Copyright (c) 2026 Pocketsnap LLC. Licensed under FSL-1.1-MIT.
# Use is permitted for non-competing purposes. Competing use requires a license.
# Converts to MIT on 2028-03-18. See LICENSE-FSL.
"""FameClaw Audience Matcher — Score scraped channels against a brand's audience profile.

Reads a CSV of scraped channels + an audience profile, outputs a scored/ranked CSV
with match scores, match type (demographic vs authority), and content category tags.

Usage:
    python3 score_channels.py --csv channels.csv --profile audience.json --output scored.csv
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter

# Content category keywords — used to tag channels
CATEGORY_KEYWORDS = {
    "Beauty & Skincare": [
        "beauty", "skincare", "makeup", "cosmetic", "skin care", "anti-aging",
        "foundation", "lipstick", "skinroutine", "get ready with me", "grwm",
        "dermatologist", "esthetician", "glow up", "hair care", "nails",
    ],
    "Fitness & Health": [
        "fitness", "workout", "gym", "exercise", "weight loss", "muscle",
        "nutrition", "supplement", "protein", "health", "wellness", "yoga",
        "crossfit", "running", "bodybuilding", "diet", "meal prep",
    ],
    "Tech & Gadgets": [
        "tech", "gadget", "smartphone", "laptop", "review", "unboxing",
        "software", "app", "coding", "programming", "ai", "robot",
        "computer", "iphone", "android", "camera", "gear",
    ],
    "Fashion & Lifestyle": [
        "fashion", "style", "outfit", "clothing", "thrift", "haul",
        "lookbook", "ootd", "wardrobe", "luxury", "lifestyle", "vlog",
        "aesthetic", "minimalist", "sustainable fashion",
    ],
    "Food & Cooking": [
        "food", "cooking", "recipe", "chef", "kitchen", "baking",
        "restaurant", "meal", "foodie", "taste test", "mukbang",
        "grocery", "healthy eating", "vegan", "keto",
    ],
    "E-commerce & Business": [
        "ecommerce", "e-commerce", "dropshipping", "shopify", "amazon fba",
        "entrepreneur", "business", "startup", "side hustle", "passive income",
        "make money", "online business", "selling", "retail", "wholesale",
    ],
    "TikTok & Social Media": [
        "tiktok", "tiktok shop", "social media", "instagram", "content creator",
        "influencer", "viral", "algorithm", "followers", "engagement",
        "monetization", "creator fund", "brand deal", "ugc",
    ],
    "Finance & Investing": [
        "finance", "investing", "stock", "crypto", "money", "budget",
        "savings", "real estate", "trading", "wealth", "financial",
        "retirement", "credit", "debt", "tax",
    ],
    "Gaming": [
        "gaming", "gamer", "gameplay", "playthrough", "stream", "twitch",
        "esports", "console", "pc gaming", "minecraft", "fortnite",
        "call of duty", "nintendo", "xbox", "playstation",
    ],
    "Education & Tutorial": [
        "tutorial", "how to", "learn", "course", "education", "teach",
        "guide", "tips", "masterclass", "lesson", "training", "academy",
        "study", "school", "university",
    ],
    "Home & DIY": [
        "home", "diy", "decor", "interior", "renovation", "garden",
        "organization", "cleaning", "furniture", "apartment", "house",
        "craft", "handmade", "woodworking",
    ],
    "Parenting & Family": [
        "mom", "dad", "parent", "baby", "kid", "family", "toddler",
        "pregnancy", "motherhood", "fatherhood", "children", "newborn",
    ],
    "Pets & Animals": [
        "pet", "dog", "cat", "puppy", "kitten", "animal", "vet",
        "pet care", "grooming", "training", "rescue",
    ],
    "Travel & Outdoor": [
        "travel", "adventure", "outdoor", "camping", "hiking", "explore",
        "vacation", "destination", "backpacking", "road trip", "van life",
    ],
}

# Authority signal keywords
AUTHORITY_SIGNALS = [
    "doctor", "dr.", "md", "phd", "certified", "licensed", "registered",
    "professional", "expert", "specialist", "coach", "trainer", "therapist",
    "nutritionist", "dietitian", "pharmacist", "nurse", "engineer",
    "consultant", "advisor", "founder", "ceo", "years of experience",
    "board certified", "published", "award", "degree",
]

# Demographic signal patterns
AGE_PATTERNS = [
    (r"\b(?:teen|teenager|gen ?z)\b", "13-24"),
    (r"\b(?:college|university|student|20s)\b", "18-25"),
    (r"\b(?:millennial|30s|young professional)\b", "25-40"),
    (r"\b(?:40s|middle.?age|established)\b", "35-55"),
    (r"\b(?:50s|60s|senior|retired|boomer|mature)\b", "50+"),
]

GENDER_PATTERNS = [
    (r"\b(?:mom|mother|woman|women|girl|she|her|wife|feminine|queen|goddess|lady|ladies)\b", "female"),
    (r"\b(?:dad|father|man|men|guy|he|him|husband|masculine|king|bro|dude)\b", "male"),
]


def categorize_channel(name, handle, description, channel_url=""):
    """Tag a channel with content categories based on name + description."""
    text = f"{name} {handle} {description}".lower()
    scores = {}

    for category, keywords in CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits >= 2:
            scores[category] = hits

    # Sort by hit count, return top 3
    sorted_cats = sorted(scores.items(), key=lambda x: -x[1])
    return [cat for cat, _ in sorted_cats[:3]]


def detect_authority(name, description):
    """Check for authority signals in channel info."""
    text = f"{name} {description}".lower()
    found = [sig for sig in AUTHORITY_SIGNALS if sig in text]
    return found


def detect_demographics(name, description):
    """Extract demographic signals from channel info."""
    text = f"{name} {description}".lower()
    demos = {}

    for pattern, age_range in AGE_PATTERNS:
        if re.search(pattern, text, re.I):
            demos["age_hint"] = age_range
            break

    for pattern, gender in GENDER_PATTERNS:
        if re.search(pattern, text, re.I):
            demos["gender_hint"] = gender
            break

    return demos


def compute_match_score(channel_categories, channel_authority, channel_demos,
                        target_categories, target_demographics, target_authority_preferred):
    """
    Score 0-100 how well a channel matches the audience profile.

    Scoring:
    - Category overlap: 0-50 points
    - Demographic match: 0-30 points
    - Authority signals: 0-20 points
    """
    score = 0
    match_type = "none"
    reasons = []

    # Category match (0-50)
    if target_categories and channel_categories:
        target_set = set(c.lower() for c in target_categories)
        channel_set = set(c.lower() for c in channel_categories)
        overlap = target_set & channel_set
        if overlap:
            cat_score = min(50, len(overlap) * 25)
            score += cat_score
            reasons.append(f"category:{','.join(overlap)}")

    # Demographic match (0-30)
    demo_score = 0
    if target_demographics:
        t_age = target_demographics.get("age_range", "")
        t_gender = target_demographics.get("gender", "")
        c_age = channel_demos.get("age_hint", "")
        c_gender = channel_demos.get("gender_hint", "")

        if t_gender and c_gender:
            if t_gender.lower() == c_gender.lower():
                demo_score += 15
                reasons.append(f"gender:{c_gender}")
            elif t_gender.lower() == "all":
                demo_score += 10
        if t_age and c_age:
            # Simple overlap check
            if t_age in c_age or c_age in t_age:
                demo_score += 15
                reasons.append(f"age:{c_age}")

    score += demo_score
    if demo_score > 10:
        match_type = "demographic"

    # Authority (0-20)
    if channel_authority:
        auth_score = min(20, len(channel_authority) * 10)
        score += auth_score
        reasons.append(f"authority:{','.join(channel_authority[:3])}")
        if auth_score >= 10:
            match_type = "authority" if match_type == "none" else "demographic+authority"

    # If no category match but has authority, still viable
    if score == 0 and channel_authority:
        score = 15
        match_type = "authority"

    return min(100, score), match_type, reasons


def score_csv(input_csv, profile_json, output_csv):
    """Read channels CSV, score each against profile, write scored CSV."""
    with open(profile_json) as f:
        profile = json.load(f)

    target_categories = profile.get("target_categories", [])
    target_demographics = profile.get("target_demographics", {})
    target_authority = profile.get("authority_preferred", False)

    rows = []
    with open(input_csv, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            rows.append(row)

    # New columns: category, match_score, match_type, match_reasons
    new_header = header + ["content_category", "match_score", "match_type", "match_reasons"]

    scored_rows = []
    for row in rows:
        name = row[0] if len(row) > 0 else ""
        handle = row[1] if len(row) > 1 else ""
        description = row[10] if len(row) > 10 else ""

        categories = categorize_channel(name, handle, description)
        authority = detect_authority(name, description)
        demographics = detect_demographics(name, description)

        score, match_type, reasons = compute_match_score(
            categories, authority, demographics,
            target_categories, target_demographics, target_authority
        )

        row_extended = row + [
            "; ".join(categories) if categories else "uncategorized",
            str(score),
            match_type,
            "; ".join(reasons) if reasons else "",
        ]
        scored_rows.append((score, row_extended))

    # Sort by score descending
    scored_rows.sort(key=lambda x: -x[0])

    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(new_header)
        for score, row in scored_rows:
            writer.writerow(row)

    # Stats
    total = len(scored_rows)
    with_email = sum(1 for _, r in scored_rows if len(r) > 9 and r[9].strip() and r[9].strip() != ";")
    high_match = sum(1 for s, _ in scored_rows if s >= 50)
    mid_match = sum(1 for s, _ in scored_rows if 25 <= s < 50)
    low_match = sum(1 for s, _ in scored_rows if 0 < s < 25)
    no_match = sum(1 for s, _ in scored_rows if s == 0)

    demo_count = sum(1 for _, r in scored_rows if "demographic" in r[-2])
    auth_count = sum(1 for _, r in scored_rows if "authority" in r[-2])

    print(f"\n=== Audience Match Results ===")
    print(f"  Total channels: {total}")
    print(f"  With email: {with_email}")
    print(f"  High match (50+): {high_match}")
    print(f"  Mid match (25-49): {mid_match}")
    print(f"  Low match (1-24): {low_match}")
    print(f"  No match: {no_match}")
    print(f"  Demographic matches: {demo_count}")
    print(f"  Authority matches: {auth_count}")
    print(f"\n  Output: {output_csv}")

    # Show top 10
    print(f"\n  Top 10 matches:")
    for i, (score, row) in enumerate(scored_rows[:10], 1):
        name = row[0]
        handle = row[1]
        email = "📧" if (len(row) > 9 and row[9].strip() and row[9].strip() != ";") else "  "
        cat = row[-4] if len(row) >= 4 else ""
        mtype = row[-2] if len(row) >= 2 else ""
        print(f"  {i:>3}. [{score:>3}] {email} {name[:30]:<30} @{handle:<20} {mtype:<15} {cat[:40]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FameClaw Audience Matcher")
    parser.add_argument("--csv", required=True, help="Input channels CSV")
    parser.add_argument("--profile", required=True, help="Audience profile JSON")
    parser.add_argument("--output", required=True, help="Output scored CSV")
    args = parser.parse_args()

    score_csv(args.csv, args.profile, args.output)
