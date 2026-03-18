#!/usr/bin/env python3
"""FameClaw Outreach Pipeline — Personalized multi-stage email outreach.

Stages: OUTREACH → FOLLOW_UP_1 → FOLLOW_UP_2 → (replied) → NEGOTIATE
- Fetches recent videos per creator for personalization
- Short, punchy first email mentioning a specific video
- Auto follow-ups with increasing urgency
- Tracks replies via gws CLI
- Moves replied creators to negotiate stage

Usage:
    python3 outreach.py send --csv scored.csv --config outreach.json [--dry-run]
    python3 outreach.py followup --config outreach.json [--dry-run]
    python3 outreach.py check-replies --config outreach.json
    python3 outreach.py status --config outreach.json
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

# Import Gmail client
sys.path.insert(0, str(SCRIPT_DIR))
from gmail import GmailClient


def run_cmd(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=isinstance(cmd, str))
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1


def get_videos(handle, count=5):
    """Fetch recent video titles for a channel."""
    out, code = run_cmd(
        f'bash "{SCRIPT_DIR}/get_videos.sh" "https://youtube.com/@{handle}" {count}',
        timeout=15
    )
    if code == 0 and out:
        return [t for t in out.split("\n") if t.strip()]
    return []


_gmail_client = None

def get_gmail(config):
    global _gmail_client
    if _gmail_client is None:
        creds = config.get("gmail_creds", "gmail_creds.json")
        _gmail_client = GmailClient(creds)
    return _gmail_client


def send_email(to, subject, body, config, html=False, dry_run=False, reply_to_msg_id=None):
    """Send via SMTP."""
    if dry_run:
        print(f"  [DRY RUN] To: {to}")
        print(f"  Subject: {subject}")
        print(f"  Body preview: {body[:200]}...")
        return True, "dry-run"

    try:
        client = get_gmail(config)
        msg_id = client.send(to, subject, body, html=html, reply_to_msg_id=reply_to_msg_id)
        return True, msg_id
    except Exception as e:
        print(f"  ❌ Send error: {e}")
        return False, str(e)


def generate_first_email(creator, config):
    """Generate personalized first outreach email."""
    brand = config.get("brand", "")
    website = config.get("website", "")
    partnerships = config.get("current_partnerships", [])
    sender_name = config.get("sender_name", "")

    # Pick a video to mention
    video_mention = ""
    if creator.get("videos"):
        vid = creator["videos"][0]
        video_mention = f'Saw your video "{vid}" — really solid content.'

    # Partnership social proof
    partnership_line = ""
    if partnerships:
        names = partnerships[:3]
        if len(names) == 1:
            partnership_line = f"We're currently working with {names[0]} on something similar."
        elif len(names) == 2:
            partnership_line = f"We're currently partnering with {names[0]} and {names[1]} on similar collabs."
        else:
            partnership_line = f"We're working with {', '.join(names[:-1])}, and {names[-1]} on similar campaigns right now."

    body = f"""Hey {creator['name'].split(' ')[0]},

{video_mention}

I'm with {brand} ({website}) and think there's a natural fit for a collab with your channel.

{partnership_line}

Would you be open to a quick chat about it?

{sender_name}""".strip()

    # Clean up double blank lines
    body = re.sub(r'\n{3,}', '\n\n', body)

    subject = config.get("subject_first", f"Quick collab idea, {creator['name'].split(' ')[0]}?")
    subject = subject.replace("{{name}}", creator['name'].split(' ')[0])
    subject = subject.replace("{{channel_name}}", creator['name'])

    return subject, body


def generate_followup_1(creator, config):
    """First follow-up — 3 days after initial."""
    brand = config.get("brand", "")
    sender_name = config.get("sender_name", "")
    name = creator['name'].split(' ')[0]

    # Reference a different video if available
    video_ref = ""
    if len(creator.get("videos", [])) > 1:
        video_ref = f'\n\nBTW, just watched "{creator["videos"][1]}" — great stuff.'

    body = f"""Hey {name},

Just bumping this up — wanted to see if a collab with {brand} would interest you.{video_ref}

Happy to keep it simple. Let me know either way.

{sender_name}""".strip()

    subject = config.get("subject_followup_1", f"Re: Quick collab idea, {name}?")
    subject = subject.replace("{{name}}", name)

    return subject, body


def generate_followup_2(creator, config):
    """Second follow-up — 5 days after first follow-up. Last touch."""
    brand = config.get("brand", "")
    sender_name = config.get("sender_name", "")
    name = creator['name'].split(' ')[0]

    body = f"""Hey {name},

Last one from me — didn't want to miss you on this.

If the timing's off, totally get it. But if you're open to working with {brand}, I'd love to connect. Just reply and we'll set something up.

{sender_name}""".strip()

    subject = config.get("subject_followup_2", f"Re: Quick collab idea, {name}?")
    subject = subject.replace("{{name}}", name)

    return subject, body


STAGE_GENERATORS = {
    "first": generate_first_email,
    "followup_1": generate_followup_1,
    "followup_2": generate_followup_2,
}

STAGE_DELAYS = {
    "first": 0,        # send immediately
    "followup_1": 3,   # 3 days after first
    "followup_2": 5,   # 5 days after followup_1
}


def load_campaign_state(config_path):
    """Load or create campaign state."""
    state_path = config_path.replace(".json", "_state.json")
    if os.path.exists(state_path):
        with open(state_path) as f:
            return json.load(f)
    return {"contacts": {}, "created": datetime.utcnow().isoformat()}


def save_campaign_state(config_path, state):
    """Save campaign state."""
    state_path = config_path.replace(".json", "_state.json")
    state["updated"] = datetime.utcnow().isoformat()
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def load_contacts_from_csv(csv_path, min_score=0):
    """Read and filter contacts from scored CSV."""
    contacts = []
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        cols = {h.lower().strip(): i for i, h in enumerate(header)}

        for row in reader:
            email_raw = row[cols.get("email", 9)] if len(row) > cols.get("email", 9) else ""
            emails = [e.strip() for e in email_raw.replace(";", ",").split(",")
                      if "@" in e and "." in e.split("@")[-1]]
            emails = [e for e in emails if not any(
                j in e.lower() for j in ["png", "jpg", "gif", "svg", "noreply", "no-reply", "example", "test@"]
            )]
            if not emails:
                continue

            score = 0
            score_i = cols.get("match_score")
            if score_i is not None and len(row) > score_i:
                try:
                    score = int(row[score_i])
                except (ValueError, IndexError):
                    pass

            if score < min_score:
                continue

            contacts.append({
                "email": emails[0],
                "name": row[cols.get("channel_name", 0)],
                "handle": row[cols.get("handle", 1)].lstrip("@"),
                "subscribers": row[cols.get("subscribers", 2)],
                "avg_views": row[cols.get("avg_views", 4)] if len(row) > cols.get("avg_views", 4) else "",
                "score": score,
            })
    return contacts


def cmd_send(args):
    """Initial outreach to new contacts."""
    with open(args.config) as f:
        config = json.load(f)

    state = load_campaign_state(args.config)
    rate = config.get("rate", 30)
    delay = 3600 / rate
    min_score = config.get("min_score", 0)
    max_send = config.get("max_per_run", 50)

    contacts = load_contacts_from_csv(args.csv, min_score)

    sent = 0
    skipped = 0

    print(f"=== FameClaw Outreach — {len(contacts)} eligible contacts ===")
    print(f"Rate: {rate}/hr | Min score: {min_score} | Dry run: {args.dry_run}")
    print()

    for c in contacts:
        if sent >= max_send:
            print(f"\nMax per run ({max_send}) reached. Run again for more.")
            break

        addr = c["email"]

        # Skip already contacted
        if addr in state["contacts"]:
            skipped += 1
            continue

        # Fetch recent videos for personalization
        print(f"[{sent+1}] @{c['handle']} ({c['name']}) — fetching videos...")
        c["videos"] = get_videos(c["handle"], 3)
        if c["videos"]:
            print(f"  Videos: {c['videos'][0][:60]}...")

        # Generate email
        subject, body = generate_first_email(c, config)

        # Send
        success, msg_id = send_email(addr, subject, body, config, dry_run=args.dry_run)

        if success:
            state["contacts"][addr] = {
                "name": c["name"],
                "handle": c["handle"],
                "stage": "first",
                "sent_at": datetime.utcnow().isoformat(),
                "message_id": msg_id,
                "videos": c.get("videos", [])[:3],
                "score": c["score"],
                "replied": False,
                "negotiate": False,
            }
            sent += 1
            print(f"  ✅ Sent to {addr}")
        else:
            print(f"  ❌ Failed: {addr}")

        if not args.dry_run and sent < max_send:
            time.sleep(delay)

    save_campaign_state(args.config, state)
    print(f"\n=== Done: {sent} sent, {skipped} skipped (already contacted) ===")


def cmd_followup(args):
    """Send follow-ups to non-responders."""
    with open(args.config) as f:
        config = json.load(f)

    state = load_campaign_state(args.config)
    rate = config.get("rate", 30)
    delay = 3600 / rate
    now = datetime.utcnow()

    # First check for replies via IMAP
    print("Checking for replies first...")
    unreplied = {e: c for e, c in state["contacts"].items() if not c.get("replied")}

    if unreplied:
        try:
            client = get_gmail(config)
            # Find earliest sent date for search window
            earliest = min(
                datetime.fromisoformat(c["sent_at"]) for c in unreplied.values()
            )
            replies = client.check_replies(list(unreplied.keys()), since_date=earliest)
            for addr in replies:
                state["contacts"][addr]["replied"] = True
                state["contacts"][addr]["negotiate"] = True
                state["contacts"][addr]["replied_at"] = now.isoformat()
                print(f"  📬 Reply from {addr} ({state['contacts'][addr]['name']}) → NEGOTIATE")
        except Exception as e:
            if not args.dry_run:
                print(f"  ⚠️ Reply check failed: {e}")

    # Find contacts needing follow-up
    followups = []
    for addr, contact in state["contacts"].items():
        if contact.get("replied") or contact.get("negotiate"):
            continue

        stage = contact["stage"]
        sent_at = datetime.fromisoformat(contact["sent_at"])
        days_since = (now - sent_at).days

        if stage == "first" and days_since >= STAGE_DELAYS["followup_1"]:
            followups.append((addr, contact, "followup_1"))
        elif stage == "followup_1" and days_since >= STAGE_DELAYS["followup_2"]:
            followups.append((addr, contact, "followup_2"))

    print(f"\n=== Follow-ups needed: {len(followups)} ===")

    sent = 0
    for addr, contact, next_stage in followups:
        gen = STAGE_GENERATORS[next_stage]
        creator = {
            "name": contact["name"],
            "handle": contact["handle"],
            "videos": contact.get("videos", []),
        }
        subject, body = gen(creator, config)

        # Thread follow-ups to original message
        reply_to = contact.get("message_id")

        print(f"\n[{sent+1}] {next_stage} → {addr} ({contact['name']})")
        success, msg_id = send_email(
            addr, subject, body, config,
            dry_run=args.dry_run, reply_to_msg_id=reply_to
        )

        if success:
            contact["stage"] = next_stage
            contact["sent_at"] = now.isoformat()
            contact["message_id"] = msg_id
            sent += 1
            print(f"  ✅ Follow-up sent (threaded)")
        else:
            print(f"  ❌ Failed")

        if not args.dry_run:
            time.sleep(delay)

    save_campaign_state(args.config, state)
    print(f"\n=== Done: {sent} follow-ups sent ===")


def cmd_check_replies(args):
    """Check for replies and move to negotiate stage."""
    with open(args.config) as f:
        config = json.load(f)

    state = load_campaign_state(args.config)
    now = datetime.utcnow()

    unreplied = {e: c for e, c in state["contacts"].items() if not c.get("replied")}
    print(f"Checking {len(unreplied)} contacts for replies...")

    if not unreplied:
        print("  No pending contacts.")
        return

    try:
        client = get_gmail(config)
        earliest = min(
            datetime.fromisoformat(c["sent_at"]) for c in unreplied.values()
        )
        replies = client.check_replies(list(unreplied.keys()), since_date=earliest)

        for addr, msgs in replies.items():
            state["contacts"][addr]["replied"] = True
            state["contacts"][addr]["negotiate"] = True
            state["contacts"][addr]["replied_at"] = now.isoformat()
            name = state["contacts"][addr]["name"]
            snippet = msgs[0].get("snippet", "")[:80] if msgs else ""
            print(f"  📬 {name} ({addr}) → NEGOTIATE")
            if snippet:
                print(f"     \"{snippet}...\"")

        if not replies:
            print("  No new replies.")

    except Exception as e:
        print(f"  ❌ Error checking replies: {e}")

    save_campaign_state(args.config, state)


def cmd_status(args):
    """Show campaign status."""
    state = load_campaign_state(args.config)
    contacts = state.get("contacts", {})

    total = len(contacts)
    stages = {"first": 0, "followup_1": 0, "followup_2": 0}
    replied = 0
    negotiate = 0

    for c in contacts.values():
        if c.get("replied"):
            replied += 1
        if c.get("negotiate"):
            negotiate += 1
        stage = c.get("stage", "first")
        if stage in stages:
            stages[stage] += 1

    print(f"=== Campaign Status ===")
    print(f"  Total contacted: {total}")
    print(f"  Stage breakdown:")
    print(f"    First email sent: {stages['first']}")
    print(f"    Follow-up 1 sent: {stages['followup_1']}")
    print(f"    Follow-up 2 sent: {stages['followup_2']}")
    print(f"  📬 Replied: {replied}")
    print(f"  🤝 Negotiate: {negotiate}")

    if negotiate > 0:
        print(f"\n  Ready to negotiate:")
        for email, c in contacts.items():
            if c.get("negotiate"):
                print(f"    • {c['name']} (@{c['handle']}) — {email}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FameClaw Outreach Pipeline")
    sub = parser.add_subparsers(dest="command")

    p_send = sub.add_parser("send", help="Send initial outreach emails")
    p_send.add_argument("--csv", required=True)
    p_send.add_argument("--config", required=True)
    p_send.add_argument("--dry-run", action="store_true")

    p_follow = sub.add_parser("followup", help="Send follow-ups to non-responders")
    p_follow.add_argument("--config", required=True)
    p_follow.add_argument("--dry-run", action="store_true")

    p_check = sub.add_parser("check-replies", help="Check inbox for replies")
    p_check.add_argument("--config", required=True)

    p_status = sub.add_parser("status", help="Show campaign status")
    p_status.add_argument("--config", required=True)

    args = parser.parse_args()

    if args.command == "send":
        cmd_send(args)
    elif args.command == "followup":
        cmd_followup(args)
    elif args.command == "check-replies":
        cmd_check_replies(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()
