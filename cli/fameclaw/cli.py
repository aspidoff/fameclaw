"""
fameclaw - personal outreach with invisible safety nets.
"""

import json
import time
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional
from datetime import datetime

import click
from rich.console import Console
from rich.table import Table
from jinja2 import Template

from .ledger import Ledger

console = Console()
STATE_DIR = "~/.openclaw/outreach"


def _render(template_str: str, ctx: dict) -> str:
    return Template(template_str, autoescape=False).render(**ctx)


def _send_email(to: str, subject: str, body: str, from_addr: str, config: dict) -> str:
    """Send one email. Returns message_id. Raises on failure."""
    provider = config.get("provider", "agentmail")

    if provider == "agentmail":
        from agentmail import AgentMail
        client = AgentMail(api_key=os.environ.get("AGENTMAIL_TOKEN"))
        result = client.inboxes.messages.send(
            inbox_id=from_addr, to=to, subject=subject, text=body,
        )
        return getattr(result, "message_id", "") or str(result)

    elif provider == "smtp":
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to
        host = config.get("smtp_host", "smtp.gmail.com")
        port = int(config.get("smtp_port", 587))
        user = config.get("smtp_user", from_addr)
        password = os.environ.get(config.get("smtp_pass_env", "SMTP_PASS"), "")
        with smtplib.SMTP(host, port) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(from_addr, [to], msg.as_string())
        return f"smtp-{int(time.time()*1000)}"

    else:
        raise ValueError(f"Unknown provider: {provider}. Use 'agentmail' or 'smtp'.")


def _check_gates(ledger: Ledger, to: str, tag: str, domain: str) -> Optional[str]:
    """Check all safety gates. Returns reason string if blocked, None if clear."""
    to = to.lower().strip()

    # Suppression
    suppressed, reason = ledger.is_suppressed(to)
    if suppressed:
        return f"Suppressed ({reason})"

    # Dedup
    if ledger.is_duped(to, tag):
        return "Already sent"

    # Cooldown
    recent = ledger.recently_contacted(to)
    if recent:
        return f"Contacted recently ({', '.join(recent)})"

    # Domain health
    ok, reason = ledger.check_domain_health(domain)
    if not ok:
        return f"Domain issue: {reason}"

    # Warm-up cap
    stage, cap = ledger.domain_stage(domain)
    today = ledger.domain_sends_today(domain)
    if today >= cap:
        return f"Daily cap ({cap}/day, stage {stage})"

    return None


# ── CLI ─────────────────────────────────────────────────────

@click.group()
def cli():
    """fameclaw - personal outreach with invisible safety nets."""
    pass


@cli.command()
def init():
    """Set up fameclaw."""
    ledger = Ledger(STATE_DIR)
    ledger._load()  # Creates default state
    console.print("[green]✓[/green] fameclaw ready")


@cli.command()
@click.option("--to", help="Recipient email")
@click.option("--name", default="", help="Recipient name")
@click.option("--subject", required=True, help="Subject (supports {{name}})")
@click.option("--body", "body_text", default=None, help="Body text inline")
@click.option("--body-file", default=None, help="Body from file (supports {{name}})")
@click.option("--from", "from_inbox", default=None, help="From address")
@click.option("--list", "list_file", default=None, help="Recipients JSON file")
@click.option("--tag", default=None, help="Batch tag for dedup (auto if omitted)")
@click.option("--spacing", default=30, type=int, help="Seconds between sends")
@click.option("--dry-run", is_flag=True, help="Check gates without sending")
def send(to, name, subject, body_text, body_file, from_inbox, list_file, tag, spacing, dry_run):
    """Send personal outreach emails."""
    ledger = Ledger(STATE_DIR)
    config = ledger.get_config()

    # Body
    if body_file:
        body_template = Path(body_file).expanduser().read_text()
    elif body_text:
        body_template = body_text
    else:
        console.print("[red]Need --body or --body-file[/red]")
        raise SystemExit(1)

    # From
    if not from_inbox:
        from_inbox = config.get("default_from", "lacie@souls.zip")

    # Recipients
    recipients = []
    if list_file:
        with open(Path(list_file).expanduser()) as f:
            recipients = json.load(f)
    elif to:
        recipients = [{"email": to, "display_name": name, "personalization": {}}]
    else:
        console.print("[red]Need --to or --list[/red]")
        raise SystemExit(1)

    # Auto-tag
    if not tag:
        tag = f"outreach-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    domain = from_inbox.split("@")[1] if "@" in from_inbox else from_inbox
    sent = 0
    total = len(recipients)

    for i, r in enumerate(recipients):
        email = (r.get("email", r) if isinstance(r, dict) else r).lower().strip()
        display_name = r.get("display_name", "") if isinstance(r, dict) else ""
        personalization = r.get("personalization", {}) if isinstance(r, dict) else {}

        ctx = {"name": display_name, "display_name": display_name, "email": email, **personalization}

        # Render
        try:
            rendered_subject = _render(subject, ctx)
            rendered_body = _render(body_template, ctx)
        except Exception as e:
            console.print(f"[red]✗[/red] {email} - template error: {e}")
            continue

        # Gates
        blocked = _check_gates(ledger, email, tag, domain)
        if blocked:
            prefix = f"[{i+1}/{total}] " if total > 1 else ""
            console.print(f"[red]✗[/red] {prefix}{email} - {blocked}")
            continue

        if dry_run:
            prefix = f"[{i+1}/{total}] " if total > 1 else ""
            console.print(f"[dim]○[/dim] {prefix}{email} [dry run]")
            sent += 1
            continue

        # Pre-allocate
        ledger.record_send(email, tag, status="sending")

        # Send
        try:
            msg_id = _send_email(email, rendered_subject, rendered_body, from_inbox, config)
            # Update to sent (re-record overwrites the sending entry conceptually,
            # but we just append - dedup checks handle it)
            ledger.record_send(email, tag, message_id=msg_id, status="sent")
            ledger.record_domain_send(domain)
            prefix = f"[{i+1}/{total}] " if total > 1 else ""
            console.print(f"[green]✓[/green] {prefix}{email}")
            sent += 1
        except Exception as e:
            console.print(f"[red]✗[/red] {email} - {e}")

        # Spacing
        if i < total - 1:
            time.sleep(spacing)

    if total > 1:
        console.print(f"\nDone. Sent: {sent}/{total}")


@cli.command()
def status():
    """Show outreach status."""
    ledger = Ledger(STATE_DIR)
    domains = ledger.domain_info()

    if domains:
        t = Table(title="Domain Health")
        t.add_column("Domain")
        t.add_column("Stage")
        t.add_column("Today")
        t.add_column("Cap")
        t.add_column("Total")
        t.add_column("Status")
        for d in domains:
            status_str = "[green]OK[/green]" if d["ok"] else f"[red]{d['status']}[/red]"
            t.add_row(d["domain"], str(d["stage"]), str(d["today"]), str(d["cap"]), str(d["total"]), status_str)
        console.print(t)

    console.print(f"\nTotal sent: {ledger.total_sends()} | Suppressed: {ledger.suppressed_count()}")


@cli.command()
@click.argument("email")
@click.option("--reason", default="manual")
def suppress(email, reason):
    """Add email to suppression list."""
    ledger = Ledger(STATE_DIR)
    ledger.suppress(email, reason)
    console.print(f"[green]✓[/green] {email.lower().strip()} suppressed ({reason})")


@cli.command()
@click.argument("email")
def unsuppress(email):
    """Remove from suppression list."""
    ledger = Ledger(STATE_DIR)
    if ledger.unsuppress(email):
        console.print(f"[green]✓[/green] {email.lower().strip()} unsuppressed")
    else:
        console.print(f"[dim]{email} was not suppressed[/dim]")


@cli.command()
def suppressed():
    """List suppressed emails."""
    ledger = Ledger(STATE_DIR)
    entries = ledger.suppressed_list()
    if not entries:
        console.print("[dim]No suppressed emails.[/dim]")
        return
    t = Table(title=f"Suppressed ({len(entries)})")
    t.add_column("Email")
    t.add_column("Reason")
    t.add_column("Added")
    for email, e in sorted(entries.items()):
        t.add_row(email, e["reason"], e.get("added_at", "")[:10])
    console.print(t)


@cli.command()
@click.argument("email")
def history(email):
    """Show send history for an email."""
    ledger = Ledger(STATE_DIR)
    entries = ledger.history(email)
    if not entries:
        console.print(f"[dim]No history for {email}[/dim]")
        return
    t = Table(title=f"History: {email.lower().strip()}")
    t.add_column("Date")
    t.add_column("Tag")
    t.add_column("Status")
    for e in entries:
        t.add_row(e["sent_at"][:10], e["tag"], e["status"])
    console.print(t)


@cli.command()
@click.option("--key", required=True)
@click.option("--value", required=True)
def config(key, value):
    """Set a config value."""
    ledger = Ledger(STATE_DIR)
    ledger.set_config(key, value)
    console.print(f"[green]✓[/green] {key} = {value}")
