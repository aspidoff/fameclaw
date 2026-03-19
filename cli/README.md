# fameclaw CLI

Personal outreach tool with invisible safety nets. Sends emails through AgentMail with automatic dedup, suppression, warm-up, and domain health protection.

## Install

```bash
cd cli/
pip install -e .
```

## Usage

```bash
# Send one email
fameclaw send --to rob@example.com --name "Rob" --subject "hey Rob" --body "message"

# Send with a template file
fameclaw send --to rob@example.com --name "Rob" --subject "hey {{name}}" --body-file msg.txt

# Send to a list
fameclaw send --list contacts.json --subject "hey {{name}}" --body-file msg.txt

# Dry run
fameclaw send --to rob@example.com --name "Rob" --subject "test" --body "test" --dry-run

# Check status
fameclaw status

# History for a person
fameclaw history rob@example.com

# Suppress/unsuppress
fameclaw suppress rob@example.com --reason explicit_opt_out
fameclaw unsuppress rob@example.com
fameclaw suppressed
```

## Safety (automatic)

All gates run silently. The email either sends or you get a one-line reason why not.

- **Dedup** - same batch + same email = blocked
- **Suppression** - suppressed emails always blocked  
- **Cooldown** - 30 days between outreach to same person
- **Warm-up** - daily caps per domain stage (15 → 30 → 50 → 100)
- **Domain health** - halts all sending if hard bounce rate >= 5%
- **Engagement gating** - auto-pause on bad open/bounce rates

## Config

State lives in `~/.openclaw/outreach/`. Set config with:

```bash
fameclaw config --key cross_campaign_cooldown_days --value 30
fameclaw config --key default_from_inbox --value "lacie@souls.zip"
```

## Migration

Import existing outreach data:

```bash
python scripts/migrate_from_raw.py
```

Requires `AGENTMAIL_TOKEN` environment variable.
