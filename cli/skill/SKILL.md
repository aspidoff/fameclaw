# fameclaw - Personal Outreach Tool

## When to Use
Use fameclaw for ALL outreach emails. NEVER call email SDKs directly.

## Commands
```bash
fameclaw send --to rob@example.com --name "Rob" --subject "hey" --body "message"
fameclaw send --list contacts.json --subject "hey {{name}}" --body-file msg.txt
fameclaw send --to rob@example.com --name "Rob" --subject "test" --body "test" --dry-run
fameclaw status
fameclaw history rob@example.com
fameclaw suppress rob@example.com --reason explicit_opt_out
fameclaw unsuppress rob@example.com
fameclaw suppressed
fameclaw config --key provider --value smtp
fameclaw config --key smtp_host --value smtp.gmail.com
```

## Providers
- `agentmail` (default) - needs AGENTMAIL_TOKEN env var
- `smtp` - needs smtp_host, smtp_port, smtp_user, smtp_pass_env in config

## Recipients JSON
```json
[{"email": "rob@example.com", "display_name": "Rob", "personalization": {"video": "Cool Video"}}]
```

## Template Variables
`{{name}}`, `{{display_name}}`, `{{email}}`, plus any key from `personalization`.

## Rules
1. NEVER call email SDKs directly - use fameclaw
2. If a gate blocks, report it - don't work around it
