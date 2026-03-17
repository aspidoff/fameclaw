---
name: fameclaw
description: YouTube creator outreach prospecting — find channels by niche, extract emails and stats, discover related channels, and batch-scrape to CSV. Use when asked to find YouTube creators, source creator emails, build influencer/outreach lists, prospect YouTube channels for partnerships, or scrape channel data at scale. Triggers on "find YouTube creators", "source emails", "build outreach list", "find channels in [niche]", "YouTube prospecting", "creator outreach", "scrape YouTube emails", "find influencers". Supports cron-based automated runs with configurable targets.
---

# FameClaw — YouTube Creator Outreach Prospector

Find YouTube creators by niche, extract their emails + stats, discover related channels via recommendations, and batch-scrape everything to CSV.

## Onboarding Flow

For new users, always run the onboarding flow before prospecting. This is a multi-turn conversational flow — ask, scan, clarify, propose, confirm.

### Step 1: Ask for brand info
Ask the user two things:
1. **Brand name**
2. **Website URL**

Keep it casual, one message: "What's your brand name and website?"

### Step 2: Scan the site
```bash
bash scripts/onboard.sh --brand "BrandName" --url "https://example.com" --output <work_dir>/scan.json
```

Read the output JSON. It contains: title, meta description, industry signals, platform, social profiles, navigation, headlines, body text preview.

### Step 3: Determine product category
From the scan, identify the product/service category. Present your assessment to the user:

- State what you found: "Looks like [Brand] is a [category] — [brief description from scan]"
- **If confident (strong signals):** State the category and move to Step 4
- **If unclear (weak/mixed signals):** Ask one focused question: "I see signals for [X] and [Y] — which best describes your product?"

Product categories to detect:
- **Physical products** (e-commerce, DTC, retail)
- **Digital products** (courses, templates, software, ebooks)
- **SaaS / App** (platform, tool, API)
- **Services** (agency, consulting, freelance)
- **Marketplace** (connecting buyers/sellers)
- **Creator tools** (helping influencers/creators)
- **Info products / Education** (coaching, masterclass)

### Step 4: Propose influencer categories + follower tiers
Based on the product category, propose:

**Influencer categories** — 2-4 YouTube creator types that would be relevant. Examples:

| Product Category | Suggested Influencer Types |
|---|---|
| Physical products (beauty) | Beauty reviewers, Get Ready With Me, haul creators, skincare routine |
| Physical products (tech) | Tech reviewers, unboxing channels, comparison/versus creators |
| Physical products (fitness) | Fitness vloggers, supplement reviewers, workout routine channels |
| SaaS / App | Tutorial creators, productivity YouTubers, tech tool reviewers |
| Digital products (courses) | Side hustle channels, "make money online" creators, niche educators |
| Marketplace | Reseller/flipper channels, ecommerce tutorial creators |
| Creator tools | Creator economy channels, YouTube growth tips, content strategy |
| Services (agency) | Business/entrepreneur channels, industry-specific educators |

**Follower tiers** — Propose 2-3 size ranges with rationale:

| Tier | Range | Best For |
|---|---|---|
| Nano | 1K–10K | High engagement, cheap/free collabs, UGC content |
| Micro | 10K–50K | Niche authority, good engagement, affordable |
| Mid | 50K–200K | Established audience, professional content, moderate cost |
| Macro | 200K–1M | Broad reach, brand awareness, higher cost |

Present like: "For [product], I'd target these creator types: [list]. And these size ranges: [tiers with why]. Sound right, or want to adjust?"

### Step 5: Build audience profile
Based on all answers, create an `audience.json` file (the onboard script generates a template):

```json
{
  "brand": "BrandName",
  "url": "https://example.com",
  "target_categories": ["Beauty & Skincare", "Fashion & Lifestyle"],
  "target_demographics": {
    "age_range": "25-40",
    "gender": "female",
    "interests": ["skincare routines", "clean beauty", "wellness"],
    "location": "US"
  },
  "authority_preferred": true
}
```

Available categories for `target_categories`:
Beauty & Skincare, Fitness & Health, Tech & Gadgets, Fashion & Lifestyle, Food & Cooking, E-commerce & Business, TikTok & Social Media, Finance & Investing, Gaming, Education & Tutorial, Home & DIY, Parenting & Family, Pets & Animals, Travel & Outdoor

Ask the user: **"Who is your typical customer?"** — age range, gender, interests, lifestyle. This determines whether we look for demographic-match or authority-match creators (per Fraser Cottrell's UGC casting framework).

### Step 6: Confirm and generate config
Once the user approves (or adjusts), generate both `config.json` and `audience.json`. Config includes:
- 15-30 tailored search queries (long-tail, video-style) based on chosen categories
- `max_subs` set to the upper bound of the highest chosen tier
- `target_emails` — ask user how many they want, or suggest 100-500 based on scope
- `work_dir` for organized output

Write the config, show a summary, and ask "Ready to start scraping?"

### Step 7: Run prospector
```bash
bash scripts/prospect.sh --config config.json
```

For targets >100, set up a cron job (see Cron Automation below).

### Step 8: Score and rank results
After scraping completes, score all channels against the audience profile:

```bash
python3 scripts/score_channels.py --csv channels.csv --profile audience.json --output scored_channels.csv
```

This adds 4 columns to the CSV:
- `content_category` — auto-detected channel niche (e.g. "Beauty & Skincare; Fashion & Lifestyle")
- `match_score` — 0-100 based on category overlap + demographic signals + authority signals
- `match_type` — "demographic", "authority", "demographic+authority", or "none"
- `match_reasons` — why the score was given

Output is sorted by match score descending. Present top results to the user grouped by match type:
- **Demographic matches** — creators whose audience looks like the brand's customers
- **Authority matches** — creators with professional credibility in the niche
- **No match** — off-niche channels (may still be useful for broad awareness)

## Gmail Outreach

### Prerequisites
FameClaw uses Google's official [Workspace CLI](https://github.com/googleworkspace/cli) (`gws`) for sending emails. One-time setup:

1. **Install gws** — download from https://github.com/googleworkspace/cli/releases
2. **Authenticate** — run `gws auth login -s gmail` (opens browser, click Allow)
3. **Verify** — run `gws auth status` to confirm

That's it. No Google Cloud Console, no API keys, no app passwords.

### Step 9: Create outreach template
Create an email template (plain text or HTML) with personalization variables:

```
Hi {{channel_name}},

I came across your channel (@{{handle}}) and loved your content.

We're building {{brand}} ({{website}}) and think there's a great fit
for a collaboration. Would you be open to a quick chat?

Best,
[Your name]
```

Available template variables:
- `{{channel_name}}` — creator's channel name
- `{{handle}}` — @handle
- `{{subscribers}}` — subscriber count
- `{{avg_views}}` — average views
- `{{email}}` — creator's email
- `{{brand}}` — your brand name
- `{{website}}` — your website URL

### Step 10: Send outreach
```bash
# Dry run first — preview without sending
bash scripts/outreach.sh \
  --csv scored.csv \
  --template template.html \
  --brand "MyBrand" \
  --website "https://mybrand.com" \
  --rate 30 \
  --min-score 25 \
  --dry-run

# Send for real
bash scripts/outreach.sh \
  --csv scored.csv \
  --template template.html \
  --brand "MyBrand" \
  --website "https://mybrand.com" \
  --rate 30 \
  --min-score 25
```

| Flag | Default | Description |
|------|---------|-------------|
| `--csv` | required | Scored CSV from score_channels.py |
| `--template` | required | Email template file (.txt or .html) |
| `--subject` | "Partnership opportunity with {{brand}}" | Email subject (supports variables) |
| `--brand` | "" | Brand name for template |
| `--website` | "" | Website URL for template |
| `--rate` | 30 | Emails per hour |
| `--min-score` | 0 | Only email channels with this match score or higher |
| `--from` | "" | Send-as alias (if configured in Gmail) |
| `--dry-run` | false | Preview without sending |

### Outreach features
- **Deduplication** — tracks sent emails in `outreach_logs/sent.txt`, never double-sends
- **Rate limiting** — configurable emails/hour (default 30, safe for Gmail)
- **Email cleaning** — auto-filters junk emails (image files, noreply, test addresses)
- **Score filtering** — only email high-match channels with `--min-score`
- **Logging** — full run logs + sent/failed tracking
- **Dry run** — always preview before sending

### Check replies
```bash
# See unread replies
gws gmail +triage --query "is:unread"

# Reply to a specific message
gws gmail +reply --message-id <id> --body "Thanks for getting back to me!"
```

## Quick Start (advanced users)

### Single channel extraction
```bash
bash scripts/extract_channel_data.sh "https://youtube.com/@handle" output.csv
```

### Find related channels from a seed
```bash
bash scripts/find_related_channels.sh "https://youtube.com/@handle" 20
```

### Email-only extraction
```bash
bash scripts/extract_email.sh "https://youtube.com/@handle"
```

### Batch prospecting (the main pipeline)
```bash
bash scripts/prospect.sh \
  --queries "tiktok shop tutorial" "dropshipping beginner" "faceless youtube" \
  --target 100 \
  --output channels.csv \
  --max-subs 100000 \
  --batch-size 200
```

Or with a config file:
```bash
bash scripts/prospect.sh --config config.json
```

## Config JSON

```json
{
  "queries": ["tiktok shop affiliate", "faceless youtube channel"],
  "target_emails": 100,
  "output": "channels.csv",
  "max_subs": 100000,
  "batch_size": 200,
  "work_dir": "./prospect-run",
  "cron_name": "my-prospect-job"
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `queries` | required | YouTube search queries (spaces OK, auto-encoded) |
| `target_emails` | 100 | Stop after finding this many emails |
| `output` | fameclaw_channels.csv | Output CSV path |
| `max_subs` | 0 (no limit) | Skip channels above this subscriber count |
| `batch_size` | 200 | Max channels to process per run |
| `work_dir` | output dir | Directory for queue/state/log files |
| `cron_name` | "" | OpenClaw cron job name — auto-removes when target hit |

## Cron Automation

Set up recurring runs to hit a target email count over time:

```bash
openclaw cron add \
  --name "my-prospect-job" \
  --every 30m \
  --session isolated \
  --model haiku \
  --light-context \
  --timeout-seconds 1800 \
  --message "Run: bash <skill-dir>/scripts/prospect.sh --config <path>/config.json" \
  --announce --to "telegram:<chat_id>"
```

The script auto-removes the cron job when the target is reached (if `cron_name` is set in config).

## Pipeline Logic

1. **Seed** — search YouTube for videos matching queries, extract uploader channel handles
2. **Pre-filter** — if `max_subs` set, fetch channel page and skip channels above threshold
3. **Extract** — for each channel: name, handle, subscribers, video count, avg/median/min/max views, email, description, external links
4. **Expand** — every 8th channel with email, discover related channels via YouTube's recommendation sidebar (top 3 videos → sidebar channels, ranked by frequency)
5. **Deduplicate** — tracks processed channels across runs via state files
6. **Repeat** — cron triggers next batch until target reached

## Email Discovery

1. Scan YouTube channel page HTML for emails in metadata/description
2. Derive vanity domain from handle (strips "live", "official", "hq", etc.)
3. Check vanity domain root + `/contact` + `/about` + `/contact-us`
4. Filter junk (image filenames, google/youtube domains, noreply, test emails)

## CSV Schema

```
channel_name,handle,subscribers,total_videos,avg_views,median_views,min_views,max_views,videos_sampled,email,description,external_links,channel_url
```

## Query Design Tips

- Use **video-style queries** (how-to, tutorial, results) — surfaces actual creators, not brands
- Long-tail queries find smaller channels: "tiktok shop first sale beginner" vs "tiktok shop"
- Group queries by niche for organized prospecting runs
- 10-15 queries typically yields 60-100 seed channels per run

### Example queries by niche

**TikTok Shop:** `tiktok shop affiliate tutorial`, `tiktok shop beginner first sale`, `tiktok shop income report`
**Faceless YouTube:** `faceless youtube channel tutorial`, `youtube automation passive income`, `cash cow channel ideas`
**Dropshipping:** `dropshipping tutorial beginner shopify`, `tiktok organic dropshipping`, `winning products research`
**Social media monetization:** `UGC creator how to start`, `how to get brand deals small creator`, `social media side hustle income`

## Limitations

- YouTube hides business emails behind captcha — script uses vanity domain workaround
- View counts sampled from visible videos (~30-200)
- Subscriber counts are approximate (YouTube rounds)
- Related channel discovery follows YouTube's algorithm — may drift off-niche over time
- Rate limiting: ~0.5s between channels, ~1s between related channel lookups

## Requirements

- `curl`, `python3` (standard on macOS/Linux)
- No API keys needed
- OpenClaw (optional, for cron automation)
