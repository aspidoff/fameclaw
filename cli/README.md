# fameclaw CLI

Personal outreach with invisible safety nets. Supports AgentMail and SMTP.

## Install

```bash
cd cli && pip install -e .
```

## Usage

```bash
fameclaw send --to rob@example.com --name "Rob" --subject "hey" --body "message"
fameclaw send --list contacts.json --subject "hey {{name}}" --body-file msg.txt
fameclaw status
fameclaw history rob@example.com
fameclaw suppress rob@example.com
```

## Providers

**AgentMail** (default): Set `AGENTMAIL_TOKEN` env var.

**SMTP** (Gmail, etc):
```bash
fameclaw config --key provider --value smtp
fameclaw config --key smtp_host --value smtp.gmail.com
fameclaw config --key smtp_user --value you@gmail.com
fameclaw config --key smtp_pass_env --value GMAIL_APP_PASSWORD
```

## Safety (automatic)

- Dedup per batch
- Suppression list
- 30-day cooldown between contacts
- Warm-up caps (15 → 30 → 50 → 100/day)
- Domain health halt at 5% bounce rate

## Files

4 Python files, 578 lines total.
