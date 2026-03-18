#!/usr/bin/env python3
"""FameClaw Gmail Client — SMTP send + IMAP reply tracking.

Zero dependencies beyond Python stdlib.
Uses app password for auth (same password for SMTP + IMAP).

Setup:
    1. Google Account → Security → 2-Step Verification → ON
    2. Google Account → Security → App passwords → Generate
    3. Save to gmail_creds.json:
       {"email": "you@gmail.com", "app_password": "xxxx xxxx xxxx xxxx"}
"""

import email
import email.mime.multipart
import email.mime.text
import email.utils
import imaplib
import json
import smtplib
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
DEFAULT_CREDS = Path.home() / ".config" / "fameclaw" / "gmail.json"


class GmailClient:
    def __init__(self, creds_path):
        with open(creds_path) as f:
            creds = json.load(f)
        self.email_addr = creds["email"]
        self.password = creds["app_password"].replace(" ", "")
        self.display_name = creds.get("display_name", "")

    def _from_addr(self):
        if self.display_name:
            return f"{self.display_name} <{self.email_addr}>"
        return self.email_addr

    def send(self, to, subject, body, html=False, reply_to_msg_id=None, thread_subject=None):
        """Send an email. Returns message_id on success."""
        if html:
            msg = email.mime.multipart.MIMEMultipart("alternative")
            msg.attach(email.mime.text.MIMEText(body, "html"))
        else:
            msg = email.mime.text.MIMEText(body, "plain")

        msg["From"] = self._from_addr()
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = email.utils.make_msgid(domain=self.email_addr.split("@")[1])

        # Threading — set In-Reply-To and References for follow-ups
        if reply_to_msg_id:
            msg["In-Reply-To"] = reply_to_msg_id
            msg["References"] = reply_to_msg_id

        ctx = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls(context=ctx)
            server.login(self.email_addr, self.password)
            server.send_message(msg)

        return msg["Message-ID"]

    def check_replies(self, sent_emails, since_date=None):
        """Check IMAP inbox for replies from specific email addresses.
        Returns dict: {email: [{subject, date, snippet, uid}]}
        """
        replies = {}
        ctx = ssl.create_default_context()

        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx) as imap:
            imap.login(self.email_addr, self.password)
            imap.select("INBOX")

            for sender_email in sent_emails:
                criteria = f'(FROM "{sender_email}")'
                if since_date:
                    date_str = since_date.strftime("%d-%b-%Y")
                    criteria = f'(FROM "{sender_email}" SINCE {date_str})'

                _, msg_nums = imap.search(None, criteria)
                if not msg_nums[0]:
                    continue

                msgs = []
                for num in msg_nums[0].split():
                    _, data = imap.fetch(num, "(RFC822.HEADER BODY.PEEK[TEXT]<0.500>)")
                    if not data or not data[0]:
                        continue

                    # Parse header
                    header_data = data[0][1] if isinstance(data[0], tuple) else data[0]
                    msg_obj = email.message_from_bytes(header_data)
                    
                    subject = str(email.header.decode_header(msg_obj.get("Subject", ""))[0][0] or "")
                    if isinstance(subject, bytes):
                        subject = subject.decode("utf-8", errors="replace")
                    
                    date_str = msg_obj.get("Date", "")
                    msg_id = msg_obj.get("Message-ID", "")

                    # Get snippet from body part
                    snippet = ""
                    if len(data) > 1 and data[1] and isinstance(data[1], tuple):
                        try:
                            snippet = data[1][1].decode("utf-8", errors="replace")[:200]
                        except (AttributeError, IndexError):
                            pass

                    msgs.append({
                        "subject": subject,
                        "date": date_str,
                        "message_id": msg_id,
                        "snippet": snippet.strip(),
                        "uid": num.decode(),
                    })

                if msgs:
                    replies[sender_email] = msgs

        return replies

    def search_inbox(self, query, max_results=20):
        """Search inbox with IMAP query. Returns list of message summaries."""
        results = []
        ctx = ssl.create_default_context()

        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx) as imap:
            imap.login(self.email_addr, self.password)
            imap.select("INBOX")

            _, msg_nums = imap.search(None, query)
            if not msg_nums[0]:
                return results

            nums = msg_nums[0].split()[-max_results:]
            for num in reversed(nums):
                _, data = imap.fetch(num, "(RFC822.HEADER)")
                if not data or not data[0]:
                    continue
                header_data = data[0][1] if isinstance(data[0], tuple) else data[0]
                msg_obj = email.message_from_bytes(header_data)

                subject = str(email.header.decode_header(msg_obj.get("Subject", ""))[0][0] or "")
                if isinstance(subject, bytes):
                    subject = subject.decode("utf-8", errors="replace")

                from_addr = msg_obj.get("From", "")
                date_str = msg_obj.get("Date", "")

                results.append({
                    "from": from_addr,
                    "subject": subject,
                    "date": date_str,
                    "uid": num.decode(),
                })

        return results

    def test_connection(self):
        """Test both SMTP and IMAP connections."""
        errors = []

        # Test SMTP
        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls(context=ctx)
                server.login(self.email_addr, self.password)
            print(f"  ✅ SMTP: connected as {self.email_addr}")
        except Exception as e:
            errors.append(f"SMTP: {e}")
            print(f"  ❌ SMTP: {e}")

        # Test IMAP
        try:
            ctx = ssl.create_default_context()
            with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx) as imap:
                imap.login(self.email_addr, self.password)
                imap.select("INBOX")
                _, msgs = imap.search(None, "ALL")
                count = len(msgs[0].split()) if msgs[0] else 0
            print(f"  ✅ IMAP: connected ({count} messages in inbox)")
        except Exception as e:
            errors.append(f"IMAP: {e}")
            print(f"  ❌ IMAP: {e}")

        return len(errors) == 0


# --- CLI ---
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FameClaw Gmail Client")
    sub = parser.add_subparsers(dest="command")

    default_creds = str(DEFAULT_CREDS)

    p_test = sub.add_parser("test", help="Test Gmail connection")
    p_test.add_argument("--creds", default=default_creds)

    p_send = sub.add_parser("send", help="Send an email")
    p_send.add_argument("--creds", default=default_creds)
    p_send.add_argument("--to", required=True)
    p_send.add_argument("--subject", required=True)
    p_send.add_argument("--body", required=True)
    p_send.add_argument("--html", action="store_true")

    p_replies = sub.add_parser("replies", help="Check for replies from addresses")
    p_replies.add_argument("--creds", default=default_creds)
    p_replies.add_argument("--from-emails", nargs="+", required=True)
    p_replies.add_argument("--since", help="Check since date (YYYY-MM-DD)")

    p_inbox = sub.add_parser("inbox", help="Show recent inbox")
    p_inbox.add_argument("--creds", default=default_creds)
    p_inbox.add_argument("--query", default="UNSEEN")
    p_inbox.add_argument("--max", type=int, default=20)

    args = parser.parse_args()

    if args.command == "test":
        print("Testing Gmail connection...")
        client = GmailClient(args.creds)
        ok = client.test_connection()
        sys.exit(0 if ok else 1)

    elif args.command == "send":
        client = GmailClient(args.creds)
        msg_id = client.send(args.to, args.subject, args.body, html=args.html)
        print(f"✅ Sent to {args.to} (Message-ID: {msg_id})")

    elif args.command == "replies":
        client = GmailClient(args.creds)
        since = datetime.strptime(args.since, "%Y-%m-%d") if args.since else None
        replies = client.check_replies(args.from_emails, since)
        for addr, msgs in replies.items():
            print(f"\n📬 {addr}:")
            for m in msgs:
                print(f"  [{m['date']}] {m['subject']}")
                if m.get("snippet"):
                    print(f"  {m['snippet'][:100]}")
        if not replies:
            print("No replies found.")

    elif args.command == "inbox":
        client = GmailClient(args.creds)
        msgs = client.search_inbox(args.query, args.max)
        for m in msgs:
            print(f"  [{m['date'][:20]}] {m['from'][:30]:30s} {m['subject'][:50]}")
        if not msgs:
            print("No messages found.")

    else:
        parser.print_help()
