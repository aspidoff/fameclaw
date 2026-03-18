---
name: fameclaw
description: YouTube creator outreach prospecting — find channels by niche, extract emails and stats, discover related channels, and batch-scrape to CSV. Use when asked to find YouTube creators, source creator emails, build influencer/outreach lists, prospect YouTube channels for partnerships, or scrape channel data at scale. Triggers on "find YouTube creators", "source emails", "build outreach list", "find channels in [niche]", "YouTube prospecting", "creator outreach", "scrape YouTube emails", "find influencers". Supports cron-based automated runs with configurable targets.
---

# FameClaw — YouTube Creator Outreach Prospector

Find YouTube creators by niche, extract their emails + stats, discover related channels via recommendations, and batch-scrape everything to CSV.

## Onboarding Flow

For new users, always run the onboarding flow before prospecting. This is a multi-turn conversational flow — ask, scan, clarify, propose, confirm.

### Step 1: Ask for brand info + connect Gmail
Ask the user for:
1. **Brand name**
2. **Website URL**
3. **Connect Gmail** — collect these details:
   - **Gmail login** — the account they authenticate with (e.g. admin@company.com)
   - **App password** — from myaccount.google.com/apppasswords
   - **Send-as email** (optional) — if they want to send from an alias (e.g. daniel@company.com). Google Workspace accounts often have aliases configured in Gmail → Settings → Accounts → "Send mail as". If they don't have one, the login email is used.
   - **Display name** — how they appear in emails (e.g. "Daniel from Fameswap")

Store credentials:
```bash
# ~/.config/fameclaw/gmail.json
{
  "email": "admin@company.com",
  "app_password": "xxxx xxxx xxxx xxxx",
  "from_email": "daniel@company.com",
  "display_name": "Daniel from Fameswap"
}
```
Save to `~/.config/fameclaw/gmail.json` with mode 600. Then test:
```bash
python3 scripts/gmail.py test
```

Keep it casual: "What's your brand name and website? And let's connect your Gmail — what email do you send outreach from?"

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
FameClaw uses Gmail App Passwords for sending (SMTP) and tracking replies (IMAP).

**During onboarding, after collecting brand info (Step 1), run Gmail setup:**

```bash
bash scripts/gmail_auth.sh setup
```

This prompts for:
1. Gmail address
2. App password (guide shown in the prompt)
3. Display name (e.g. "Alex from MyBrand")

Credentials stored at `~/.config/fameclaw/gmail.json` (mode 600, same pattern as OpenClaw config).

To verify: `bash scripts/gmail_auth.sh test`

### Step 9: Configure outreach campaign
Create an `outreach.json` config:

```json
{
  "brand": "MyBrand",
  "website": "https://mybrand.com",
  "sender_name": "Alex",
  "gmail_creds": "gmail_creds.json",
  "current_partnerships": ["@CreatorA", "@CreatorB", "@CreatorC"],
  "rate": 30,
  "min_score": 25,
  "max_per_run": 50
}
```

| Field | Description |
|-------|-------------|
| `brand` | Your brand name |
| `website` | Your website URL |
| `sender_name` | Sign-off name in emails |
| `current_partnerships` | 2-3 creators you're currently working with (social proof) |
| `rate` | Emails per hour (default 30, safe for Gmail) |
| `min_score` | Only email channels with this match score or higher |
| `max_per_run` | Max emails per run |

### Step 10: Run outreach pipeline

The pipeline has 4 commands:

```bash
# 1. Send first emails (fetches recent videos per creator for personalization)
python3 scripts/outreach.py send --csv scored.csv --config outreach.json --dry-run
python3 scripts/outreach.py send --csv scored.csv --config outreach.json

# 2. Check for replies (moves responders to NEGOTIATE stage)
python3 scripts/outreach.py check-replies --config outreach.json

# 3. Send follow-ups to non-responders (auto-timed: 3 days, then 5 days)
python3 scripts/outreach.py followup --config outreach.json --dry-run
python3 scripts/outreach.py followup --config outreach.json

# 4. Check campaign status
python3 scripts/outreach.py status --config outreach.json
```

### Email sequence
Three-stage sequence, all auto-generated and personalized per creator:

**Email 1 (Initial)** — short, mentions a specific recent video, names 2-3 current partnerships as social proof, asks for a quick chat.

**Email 2 (Follow-up, day 3)** — bump, references a different video, keeps it casual.

**Email 3 (Final follow-up, day 8)** — last touch, respects their time, clear CTA.

Each email:
- Mentions a **specific video** from the creator's channel (fetched live)
- References **current partnerships** (social proof from config)
- Is **short** — 3-5 sentences max
- Stops automatically if the creator **replies**

### Outreach features
- **Per-creator personalization** — fetches recent videos, mentions them by title
- **Social proof** — references current partnerships in the first email
- **Auto follow-ups** — 3 days after first, 5 days after follow-up 1
- **Reply detection** — checks inbox via `gws`, moves responders to NEGOTIATE
- **Deduplication** — campaign state tracks every contact, never double-sends
- **Rate limiting** — configurable emails/hour
- **Score filtering** — only email high-match channels
- **Dry run** — always preview before sending
- **Campaign state** — saved to `outreach_state.json`, survives restarts

### Step 11: Negotiate autonomously

FameClaw negotiates with creators automatically. The agent only asks the brand owner for info it doesn't have.

**First-time setup — ask brand owner once:**
```bash
python3 scripts/negotiate.py set-config --config outreach.json --key budget_min --value 1000
python3 scripts/negotiate.py set-config --config outreach.json --key budget_max --value 3000
python3 scripts/negotiate.py set-config --config outreach.json --key negotiation_style --value value-focused
# Styles: friendly (meet their price) / value-focused (counter, anchor low) / budget-strict (hard cap)
```

If these aren't set when a negotiation runs, `negotiate.py` will print what's missing — ask the brand owner and set it.

**Running negotiations:**
```bash
# Check replies + auto-respond (dry run first)
python3 scripts/negotiate.py check --config outreach.json --dry-run
python3 scripts/negotiate.py check --config outreach.json

# Dashboard
python3 scripts/negotiate.py status --config outreach.json
```

**What it does automatically:**
1. Reads every reply via IMAP
2. Classifies it: INTERESTED / PRICED / REDIRECT / DECLINED
3. INTERESTED → sends discovery questions (demographics, rates, past work)
4. PRICED → extracts their price, counters based on budget + style
5. REDIRECT → pivots to their preferred format, asks same questions
6. DECLINED → respects it, marks dead, re-engages in 3-6 months
7. No reply in 3 days → auto follow-up (max 3, then STALE)
8. Price too high → proposes alternatives (shorter format, affiliate, bundle)

**When it notifies the brand owner:**
- Missing config (budget, style) — asks once, stores forever
- Deal closed → "Leo agreed to 2 videos for $2K"
- Deal dead → "Leo declined. Parked for re-engagement."

**Full playbook:** `references/negotiation_playbook.md`

### Automate with cron
Set up follow-ups and reply checking on a schedule:

```bash
# Check replies + send follow-ups every 6 hours
openclaw cron add --name "outreach-followup" --every 6h \
  --session isolated --model haiku --timeout-seconds 300 \
  --message "Run: python3 scripts/outreach.py check-replies --config outreach.json && python3 scripts/outreach.py followup --config outreach.json"
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
