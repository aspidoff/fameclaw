---
name: fameclaw
description: YouTube creator outreach prospecting — find channels by niche, extract emails and stats, discover related channels, and batch-scrape to CSV. Use when asked to find YouTube creators, source creator emails, build influencer/outreach lists, prospect YouTube channels for partnerships, or scrape channel data at scale. Triggers on "find YouTube creators", "source emails", "build outreach list", "find channels in [niche]", "YouTube prospecting", "creator outreach", "scrape YouTube emails", "find influencers".
---

# FameClaw — YouTube Creator Outreach Prospector

Find YouTube creators by niche, extract their emails + stats, discover related channels via recommendations, and batch-scrape everything to CSV.

**Zero API keys. Fully local. All data stays on your machine.**

## Installation

FameClaw scripts live in this skill directory. Set the scripts path:

```bash
export FAMECLAW_SCRIPTS="${CLAUDE_SKILL_DIR}/../scripts"
export FAMECLAW_CONFIG_DIR="$HOME/.config/fameclaw"
mkdir -p "$FAMECLAW_CONFIG_DIR"
```

Requirements: `curl`, `python3` (standard on macOS/Linux). No API keys needed.

## Onboarding Flow

For new users, run the onboarding flow before prospecting. Multi-turn conversational flow.

### Step 1: Ask for brand info + connect Gmail

Collect: brand name, website URL, Gmail credentials (login, app password, optional send-as alias, display name).

Store at `~/.config/fameclaw/gmail.json` (mode 600):
```json
{
  "email": "admin@company.com",
  "app_password": "xxxx xxxx xxxx xxxx",
  "from_email": "daniel@company.com",
  "display_name": "Daniel from Fameswap"
}
```

Test: `python3 $FAMECLAW_SCRIPTS/gmail.py test`

### Step 2: Scan the site
```bash
bash $FAMECLAW_SCRIPTS/onboard.sh --brand "BrandName" --url "https://example.com" --output scan.json
```

### Step 3: Determine product category
From scan, identify category. Categories: Physical products, Digital products, SaaS/App, Services, Marketplace, Creator tools, Info products/Education.

If confident, state it. If unclear, ask one focused question.

### Step 4: Propose influencer categories + follower tiers
Based on product category, propose 2-4 YouTube creator types and 2-3 size ranges. See `${CLAUDE_SKILL_DIR}/references/category-mapping.md` for the full mapping table.

### Step 5: Build audience profile
Create `audience.json`:
```json
{
  "brand": "BrandName",
  "url": "https://example.com",
  "target_categories": ["Beauty & Skincare", "Fashion & Lifestyle"],
  "target_demographics": { "age_range": "25-40", "gender": "female", "interests": ["skincare"], "location": "US" },
  "authority_preferred": true
}
```

Ask: "Who is your typical customer?" — age, gender, interests, lifestyle.

### Step 6: Generate config
Write `config.json` with 15-30 tailored search queries, `max_subs`, `target_emails` (suggest 100-500).

### Step 7: Run prospector
```bash
bash $FAMECLAW_SCRIPTS/prospect.sh --config config.json
```

### Step 8: Score and rank
```bash
python3 $FAMECLAW_SCRIPTS/score_channels.py --csv channels.csv --profile audience.json --output scored_channels.csv
```

Adds: `content_category`, `match_score` (0-100), `match_type`, `match_reasons`. Present top results grouped by match type.

## Gmail Outreach

### Step 9: Configure outreach
Create `outreach.json`:
```json
{
  "brand": "MyBrand",
  "website": "https://mybrand.com",
  "sender_name": "Alex",
  "gmail_creds": "gmail_creds.json",
  "current_partnerships": ["@CreatorA", "@CreatorB"],
  "rate": 30,
  "min_score": 25,
  "max_per_run": 50
}
```

### Step 10: Run outreach
```bash
python3 $FAMECLAW_SCRIPTS/outreach.py send --csv scored.csv --config outreach.json --dry-run
python3 $FAMECLAW_SCRIPTS/outreach.py send --csv scored.csv --config outreach.json
python3 $FAMECLAW_SCRIPTS/outreach.py check-replies --config outreach.json
python3 $FAMECLAW_SCRIPTS/outreach.py followup --config outreach.json
python3 $FAMECLAW_SCRIPTS/outreach.py status --config outreach.json
```

Three-stage email sequence, auto-personalized per creator (mentions specific recent videos, current partnerships as social proof, 3-5 sentences max).

### Step 11: Negotiate
```bash
python3 $FAMECLAW_SCRIPTS/negotiate.py set-config --config outreach.json --key budget_min --value 1000
python3 $FAMECLAW_SCRIPTS/negotiate.py set-config --config outreach.json --key budget_max --value 3000
python3 $FAMECLAW_SCRIPTS/negotiate.py set-config --config outreach.json --key negotiation_style --value value-focused
python3 $FAMECLAW_SCRIPTS/negotiate.py check --config outreach.json
python3 $FAMECLAW_SCRIPTS/negotiate.py status --config outreach.json
```

Negotiation styles: friendly / value-focused / budget-strict. Full playbook: `${CLAUDE_SKILL_DIR}/references/negotiation_playbook.md`

## Scheduling (NanoClaw Tasks)

For recurring runs, use NanoClaw's task scheduler instead of OpenClaw cron.

**Prospecting (every 30 min until target hit):**

Create a task in your NanoClaw config or ask the agent to schedule:
```
Schedule a recurring task every 30 minutes:
Run: bash $FAMECLAW_SCRIPTS/prospect.sh --config /path/to/config.json
Stop when target email count is reached.
```

**Outreach follow-ups (every 6 hours):**
```
Schedule a recurring task every 6 hours:
Run: python3 $FAMECLAW_SCRIPTS/outreach.py check-replies --config outreach.json && python3 $FAMECLAW_SCRIPTS/outreach.py followup --config outreach.json
```

## Quick Start (advanced users)

```bash
# Single channel
bash $FAMECLAW_SCRIPTS/extract_channel_data.sh "https://youtube.com/@handle" output.csv

# Find related channels
bash $FAMECLAW_SCRIPTS/find_related_channels.sh "https://youtube.com/@handle" 20

# Email only
bash $FAMECLAW_SCRIPTS/extract_email.sh "https://youtube.com/@handle"

# Batch prospecting
bash $FAMECLAW_SCRIPTS/prospect.sh \
  --queries "tiktok shop tutorial" "dropshipping beginner" \
  --target 100 --output channels.csv --max-subs 100000
```

## Config JSON

| Field | Default | Description |
|-------|---------|-------------|
| `queries` | required | YouTube search queries |
| `target_emails` | 100 | Stop after this many emails |
| `output` | fameclaw_channels.csv | Output CSV path |
| `max_subs` | 0 (no limit) | Skip channels above this count |
| `batch_size` | 200 | Max channels per run |
| `work_dir` | output dir | State/queue/log directory |

## CSV Schema

```
channel_name,handle,subscribers,total_videos,avg_views,median_views,min_views,max_views,videos_sampled,email,description,external_links,channel_url
```

## NanoClaw Container Notes

When running inside a NanoClaw container, ensure these paths are mounted:
- `~/.config/fameclaw/` — credentials (read/write)
- Working directory for CSV output (read/write)
- The FameClaw scripts directory (read-only)

The scripts use only `curl` and `python3` — both available in NanoClaw's default container image.

## Limitations

- YouTube hides business emails behind captcha — uses vanity domain workaround
- View counts sampled from visible videos (~30-200)
- Subscriber counts approximate (YouTube rounds)
- Rate limiting: ~0.5s between channels, ~1s between related lookups
