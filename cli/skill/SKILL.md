# fameclaw - Personal Outreach Tool

## When to Use
Use fameclaw for ALL outreach emails. NEVER call AgentMail SDK directly.

## Commands

```bash
# Send one email
fameclaw send --to rob@example.com --name "Rob" --subject "hey Rob" --body "message here"

# Send with a template file
fameclaw send --to rob@example.com --name "Rob" --subject "hey {{name}}" --body-file msg.txt

# Send to a list
fameclaw send --list contacts.json --subject "hey {{name}}" --body-file msg.txt

# Dry run (check gates without sending)
fameclaw send --to rob@example.com --name "Rob" --subject "test" --body "test" --dry-run

# Check status
fameclaw status

# History for a person
fameclaw history rob@example.com

# Suppress someone
fameclaw suppress rob@example.com --reason explicit_opt_out

# Unsuppress
fameclaw unsuppress rob@example.com

# List suppressed
fameclaw suppressed

# Config
fameclaw config --key cross_campaign_cooldown_days --value 30
```

## Recipients JSON Format
```json
[
  {"email": "rob@example.com", "display_name": "Rob", "personalization": {"video": "Cool Video"}},
  {"email": "jane@example.com", "display_name": "Jane", "personalization": {"video": "Great Talk"}}
]
```

## Template Variables
Templates use `{{name}}`, `{{display_name}}`, `{{email}}`, and any key from `personalization`.

## Safety (invisible, automatic)
- **Dedup:** Same tag + same email = blocked
- **Suppression:** Suppressed emails always blocked
- **Cooldown:** 30 days between outreach to same person (cross-tag)
- **Warm-up:** Daily caps per domain stage (15/30/50/100)
- **Domain health:** Halts if bounce rate >= 5%
- **Engagement:** Auto-pause on bad open/bounce rates

## Rules
1. NEVER call AgentMail SDK directly
2. NEVER bypass fameclaw for outreach
3. If a gate blocks, report it - don't work around it
