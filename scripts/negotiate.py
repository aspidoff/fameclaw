#!/usr/bin/env python3
"""FameClaw Negotiate Engine — Autonomous creator negotiation.

Reads replies, classifies them, generates responses, sends them.
Only asks brand owner when missing critical config (budget, etc).
Notifies on deal closed or dead.

Usage:
    python3 negotiate.py check --config outreach.json
    python3 negotiate.py reply --to creator@email.com --body "..." --config outreach.json
    python3 negotiate.py status --config outreach.json
    python3 negotiate.py close --email creator@email.com --outcome won|lost|stale --config outreach.json
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from gmail import GmailClient

DEFAULT_CREDS = Path.home() / ".config" / "fameclaw" / "gmail.json"

# --- Negotiate config ---
DEFAULT_NEGOTIATE_CONFIG = {
    "budget_min": None,         # Ideal price per creator (ask if missing)
    "budget_max": None,         # Hard cap per creator (ask if missing)
    "negotiation_style": None,  # friendly / value-focused / budget-strict (ask if missing)
    "payment_terms": "50/50",   # 50% upfront, 50% after delivery
    "preferred_formats": ["video_integration", "mid_roll", "dedicated_video", "newsletter", "shorts"],
    "deal_breakers": [],        # e.g. ["competing_products", "wrong_geography"]
    "brand": "",
    "website": "",
    "sender_name": "",
    "current_partnerships": [],
}


def load_outreach_state(config_path):
    state_file = Path(config_path).with_name("outreach_state.json")
    if state_file.exists():
        with open(state_file) as f:
            return json.load(f)
    return {"contacts": {}, "stats": {}}


def save_outreach_state(config_path, state):
    state_file = Path(config_path).with_name("outreach_state.json")
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


def load_negotiate_config(config_path):
    neg_file = Path(config_path).with_name("negotiate_config.json")
    if neg_file.exists():
        with open(neg_file) as f:
            cfg = json.load(f)
        merged = {**DEFAULT_NEGOTIATE_CONFIG, **cfg}
        return merged

    # Fall back to outreach config for brand info
    with open(config_path) as f:
        outreach = json.load(f)

    cfg = dict(DEFAULT_NEGOTIATE_CONFIG)
    cfg["brand"] = outreach.get("brand", "")
    cfg["website"] = outreach.get("website", "")
    cfg["sender_name"] = outreach.get("sender_name", "")
    cfg["current_partnerships"] = outreach.get("current_partnerships", [])
    return cfg


def save_negotiate_config(config_path, cfg):
    neg_file = Path(config_path).with_name("negotiate_config.json")
    with open(neg_file, "w") as f:
        json.dump(cfg, f, indent=2)


def get_gmail_client(config_path):
    with open(config_path) as f:
        outreach = json.load(f)
    creds = outreach.get("gmail_creds", str(DEFAULT_CREDS))
    return GmailClient(creds)


# --- Reply classification ---

def classify_reply(body, subject=""):
    """Classify a creator's reply into a category."""
    text = (subject + " " + body).lower()

    # Hard no
    no_patterns = [
        r"not interested",
        r"no thanks",
        r"no thank you",
        r"i('m| am) not .*(available|interested|open)",
        r"kindly decline",
        r"have to (decline|pass)",
        r"not .* right now",
        r"remove me",
        r"unsubscribe",
        r"stop (emailing|contacting)",
    ]
    for p in no_patterns:
        if re.search(p, text):
            return "DECLINED"

    # Price / rate mentioned
    price_patterns = [
        r"\$\d+",
        r"\d+\s*(usd|dollars|per video|per post|per integration)",
        r"my rate",
        r"my price",
        r"i charge",
        r"our rate",
        r"starting at",
        r"minimum.*\d+",
        r"budget",
    ]
    for p in price_patterns:
        if re.search(p, text):
            return "PRICED"

    # Redirect to different format
    redirect_patterns = [
        r"i (only|don'?t) do .*(youtube|video|integration)",
        r"newsletter instead",
        r"i (do|offer) .*(newsletter|shorts|tiktok|instagram|podcast)",
        r"different (platform|format|channel)",
        r"instead of .*(video|youtube)",
    ]
    for p in redirect_patterns:
        if re.search(p, text):
            return "REDIRECT"

    # Asking questions (interested but wants more info)
    question_patterns = [
        r"what .*(looking for|do you need|kind of|type of)",
        r"can you (tell|share|send|provide)",
        r"more (info|information|details)",
        r"how (does|would|do)",
        r"\?",
    ]
    for p in question_patterns:
        if re.search(p, text):
            return "INTERESTED"

    # Positive signals
    positive_patterns = [
        r"(sounds|looks) (good|great|interesting)",
        r"i('m| am) (interested|open|available|down)",
        r"let('s| us) (do|discuss|talk|chat)",
        r"sure",
        r"yeah",
        r"i('d| would) (love|like) to",
        r"send me",
    ]
    for p in positive_patterns:
        if re.search(p, text):
            return "INTERESTED"

    # Default — treat as interested if they replied at all
    return "INTERESTED"


def extract_price_from_reply(body):
    """Try to extract a dollar amount from reply."""
    matches = re.findall(r'\$\s?([\d,]+(?:\.\d{2})?)', body)
    if matches:
        prices = []
        for m in matches:
            try:
                prices.append(float(m.replace(",", "")))
            except ValueError:
                pass
        if prices:
            return max(prices)  # Take the highest mentioned price

    # "X dollars" or "X usd"
    matches = re.findall(r'(\d[\d,]*)\s*(dollars|usd|per video|per post)', body.lower())
    if matches:
        try:
            return float(matches[0][0].replace(",", ""))
        except ValueError:
            pass

    return None


def extract_demographics_from_reply(body):
    """Check if creator shared demographic info."""
    demo_signals = ["male", "female", "age", "country", "countries", "demographic",
                    "united states", "usa", "uk", "canada", "australia", "18-", "25-", "35-"]
    text = body.lower()
    found = [s for s in demo_signals if s in text]
    return len(found) >= 2  # At least 2 demographic signals


# --- Response generation ---

def generate_discovery_response(contact, neg_config):
    """First response after creator shows interest — ask for demographics + rates."""
    name = contact.get("name", "").split()[0]  # First name
    sender = neg_config.get("sender_name", "")
    brand = neg_config.get("brand", "")

    body = f"""Hey {name},

Great to hear from you! Really appreciate the response.

Before we put something together, a few quick questions:

1. Could you share your audience demographics? Specifically top countries and age/gender split.
2. What are your rates for a video integration? Do you offer discounts for multiple videos?
3. Have any examples of past brand collabs you've done?

Happy to work with whatever format suits you best — if you already have a video in production where {brand} would be a natural fit, even better.

{sender}"""
    return f"Re: Collaboration with {brand}", body


def generate_counter_offer(contact, neg_config, their_price=None):
    """Generate counter-offer based on budget and style."""
    name = contact.get("name", "").split()[0]
    sender = neg_config.get("sender_name", "")
    brand = neg_config.get("brand", "")
    website = neg_config.get("website", "")
    style = neg_config.get("negotiation_style", "value-focused")
    budget_max = neg_config.get("budget_max")
    budget_min = neg_config.get("budget_min")
    payment = neg_config.get("payment_terms", "50/50")
    affiliate_url = neg_config.get("affiliate_url", "")

    # Determine offer price
    if their_price and budget_max:
        if style == "friendly":
            # If within budget, close immediately — don't counter
            if their_price <= budget_max:
                return generate_instant_close(contact, neg_config, their_price)
            offer = budget_max
        elif style == "budget-strict":
            offer = budget_min or (budget_max * 0.5)
        else:  # value-focused
            # If price is well within budget (<70%), close fast
            if their_price <= (budget_max * 0.7):
                return generate_instant_close(contact, neg_config, their_price)
            offer = min(their_price * 0.65, budget_max)
            if budget_min and offer < budget_min:
                offer = budget_min
    elif budget_min:
        offer = budget_min
    elif budget_max:
        offer = budget_max * 0.6
    else:
        return None, None

    offer = int(round(offer, -1))

    # Payment terms
    if payment == "50/50":
        payment_text = "50% upfront, 50% after delivery (before publishing)"
    elif payment == "full_upfront":
        payment_text = "full payment upfront"
    elif payment == "net30":
        payment_text = "net-30 after delivery"
    else:
        payment_text = payment

    # Affiliate sweetener
    affiliate_text = ""
    if affiliate_url:
        affiliate_text = f"\n\nWe also have an affiliate program ({affiliate_url}) — you'd earn ongoing revenue from any sales driven by your content, on top of the flat fee."

    body = f"""Hey {name},

Thanks for the details — your audience looks like a strong fit for {brand}.

Here's what we're thinking: a video integration for ${offer:,}, plus a performance bonus of ${int(offer * 0.5):,} if the video hits 10K views in 30 days.

This would be the start of an ongoing partnership — if it performs well, we'd want to do several more this quarter.

Payment: {payment_text}. PayPal, Stripe, or wire — whatever works for you.{affiliate_text}

We'd love to review the script before recording to make sure everything's accurate. What do you think?

{sender}"""

    subject = f"Re: Collaboration with {brand}"
    return subject, body


def generate_instant_close(contact, neg_config, their_price):
    """When price is within budget — close immediately, don't counter."""
    name = contact.get("name", "").split()[0]
    sender = neg_config.get("sender_name", "")
    brand = neg_config.get("brand", "")
    payment = neg_config.get("payment_terms", "50/50")
    affiliate_url = neg_config.get("affiliate_url", "")

    if payment == "50/50":
        payment_text = "50% upfront, 50% after delivery (before publishing)"
    else:
        payment_text = payment

    affiliate_text = ""
    if affiliate_url:
        affiliate_text = f"\n\nWe also have an affiliate program ({affiliate_url}) — ongoing revenue from any sales your content drives, on top of the flat fee."

    body = f"""Hey {name},

We have a deal. ${int(their_price):,} works for us.

Please send us a PayPal or Stripe invoice, and we'll get that sent right away. Payment terms: {payment_text}.

A couple things before we kick off:
1. Could you send your channel demographics (top countries, age/gender)? Helps us track ROI.
2. We'd love to review the script/talking points before you record — just to make sure everything's accurate.{affiliate_text}

Looking forward to this!

{sender}"""

    subject = f"Re: Collaboration with {brand}"
    return subject, body


def generate_redirect_response(contact, neg_config, their_format=""):
    """Respond when creator wants a different format."""
    name = contact.get("name", "").split()[0]
    sender = neg_config.get("sender_name", "")
    brand = neg_config.get("brand", "")

    body = f"""Hey {name},

Totally open to that! We're flexible on format.

Could you share:
1. What that would look like specifically?
2. Your rates for it?
3. Audience demographics (top countries, age/gender)?

We're mainly looking for the right audience fit — the format is secondary.

{sender}"""

    return f"Re: Collaboration with {brand}", body


def generate_too_expensive_response(contact, neg_config, their_price):
    """When their price exceeds our max budget."""
    name = contact.get("name", "").split()[0]
    sender = neg_config.get("sender_name", "")
    brand = neg_config.get("brand", "")
    budget_max = neg_config.get("budget_max", 0)

    body = f"""Hey {name},

Appreciate the transparency on pricing.

That's a bit above our current budget for a single integration. A couple thoughts:

1. Could we do a shorter integration (30-60 seconds) at a lower rate?
2. Or would you be open to a performance/affiliate model instead? We'd pay a base + commission on conversions.
3. Alternatively, if there's a format that's less work on your end (newsletter mention, community post, etc.), we'd be interested.

We're definitely keen to work together — just want to find a structure that works for both sides.

{sender}"""

    return f"Re: Collaboration with {brand}", body


def generate_followup(contact, neg_config, days_since):
    """Follow-up on an unanswered negotiate email."""
    name = contact.get("name", "").split()[0]
    sender = neg_config.get("sender_name", "")
    brand = neg_config.get("brand", "")

    if days_since <= 5:
        body = f"""Hey {name},

Just circling back on the above — let me know your thoughts. Happy to adjust if needed.

{sender}"""
    elif days_since <= 10:
        body = f"""Hey {name},

Still interested if you are! No pressure either way.

{sender}"""
    else:
        body = f"""Hey {name},

Totally understand if the timing isn't right. No hard feelings.

If anything changes down the road, we'd love to revisit. Keep making great content!

{sender}"""

    return f"Re: Collaboration with {brand}", body


# --- Main commands ---

def cmd_check(args):
    """Check for new replies from NEGOTIATE contacts and process them."""
    with open(args.config) as f:
        config = json.load(f)

    state = load_outreach_state(args.config)
    neg_config = load_negotiate_config(args.config)
    now = datetime.utcnow()

    # Find all contacts in negotiate stage (or any stage that hasn't been declined/closed)
    active = {}
    for email, contact in state["contacts"].items():
        if contact.get("negotiate_outcome") in ("won", "lost", "declined"):
            continue
        if contact.get("replied") or contact.get("negotiate"):
            active[email] = contact

    if not active:
        print("No active negotiations.")
        return

    # Check missing config — ask brand owner if needed
    missing = []
    if neg_config.get("budget_max") is None:
        missing.append("budget_max (hard cap per creator, e.g. 3000)")
    if neg_config.get("budget_min") is None:
        missing.append("budget_min (ideal price per creator, e.g. 1000)")
    if neg_config.get("negotiation_style") is None:
        missing.append("negotiation_style (friendly / value-focused / budget-strict)")

    if missing:
        print("⚠️ MISSING CONFIG — Ask brand owner:")
        for m in missing:
            print(f"  → {m}")
        print(f"\nSet these in negotiate_config.json or run:")
        print(f"  python3 negotiate.py set-config --config {args.config} --key budget_max --value 3000")
        print()

    # Fetch new replies
    print(f"Checking {len(active)} active negotiations for new replies...")
    client = get_gmail_client(args.config)

    earliest = min(
        datetime.fromisoformat(c["sent_at"]) for c in active.values()
    )
    replies = client.check_replies(list(active.keys()), since_date=earliest)

    new_replies = []
    for email_addr, msgs in replies.items():
        contact = active.get(email_addr)
        if not contact:
            continue

        # Check if we already processed this reply
        last_reply_id = contact.get("last_reply_id")
        for msg in msgs:
            if last_reply_id and msg.get("message_id") == last_reply_id:
                continue
            new_replies.append((email_addr, contact, msg))

    if not new_replies:
        print("No new replies to process.")

        # Check for follow-ups needed on stale negotiations
        followups_needed = []
        for email_addr, contact in active.items():
            last_sent = contact.get("negotiate_last_sent")
            if not last_sent:
                continue
            days = (now - datetime.fromisoformat(last_sent)).days
            followups = contact.get("negotiate_followups", 0)
            if followups < 3 and days >= 3:
                followups_needed.append((email_addr, contact, days))

        if followups_needed:
            print(f"\n{len(followups_needed)} negotiations need follow-up:")
            for email_addr, contact, days in followups_needed:
                print(f"  → {contact['name']} ({email_addr}) — {days} days since last email")

                if not args.dry_run:
                    subject, body = generate_followup(contact, neg_config, days)
                    reply_to = contact.get("negotiate_msg_id") or contact.get("message_id")
                    success, msg_id = send_negotiate_email(
                        client, email_addr, subject, body, reply_to
                    )
                    if success:
                        contact["negotiate_last_sent"] = now.isoformat()
                        contact["negotiate_followups"] = followups + 1
                        contact["negotiate_msg_id"] = msg_id
                        print(f"    ✅ Follow-up #{followups + 1} sent")

                        if followups + 1 >= 3:
                            contact["negotiate_outcome"] = "stale"
                            print(f"    ⏸ Max follow-ups reached → STALE (re-engage in 3 months)")
                else:
                    print(f"    [DRY RUN] Would send follow-up #{followups + 1}")

        save_outreach_state(args.config, state)
        return

    print(f"\n📬 {len(new_replies)} new replies to process:\n")

    for email_addr, contact, msg in new_replies:
        snippet = msg.get("snippet", "")
        subject = msg.get("subject", "")
        print(f"{'='*60}")
        print(f"From: {contact['name']} ({email_addr})")
        print(f"Subject: {subject}")
        print(f"Preview: {snippet[:200]}")

        # Classify
        classification = classify_reply(snippet, subject)
        print(f"Classification: {classification}")

        # Update state
        contact["last_reply_id"] = msg.get("message_id")
        contact["last_reply_at"] = now.isoformat()
        contact["negotiate_stage"] = classification

        # Generate response based on classification
        response_subject = None
        response_body = None
        reply_to = msg.get("message_id") or contact.get("message_id")

        if classification == "DECLINED":
            contact["negotiate_outcome"] = "declined"
            print(f"  → DECLINED. Marked as dead. Will re-engage in 3-6 months.")
            # No response sent — respect the no

        elif classification == "INTERESTED":
            # Check if we already have their rates/demographics
            has_demo = contact.get("has_demographics", False)
            has_rates = contact.get("has_rates", False)

            if not has_demo or not has_rates:
                response_subject, response_body = generate_discovery_response(contact, neg_config)
                print(f"  → Interested but need more info. Sending discovery questions.")
            else:
                # We have info, make an offer
                their_price = contact.get("their_price")
                if their_price and neg_config.get("budget_max"):
                    if their_price > neg_config["budget_max"]:
                        response_subject, response_body = generate_too_expensive_response(
                            contact, neg_config, their_price
                        )
                        print(f"  → Price ${their_price:,} exceeds budget. Sending alternative structure.")
                    else:
                        response_subject, response_body = generate_counter_offer(
                            contact, neg_config, their_price
                        )
                        print(f"  → Making counter-offer.")
                elif neg_config.get("budget_max"):
                    response_subject, response_body = generate_counter_offer(contact, neg_config)
                    print(f"  → Making initial offer.")
                else:
                    print(f"  ⚠️ Can't make offer — budget not set. Run set-config first.")

        elif classification == "PRICED":
            their_price = extract_price_from_reply(snippet)
            has_demo = extract_demographics_from_reply(snippet)

            if their_price:
                contact["their_price"] = their_price
                contact["has_rates"] = True
                print(f"  → Creator quoted ${their_price:,}")

            if has_demo:
                contact["has_demographics"] = True
                print(f"  → Demographics info detected")

            if their_price and neg_config.get("budget_max"):
                if their_price > neg_config["budget_max"]:
                    response_subject, response_body = generate_too_expensive_response(
                        contact, neg_config, their_price
                    )
                    print(f"  → Price exceeds budget. Proposing alternatives.")
                else:
                    response_subject, response_body = generate_counter_offer(
                        contact, neg_config, their_price
                    )
                    print(f"  → Counter-offering based on their ${their_price:,} ask.")
            elif their_price:
                print(f"  ⚠️ Got price but budget not set. Storing price, need config.")
            else:
                # They mentioned price but we couldn't extract it
                response_subject, response_body = generate_discovery_response(contact, neg_config)
                print(f"  → Couldn't extract exact price. Asking for clarification.")

        elif classification == "REDIRECT":
            response_subject, response_body = generate_redirect_response(contact, neg_config)
            print(f"  → Creator wants different format. Pivoting.")

        # Send response
        if response_subject and response_body:
            if not args.dry_run:
                success, msg_id = send_negotiate_email(
                    client, email_addr, response_subject, response_body, reply_to
                )
                if success:
                    contact["negotiate_last_sent"] = now.isoformat()
                    contact["negotiate_msg_id"] = msg_id
                    contact["negotiate_followups"] = 0  # Reset follow-up counter
                    print(f"  ✅ Response sent")
                else:
                    print(f"  ❌ Failed to send")
            else:
                print(f"  [DRY RUN] Would send:")
                print(f"  Subject: {response_subject}")
                print(f"  Body: {response_body[:200]}...")

        print()

    save_outreach_state(args.config, state)
    print(f"=== Done. {len(new_replies)} replies processed. ===")

    # Summary
    outcomes = {}
    for email_addr, contact in state["contacts"].items():
        stage = contact.get("negotiate_stage", contact.get("stage", "unknown"))
        outcomes[stage] = outcomes.get(stage, 0) + 1

    print(f"\nCampaign status:")
    for stage, count in sorted(outcomes.items()):
        print(f"  {stage}: {count}")


def send_negotiate_email(client, to, subject, body, reply_to_msg_id=None):
    """Send a negotiate email via gmail client."""
    try:
        msg_id = client.send(to, subject, body, reply_to_msg_id=reply_to_msg_id)
        return True, msg_id
    except Exception as e:
        print(f"  ❌ Send error: {e}")
        return False, str(e)


def cmd_status(args):
    """Show all active negotiations."""
    state = load_outreach_state(args.config)
    neg_config = load_negotiate_config(args.config)

    negotiations = {e: c for e, c in state["contacts"].items()
                    if c.get("replied") or c.get("negotiate")}

    if not negotiations:
        print("No active negotiations.")
        return

    print(f"=== {len(negotiations)} negotiations ===\n")

    # Group by outcome/stage
    active = []
    won = []
    lost = []
    stale = []

    for email, contact in negotiations.items():
        outcome = contact.get("negotiate_outcome")
        if outcome == "won":
            won.append((email, contact))
        elif outcome in ("lost", "declined"):
            lost.append((email, contact))
        elif outcome == "stale":
            stale.append((email, contact))
        else:
            active.append((email, contact))

    if active:
        print("🟢 ACTIVE:")
        for email, c in active:
            stage = c.get("negotiate_stage", "?")
            price = c.get("their_price")
            price_str = f" (${price:,.0f})" if price else ""
            days = ""
            if c.get("negotiate_last_sent"):
                d = (datetime.utcnow() - datetime.fromisoformat(c["negotiate_last_sent"])).days
                days = f" — {d}d since last email"
            print(f"  {c['name']:30s} {stage:12s}{price_str}{days}")

    if won:
        print("\n🏆 WON:")
        for email, c in won:
            price = c.get("agreed_price", "?")
            print(f"  {c['name']:30s} ${price}")

    if lost:
        print("\n❌ DECLINED:")
        for email, c in lost:
            print(f"  {c['name']:30s}")

    if stale:
        print("\n⏸ STALE (re-engage later):")
        for email, c in stale:
            print(f"  {c['name']:30s}")

    # Config status
    print(f"\n--- Config ---")
    print(f"Budget: ${neg_config.get('budget_min', '?')} - ${neg_config.get('budget_max', '?')}")
    print(f"Style: {neg_config.get('negotiation_style', 'NOT SET')}")
    print(f"Payment: {neg_config.get('payment_terms', '50/50')}")


def cmd_set_config(args):
    """Set a negotiate config value."""
    neg_config = load_negotiate_config(args.config)

    key = args.key
    value = args.value

    # Type conversion
    if key in ("budget_min", "budget_max"):
        value = float(value)
    elif key == "deal_breakers":
        value = [v.strip() for v in value.split(",")]
    elif key == "preferred_formats":
        value = [v.strip() for v in value.split(",")]

    neg_config[key] = value
    save_negotiate_config(args.config, neg_config)
    print(f"✅ {key} = {value}")


def cmd_close(args):
    """Close a negotiation as won/lost/stale."""
    state = load_outreach_state(args.config)

    contact = state["contacts"].get(args.email)
    if not contact:
        print(f"❌ Contact not found: {args.email}")
        return

    contact["negotiate_outcome"] = args.outcome
    contact["closed_at"] = datetime.utcnow().isoformat()

    if args.outcome == "won" and args.price:
        contact["agreed_price"] = float(args.price)

    save_outreach_state(args.config, state)
    print(f"✅ {contact['name']} ({args.email}) → {args.outcome.upper()}")


# --- CLI ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FameClaw Negotiate Engine")
    sub = parser.add_subparsers(dest="command")

    p_check = sub.add_parser("check", help="Check for replies and auto-respond")
    p_check.add_argument("--config", default="outreach.json")
    p_check.add_argument("--dry-run", action="store_true")

    p_reply = sub.add_parser("reply", help="Send a manual negotiate reply")
    p_reply.add_argument("--config", default="outreach.json")
    p_reply.add_argument("--to", required=True)
    p_reply.add_argument("--subject", required=True)
    p_reply.add_argument("--body", required=True)

    p_status = sub.add_parser("status", help="Show negotiation status")
    p_status.add_argument("--config", default="outreach.json")

    p_config = sub.add_parser("set-config", help="Set negotiate config")
    p_config.add_argument("--config", default="outreach.json")
    p_config.add_argument("--key", required=True)
    p_config.add_argument("--value", required=True)

    p_close = sub.add_parser("close", help="Close a negotiation")
    p_close.add_argument("--config", default="outreach.json")
    p_close.add_argument("--email", required=True)
    p_close.add_argument("--outcome", required=True, choices=["won", "lost", "stale"])
    p_close.add_argument("--price", help="Agreed price (if won)")

    args = parser.parse_args()

    if args.command == "check":
        cmd_check(args)
    elif args.command == "reply":
        client = get_gmail_client(args.config)
        state = load_outreach_state(args.config)
        contact = state["contacts"].get(args.to)
        reply_to = None
        if contact:
            reply_to = contact.get("negotiate_msg_id") or contact.get("message_id")
        success, msg_id = send_negotiate_email(client, args.to, args.subject, args.body, reply_to)
        if success:
            if contact:
                contact["negotiate_last_sent"] = datetime.utcnow().isoformat()
                contact["negotiate_msg_id"] = msg_id
                save_outreach_state(args.config, state)
            print(f"✅ Sent to {args.to}")
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "set-config":
        cmd_set_config(args)
    elif args.command == "close":
        cmd_close(args)
    else:
        parser.print_help()
