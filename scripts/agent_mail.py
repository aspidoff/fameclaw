#!/usr/bin/env python3
"""FameClaw Agent Mail — Autonomous email management for creator outreach.

Monitors inbox, routes emails, handles responses, and manages the full
outreach-to-deal pipeline without human intervention.

Usage:
    python3 agent_mail.py watch --config outreach.json [--interval 300]
    python3 agent_mail.py check --config outreach.json
    python3 agent_mail.py status --config outreach.json
"""

import argparse
import csv
import json
import re
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from gmail import GmailClient, DEFAULT_CREDS
from negotiate import (
    classify_reply, extract_price_from_reply, extract_demographics_from_reply,
    generate_discovery_response, generate_counter_offer, generate_instant_close,
    generate_redirect_response, generate_too_expensive_response, generate_followup,
    load_negotiate_config, save_negotiate_config,
)

# --- State management ---

def load_state(config_path):
    state_file = Path(config_path).with_name("outreach_state.json")
    if state_file.exists():
        with open(state_file) as f:
            return json.load(f)
    return {"contacts": {}, "stats": {}, "agent_mail": {}}


def save_state(config_path, state):
    state_file = Path(config_path).with_name("outreach_state.json")
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


def load_config(config_path):
    with open(config_path) as f:
        return json.load(f)


def get_gmail(config):
    creds = config.get("gmail_creds", str(DEFAULT_CREDS))
    return GmailClient(creds)


# --- Email routing ---

def route_email(sender_email, subject, body, state, config):
    """Determine what to do with an incoming email.
    
    Returns: (action, context)
        action: 'negotiate' | 'followup_reply' | 'new_contact' | 'ignore'
        context: dict with relevant info
    """
    sender_lower = sender_email.lower()

    # Ignore junk
    junk_patterns = [
        "noreply", "no-reply", "mailer-daemon", "postmaster",
        "notification", "newsletter", "marketing", "promo",
        "support@google", "support@youtube"
    ]
    if any(j in sender_lower for j in junk_patterns):
        return "ignore", {"reason": "junk/automated"}

    # Known contact — route to negotiate
    contact = state["contacts"].get(sender_email)
    if contact:
        if contact.get("negotiate_outcome") in ("won", "lost", "declined"):
            return "ignore", {"reason": f"closed ({contact.get('negotiate_outcome')})"}
        return "negotiate", {"contact": contact, "email": sender_email}

    # Check if sender matches any contact by domain or similar email
    for stored_email, contact in state["contacts"].items():
        if stored_email.split("@")[1] == sender_email.split("@")[1]:
            # Same domain — might be the same person from a different address
            return "negotiate", {"contact": contact, "email": stored_email, "alt_email": sender_email}

    # Unknown sender — could be a creator reaching out to us
    return "new_contact", {"email": sender_email, "subject": subject}


# --- Actions ---

def handle_negotiate(sender_email, subject, body, contact, state, config, neg_config, client, dry_run=False):
    """Handle a reply from a known contact in negotiation."""
    now = datetime.utcnow()
    name = contact.get("name", sender_email.split("@")[0])

    classification = classify_reply(body, subject)
    print(f"  Classification: {classification}")

    # Update contact state
    contact["last_reply_at"] = now.isoformat()
    contact["negotiate_stage"] = classification
    contact["replied"] = True
    contact["negotiate"] = True

    # Generate response based on classification
    response_subject = None
    response_body = None
    reply_to = contact.get("negotiate_msg_id") or contact.get("message_id")

    if classification == "DECLINED":
        contact["negotiate_outcome"] = "declined"
        contact["closed_at"] = now.isoformat()
        print(f"  → DECLINED. Marked as dead.")
        # Log for brand owner notification
        log_notification(state, f"❌ {name} ({sender_email}) declined the collaboration.")
        return

    elif classification == "PRICED":
        their_price = extract_price_from_reply(body)
        has_demo = extract_demographics_from_reply(body)

        if their_price:
            contact["their_price"] = their_price
            contact["has_rates"] = True
            print(f"  → Quoted ${their_price:,.0f}")

        if has_demo:
            contact["has_demographics"] = True
            print(f"  → Demographics detected")

        if their_price and neg_config.get("budget_max"):
            if their_price > neg_config["budget_max"] * 1.5:
                response_subject, response_body = generate_too_expensive_response(
                    contact, neg_config, their_price
                )
                print(f"  → Price way over budget. Proposing alternatives.")
            elif their_price > neg_config["budget_max"]:
                response_subject, response_body = generate_too_expensive_response(
                    contact, neg_config, their_price
                )
                print(f"  → Price over budget. Counter with structure.")
            else:
                response_subject, response_body = generate_counter_offer(
                    contact, neg_config, their_price
                )
                print(f"  → Price within range. Making offer.")
        elif their_price:
            # Store price, need budget config
            log_notification(state,
                f"⚠️ {name} quoted ${their_price:,.0f} but budget not configured. "
                f"Run: negotiate.py set-config --key budget_max --value <amount>")
            print(f"  ⚠️ Got price but no budget set.")
        else:
            response_subject, response_body = generate_discovery_response(contact, neg_config)
            print(f"  → Price mentioned but couldn't extract. Asking for clarification.")

    elif classification == "REDIRECT":
        response_subject, response_body = generate_redirect_response(contact, neg_config)
        print(f"  → Creator wants different format. Pivoting.")

    elif classification == "INTERESTED":
        has_demo = contact.get("has_demographics", False)
        has_rates = contact.get("has_rates", False)

        # Check if this reply contains rates or demographics
        price = extract_price_from_reply(body)
        if price:
            contact["their_price"] = price
            contact["has_rates"] = True
            has_rates = True

        demo = extract_demographics_from_reply(body)
        if demo:
            contact["has_demographics"] = True
            has_demo = True

        if not has_demo or not has_rates:
            response_subject, response_body = generate_discovery_response(contact, neg_config)
            print(f"  → Interested. Sending discovery questions.")
        elif price and neg_config.get("budget_max"):
            if price <= neg_config["budget_max"]:
                response_subject, response_body = generate_counter_offer(contact, neg_config, price)
            else:
                response_subject, response_body = generate_too_expensive_response(contact, neg_config, price)
            print(f"  → Have rates + demographics. Making offer.")
        elif neg_config.get("budget_max"):
            response_subject, response_body = generate_counter_offer(contact, neg_config)
            print(f"  → Making initial offer.")
        else:
            log_notification(state,
                f"⚠️ {name} is interested but budget not set. Configure negotiate_config.json.")

    # Send response
    if response_subject and response_body:
        if dry_run:
            print(f"  [DRY RUN] Would send: {response_subject}")
            print(f"  Body preview: {response_body[:150]}...")
        else:
            try:
                msg_id = client.send(sender_email, response_subject, response_body,
                                     reply_to_msg_id=reply_to)
                contact["negotiate_last_sent"] = now.isoformat()
                contact["negotiate_msg_id"] = msg_id
                contact["negotiate_followups"] = 0
                print(f"  ✅ Response sent (threaded)")
            except Exception as e:
                print(f"  ❌ Send error: {e}")


def handle_followups(state, config, neg_config, client, dry_run=False):
    """Send follow-ups to stale negotiations."""
    now = datetime.utcnow()
    sent = 0

    for email, contact in state["contacts"].items():
        if contact.get("negotiate_outcome") in ("won", "lost", "declined", "stale"):
            continue
        if not contact.get("negotiate"):
            continue

        last_sent = contact.get("negotiate_last_sent")
        if not last_sent:
            continue

        days = (now - datetime.fromisoformat(last_sent)).days
        followups = contact.get("negotiate_followups", 0)

        if followups >= 3:
            if not contact.get("negotiate_outcome"):
                contact["negotiate_outcome"] = "stale"
                contact["closed_at"] = now.isoformat()
                name = contact.get("name", email)
                log_notification(state, f"⏸ {name} ({email}) went stale after 3 follow-ups. Will re-engage in 3 months.")
            continue

        # Follow-up schedule: day 3, day 7, day 14
        thresholds = [3, 7, 14]
        if followups < len(thresholds) and days >= thresholds[followups]:
            name = contact.get("name", email)
            subject, body = generate_followup(contact, neg_config, days)
            reply_to = contact.get("negotiate_msg_id") or contact.get("message_id")

            if dry_run:
                print(f"  [DRY RUN] Follow-up #{followups+1} to {name} ({email})")
            else:
                try:
                    msg_id = client.send(email, subject, body, reply_to_msg_id=reply_to)
                    contact["negotiate_last_sent"] = now.isoformat()
                    contact["negotiate_msg_id"] = msg_id
                    contact["negotiate_followups"] = followups + 1
                    print(f"  📤 Follow-up #{followups+1} to {name} ({email})")
                    sent += 1
                except Exception as e:
                    print(f"  ❌ Follow-up error for {email}: {e}")

    return sent


def handle_outreach_followups(state, config, client, dry_run=False):
    """Send outreach follow-ups (day 3, day 8) for contacts that haven't replied."""
    now = datetime.utcnow()
    sent = 0

    for email, contact in state["contacts"].items():
        if contact.get("replied") or contact.get("negotiate"):
            continue
        if contact.get("negotiate_outcome"):
            continue

        stage = contact.get("stage", "first")
        sent_at = contact.get("sent_at")
        if not sent_at:
            continue

        days = (now - datetime.fromisoformat(sent_at)).days

        # Outreach follow-up schedule
        if stage == "first" and days >= 3:
            next_stage = "followup_1"
        elif stage == "followup_1" and days >= 5:
            next_stage = "followup_2"
        else:
            continue

        name = contact.get("name", email)
        sender_name = config.get("sender_name", "")
        brand = config.get("brand", "")

        # Generate outreach follow-up
        videos = contact.get("videos", [])
        video_mention = ""
        if len(videos) > 1 and next_stage == "followup_1":
            video_mention = f' Your video "{videos[1][:50]}" caught our eye too.'
        elif videos:
            video_mention = f' Loved your video "{videos[0][:50]}".'

        if next_stage == "followup_1":
            body = f"Hey {name.split()[0] if name else 'there'},\n\nJust circling back on my previous email about a potential collaboration with {brand}.{video_mention}\n\nWould love to chat if you're open to it.\n\n{sender_name}"
            subject = f"Re: Collaboration with {brand}"
        else:
            body = f"Hey {name.split()[0] if name else 'there'},\n\nLast follow-up — totally understand if the timing isn't right. If you're ever open to brand collaborations down the road, we'd love to connect.\n\nKeep making great content!\n\n{sender_name}"
            subject = f"Re: Collaboration with {brand}"

        reply_to = contact.get("message_id")

        if dry_run:
            print(f"  [DRY RUN] Outreach {next_stage} to {name} ({email})")
        else:
            try:
                msg_id = client.send(email, subject, body, reply_to_msg_id=reply_to)
                contact["stage"] = next_stage
                contact["sent_at"] = now.isoformat()
                contact["message_id"] = msg_id
                print(f"  📤 Outreach {next_stage} to {name} ({email})")
                sent += 1
            except Exception as e:
                print(f"  ❌ Error: {e}")

    return sent


# --- Notifications ---

def log_notification(state, message):
    """Store a notification for the brand owner."""
    if "notifications" not in state.get("agent_mail", {}):
        state.setdefault("agent_mail", {})["notifications"] = []
    state["agent_mail"]["notifications"].append({
        "time": datetime.utcnow().isoformat(),
        "message": message
    })


def get_pending_notifications(state):
    """Get and clear pending notifications."""
    notifs = state.get("agent_mail", {}).get("notifications", [])
    if notifs:
        state["agent_mail"]["notifications"] = []
    return notifs


# --- Main check cycle ---

def run_check(config_path, dry_run=False, verbose=True):
    """Run one full check cycle: inbox scan + followups."""
    config = load_config(config_path)
    state = load_state(config_path)
    neg_config = load_negotiate_config(config_path)
    client = get_gmail(config)
    now = datetime.utcnow()

    # Track last check time
    last_check = state.get("agent_mail", {}).get("last_check")
    state.setdefault("agent_mail", {})["last_check"] = now.isoformat()
    state["agent_mail"]["checks"] = state.get("agent_mail", {}).get("checks", 0) + 1

    since_date = None
    if last_check:
        since_date = datetime.fromisoformat(last_check) - timedelta(hours=1)
    else:
        # First run — check last 30 days
        since_date = now - timedelta(days=30)

    # 1. Check for new replies from all contacts
    active_emails = [e for e, c in state["contacts"].items()
                     if not c.get("negotiate_outcome") in ("won", "lost", "declined")]

    new_replies = 0
    if active_emails:
        if verbose:
            print(f"📬 Checking {len(active_emails)} active contacts for replies...")

        try:
            replies = client.check_replies(active_emails, since_date=since_date)

            for sender_email, msgs in replies.items():
                contact = state["contacts"].get(sender_email)
                if not contact:
                    continue

                # Skip already-processed replies
                last_reply_id = contact.get("last_reply_id")
                for msg in msgs:
                    if last_reply_id and msg.get("message_id") == last_reply_id:
                        continue

                    new_replies += 1
                    snippet = msg.get("snippet", "")
                    subject = msg.get("subject", "")

                    if verbose:
                        print(f"\n{'='*50}")
                        print(f"📩 Reply from {contact.get('name', sender_email)} ({sender_email})")
                        print(f"   Subject: {subject}")
                        print(f"   Preview: {snippet[:100]}...")

                    contact["last_reply_id"] = msg.get("message_id")

                    action, ctx = route_email(sender_email, subject, snippet, state, config)

                    if action == "negotiate":
                        handle_negotiate(sender_email, subject, snippet,
                                        contact, state, config, neg_config, client, dry_run)
                    elif action == "ignore":
                        if verbose:
                            print(f"  → Ignored: {ctx.get('reason')}")

        except Exception as e:
            print(f"  ⚠️ Inbox check error: {e}")

    # 2. Send negotiate follow-ups
    if verbose:
        print(f"\n📤 Checking for negotiate follow-ups...")
    neg_followups = handle_followups(state, config, neg_config, client, dry_run)

    # 3. Send outreach follow-ups
    if verbose:
        print(f"📤 Checking for outreach follow-ups...")
    out_followups = handle_outreach_followups(state, config, client, dry_run)

    # 4. Show notifications
    notifs = get_pending_notifications(state)
    if notifs:
        print(f"\n🔔 Notifications for brand owner:")
        for n in notifs:
            print(f"  {n['message']}")

    # Save state
    save_state(config_path, state)

    # Summary
    if verbose:
        print(f"\n{'='*50}")
        print(f"Agent Mail Check Complete — {now.strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"  New replies: {new_replies}")
        print(f"  Negotiate follow-ups sent: {neg_followups}")
        print(f"  Outreach follow-ups sent: {out_followups}")
        print(f"  Active contacts: {len(active_emails)}")

    return {
        "new_replies": new_replies,
        "neg_followups": neg_followups,
        "out_followups": out_followups,
        "notifications": notifs,
    }


def cmd_watch(args):
    """Persistent watch loop."""
    interval = args.interval
    print(f"🤖 FameClaw Agent Mail — watching every {interval}s")
    print(f"   Config: {args.config}")
    print(f"   Dry run: {args.dry_run}")
    print()

    running = True
    def stop(sig, frame):
        nonlocal running
        print("\n🛑 Stopping Agent Mail...")
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while running:
        try:
            run_check(args.config, dry_run=args.dry_run)
        except Exception as e:
            print(f"\n❌ Check cycle error: {e}")

        # Wait for next cycle
        if running:
            print(f"\n⏳ Next check in {interval}s...")
            for _ in range(interval):
                if not running:
                    break
                time.sleep(1)


def cmd_check(args):
    """Single check cycle."""
    run_check(args.config, dry_run=args.dry_run)


def cmd_status(args):
    """Show agent mail status."""
    state = load_state(args.config)
    config = load_config(args.config)
    neg_config = load_negotiate_config(args.config)
    am = state.get("agent_mail", {})

    print("🤖 FameClaw Agent Mail Status")
    print(f"   Last check: {am.get('last_check', 'never')}")
    print(f"   Total checks: {am.get('checks', 0)}")

    # Contact stats
    total = len(state.get("contacts", {}))
    replied = sum(1 for c in state.get("contacts", {}).values() if c.get("replied"))
    negotiating = sum(1 for c in state.get("contacts", {}).values()
                      if c.get("negotiate") and not c.get("negotiate_outcome"))
    won = sum(1 for c in state.get("contacts", {}).values()
              if c.get("negotiate_outcome") == "won")
    lost = sum(1 for c in state.get("contacts", {}).values()
               if c.get("negotiate_outcome") in ("lost", "declined"))
    stale = sum(1 for c in state.get("contacts", {}).values()
                if c.get("negotiate_outcome") == "stale")
    pending_outreach = sum(1 for c in state.get("contacts", {}).values()
                          if not c.get("replied") and not c.get("negotiate_outcome"))

    print(f"\n📊 Pipeline:")
    print(f"   Total contacts:     {total}")
    print(f"   Pending outreach:   {pending_outreach}")
    print(f"   Replied:            {replied}")
    print(f"   Active negotiation: {negotiating}")
    print(f"   Deals won:          {won}")
    print(f"   Declined:           {lost}")
    print(f"   Stale:              {stale}")

    # Config check
    print(f"\n⚙️ Config:")
    print(f"   Brand: {config.get('brand', 'NOT SET')}")
    print(f"   Budget: ${neg_config.get('budget_min', '?')} - ${neg_config.get('budget_max', '?')}")
    print(f"   Style: {neg_config.get('negotiation_style', 'NOT SET')}")
    print(f"   Payment: {neg_config.get('payment_terms', '50/50')}")

    missing = []
    if not neg_config.get("budget_max"):
        missing.append("budget_max")
    if not neg_config.get("budget_min"):
        missing.append("budget_min")
    if not neg_config.get("negotiation_style"):
        missing.append("negotiation_style")
    if missing:
        print(f"\n   ⚠️ Missing: {', '.join(missing)}")
        print(f"   Set via: negotiate.py set-config --key <key> --value <value>")

    # Pending notifications
    notifs = state.get("agent_mail", {}).get("notifications", [])
    if notifs:
        print(f"\n🔔 Pending notifications ({len(notifs)}):")
        for n in notifs[-5:]:
            print(f"   [{n['time'][:16]}] {n['message']}")


# --- CLI ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FameClaw Agent Mail")
    sub = parser.add_subparsers(dest="command")

    p_watch = sub.add_parser("watch", help="Persistent watch loop")
    p_watch.add_argument("--config", default="outreach.json")
    p_watch.add_argument("--interval", type=int, default=300, help="Check interval in seconds (default 300)")
    p_watch.add_argument("--dry-run", action="store_true")

    p_check = sub.add_parser("check", help="Single check cycle")
    p_check.add_argument("--config", default="outreach.json")
    p_check.add_argument("--dry-run", action="store_true")

    p_status = sub.add_parser("status", help="Show agent mail status")
    p_status.add_argument("--config", default="outreach.json")

    args = parser.parse_args()

    if args.command == "watch":
        cmd_watch(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()
