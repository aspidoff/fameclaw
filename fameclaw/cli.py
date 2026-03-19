"""
fameclaw - personal outreach tool with invisible safety nets.
"""

import json
import time
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

import click
from rich.console import Console
from rich.table import Table

from .config import ConfigManager
from .suppressor import SuppressionManager
from .warmup import WarmupManager
from .bouncer import BounceManager
from .ledger import LedgerManager
from .templates import TemplateRenderer
from .validation import normalize_email, validate_can_spam
from .exceptions import OutreachError

console = Console()

DEFAULT_STATE_DIR = "~/.openclaw/outreach"


def _get_domain(email: str) -> str:
    return email.split("@")[1] if "@" in email else email


def _send_one(
    to: str,
    name: str,
    subject: str,
    body: str,
    from_inbox: str,
    tag: str,
    state_dir: str,
    dry_run: bool = False,
    personalization: dict = None,
) -> tuple[bool, str]:
    """
    Send one email through all safety gates.

    Returns (success, message).
    """
    to = normalize_email(to)
    domain = _get_domain(from_inbox)

    suppressor = SuppressionManager(state_dir)
    ledger = LedgerManager(state_dir)
    warmup = WarmupManager(state_dir)
    bouncer = BounceManager(state_dir)
    config = ConfigManager(state_dir).load()

    # Gate: suppression
    if suppressor.check(to):
        entry = suppressor.get(to)
        return False, f"Suppressed ({entry.reason})"

    # Gate: dedup (same tag = same batch, don't re-send)
    if ledger.check_dedup(tag, to):
        return False, "Already sent"

    # Gate: cooldown (30 days between outreach to same person)
    recent = ledger.get_recent_campaigns_for_recipient(to, config.cross_campaign_cooldown_days)
    if recent:
        return False, f"Contacted recently ({', '.join(recent)})"

    # Gate: warm-up cap
    inbox = warmup.get_or_create(domain)
    today = datetime.utcnow().date().isoformat()
    if inbox.sends_today_date != today:
        inbox.sends_today = 0
        inbox.sends_today_date = today
    if inbox.sends_today >= inbox.daily_cap_for_stage:
        return False, f"Daily cap reached ({inbox.daily_cap_for_stage}/day, stage {inbox.stage})"

    # Gate: engagement pause
    if inbox.paused:
        return False, f"Warm-up paused: {inbox.pause_reason}"

    # Gate: domain health
    at_risk, reason = bouncer.domain_at_risk(domain)
    if at_risk:
        return False, f"Domain at risk: {reason}"

    if dry_run:
        return True, "[dry run] Would send"

    # Pre-allocate
    pre_id = f"pre-{tag}-{to}-{int(time.time() * 1000)}"
    ledger.add_entry(
        campaign_id=tag,
        recipient_email=to,
        message_id=pre_id,
        status="sending",
    )

    # Send via AgentMail
    try:
        from agentmail import AgentMail
        client = AgentMail(api_key=os.environ.get("AGENTMAIL_TOKEN"))
        result = client.inboxes.messages.send(
            inbox_id=from_inbox,
            to=to,
            subject=subject,
            text=body,
        )
        msg_id = getattr(result, "message_id", None) or str(result)

        # Record success
        ledger.update_entry_status(pre_id, "sent")
        warmup.increment_sends_today(domain)
        warmup.increment_stage_sends(domain)
        bouncer.record_delivery_success(domain)

        return True, msg_id

    except Exception as e:
        ledger.update_entry_status(pre_id, "delivery_failed", error_message=str(e))
        return False, str(e)


# ── CLI ─────────────────────────────────────────────────────────

@click.group()
def cli():
    """fameclaw - personal outreach with invisible safety nets."""
    pass


@cli.command()
@click.option("--state-dir", default=DEFAULT_STATE_DIR, help="State directory")
def init(state_dir: str):
    """Set up fameclaw."""
    from .state import StateManager
    sm = StateManager(state_dir)
    sm._ensure_dir()

    config_mgr = ConfigManager(state_dir)
    try:
        config_mgr.load()
    except Exception:
        config_mgr.save(config_mgr._get_defaults())

    console.print("[green]✓[/green] fameclaw ready")
    console.print(f"  State: {Path(state_dir).expanduser()}")


@cli.command()
@click.option("--to", help="Recipient email")
@click.option("--name", default="", help="Recipient name")
@click.option("--subject", required=True, help="Subject (supports {{name}} etc)")
@click.option("--body", "body_text", default=None, help="Body text inline")
@click.option("--body-file", default=None, help="Body from file (supports {{name}} etc)")
@click.option("--from", "from_inbox", default=None, help="From inbox (default: config)")
@click.option("--list", "list_file", default=None, help="Recipients JSON file")
@click.option("--tag", default=None, help="Batch tag for dedup (default: auto)")
@click.option("--spacing", default=30, type=int, help="Seconds between sends (default: 30)")
@click.option("--dry-run", is_flag=True, help="Check gates without sending")
@click.option("--state-dir", default=DEFAULT_STATE_DIR, help="State directory")
def send(
    to: Optional[str],
    name: str,
    subject: str,
    body_text: Optional[str],
    body_file: Optional[str],
    from_inbox: Optional[str],
    list_file: Optional[str],
    tag: Optional[str],
    spacing: int,
    dry_run: bool,
    state_dir: str,
):
    """Send personal outreach emails."""
    # Resolve body
    if body_file:
        body_template = Path(body_file).expanduser().read_text()
    elif body_text:
        body_template = body_text
    else:
        console.print("[red]Error:[/red] Need --body or --body-file")
        raise SystemExit(1)

    # Resolve from
    if not from_inbox:
        config = ConfigManager(state_dir).load()
        from_inbox = config.default_from_inbox

    # Resolve recipients
    recipients = []
    if list_file:
        with open(Path(list_file).expanduser()) as f:
            recipients = json.load(f)
    elif to:
        recipients = [{"email": to, "display_name": name, "personalization": {}}]
    else:
        console.print("[red]Error:[/red] Need --to or --list")
        raise SystemExit(1)

    # Auto-tag
    if not tag:
        tag = f"outreach-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    # CAN-SPAM check (physical address)
    config = ConfigManager(state_dir).load()
    violations = validate_can_spam(body_template, config)
    if violations:
        for v in violations:
            console.print(f"[red]✗[/red] {v}")
        raise SystemExit(1)

    # Send
    sent = 0
    failed = 0
    total = len(recipients)

    for i, r in enumerate(recipients):
        email = r.get("email", r) if isinstance(r, dict) else r
        display_name = r.get("display_name", "") if isinstance(r, dict) else ""
        personalization = r.get("personalization", {}) if isinstance(r, dict) else {}

        # Render templates
        ctx = {"name": display_name, "display_name": display_name, "email": email, **personalization}
        rendered_subject, subj_err = TemplateRenderer._render_content(subject, ctx, email)
        if subj_err:
            console.print(f"[red]✗[/red] {email} - template error: {subj_err[0]}")
            failed += 1
            continue

        rendered_body, body_err = TemplateRenderer._render_content(body_template, ctx, email)
        if body_err:
            console.print(f"[red]✗[/red] {email} - template error: {body_err[0]}")
            failed += 1
            continue

        # Send
        prefix = f"[{i + 1}/{total}]" if total > 1 else ""
        success, msg = _send_one(
            to=email,
            name=display_name,
            subject=rendered_subject,
            body=rendered_body,
            from_inbox=from_inbox,
            tag=tag,
            state_dir=state_dir,
            dry_run=dry_run,
            personalization=personalization,
        )

        if success:
            sent += 1
            console.print(f"[green]✓[/green] {prefix} {email}")
        else:
            failed += 1
            console.print(f"[red]✗[/red] {prefix} {email} - {msg}")

        # Spacing between sends
        if success and not dry_run and i < total - 1:
            time.sleep(spacing)

    # Summary
    if total > 1:
        console.print(f"\nDone. Sent: {sent}, Skipped: {failed}")


@cli.command()
@click.option("--state-dir", default=DEFAULT_STATE_DIR)
def status(state_dir: str):
    """Show outreach status."""
    warmup = WarmupManager(state_dir)
    bouncer = BounceManager(state_dir)
    ledger = LedgerManager(state_dir)
    suppressor = SuppressionManager(state_dir)

    # Warm-up
    inboxes = warmup.list_all()
    if inboxes:
        t = Table(title="Domain Health")
        t.add_column("Domain")
        t.add_column("Stage")
        t.add_column("Today")
        t.add_column("Cap")
        t.add_column("Status")

        for inbox in inboxes:
            at_risk, _ = bouncer.domain_at_risk(inbox.domain)
            status_str = "[red]AT RISK[/red]" if at_risk else (
                "[yellow]PAUSED[/yellow]" if inbox.paused else "[green]OK[/green]"
            )
            t.add_row(
                inbox.domain,
                str(inbox.stage),
                str(inbox.sends_today),
                str(inbox.daily_cap_for_stage),
                status_str,
            )
        console.print(t)
    else:
        console.print("[dim]No domains tracked yet.[/dim]")

    # Quick stats
    total_sent = len(ledger.load().entries)
    total_suppressed = suppressor.count()
    console.print(f"\nTotal sent: {total_sent} | Suppressed: {total_suppressed}")


@cli.command()
@click.argument("email")
@click.option("--reason", default="manual", help="Reason (manual, explicit_opt_out, hard_bounce)")
@click.option("--state-dir", default=DEFAULT_STATE_DIR)
def suppress(email: str, reason: str, state_dir: str):
    """Add email to suppression list."""
    suppressor = SuppressionManager(state_dir)
    email = normalize_email(email)
    suppressor.add(email=email, reason=reason, added_by="user")
    console.print(f"[green]✓[/green] {email} suppressed ({reason})")


@cli.command()
@click.argument("email")
@click.option("--state-dir", default=DEFAULT_STATE_DIR)
def unsuppress(email: str, state_dir: str):
    """Remove email from suppression list."""
    suppressor = SuppressionManager(state_dir)
    email = normalize_email(email)
    if suppressor.remove(email):
        console.print(f"[green]✓[/green] {email} unsuppressed")
    else:
        console.print(f"[dim]{email} was not suppressed[/dim]")


@cli.command()
@click.option("--state-dir", default=DEFAULT_STATE_DIR)
def suppressed(state_dir: str):
    """List suppressed emails."""
    suppressor = SuppressionManager(state_dir)
    entries = suppressor.list_all()

    if not entries:
        console.print("[dim]No suppressed emails.[/dim]")
        return

    t = Table(title=f"Suppressed ({len(entries)})")
    t.add_column("Email")
    t.add_column("Reason")
    t.add_column("Added")

    for e in entries:
        t.add_row(e.email, e.reason, e.added_at[:10])

    console.print(t)


@cli.command()
@click.option("--key", required=True, help="Config key")
@click.option("--value", required=True, help="Config value")
@click.option("--state-dir", default=DEFAULT_STATE_DIR)
def config(key: str, value: str, state_dir: str):
    """Set a config value."""
    try:
        config_mgr = ConfigManager(state_dir)
        config_mgr.set_value(key, value)
        console.print(f"[green]✓[/green] {key} = {value}")
    except OutreachError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@cli.command()
@click.argument("email")
@click.option("--state-dir", default=DEFAULT_STATE_DIR)
def history(email: str, state_dir: str):
    """Show send history for an email."""
    ledger = LedgerManager(state_dir)
    email = normalize_email(email)
    entries = ledger.get_by_recipient(email)

    if not entries:
        console.print(f"[dim]No history for {email}[/dim]")
        return

    t = Table(title=f"History: {email}")
    t.add_column("Date")
    t.add_column("Tag")
    t.add_column("Status")

    for e in entries:
        t.add_row(e.sent_at[:10], e.campaign_id, e.status)

    console.print(t)
