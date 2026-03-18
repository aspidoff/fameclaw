#!/usr/bin/env python3
"""FameClaw AgentMail Provider — Alternative to SMTP/IMAP using AgentMail API.

AgentMail (agentmail.to) provides dedicated email inboxes for AI agents.
No Gmail app passwords needed — just an API key.

Setup:
    pip install agentmail
    Add to gmail.json: {"provider": "agentmail", "api_key": "am_..."}

Usage:
    Same interface as gmail.py — drop-in replacement.
"""

import json
from datetime import datetime
from pathlib import Path

try:
    from agentmail import AgentMail
    HAS_AGENTMAIL = True
except ImportError:
    HAS_AGENTMAIL = False

DEFAULT_CREDS = Path.home() / ".config" / "fameclaw" / "gmail.json"


class AgentMailClient:
    """Drop-in replacement for GmailClient using AgentMail API."""

    def __init__(self, creds_path=None):
        if not HAS_AGENTMAIL:
            raise ImportError(
                "agentmail package not installed. Run: pip install agentmail"
            )

        if creds_path is None:
            creds_path = str(DEFAULT_CREDS)

        with open(creds_path) as f:
            creds = json.load(f)

        self.api_key = creds.get("api_key", creds.get("agentmail_api_key", ""))
        self.inbox_id = creds.get("inbox_id", "")
        self.from_email = creds.get("from_email", "")
        self.display_name = creds.get("display_name", "")

        self.client = AgentMail(api_key=self.api_key)

        # Auto-create inbox if not set
        if not self.inbox_id:
            self._setup_inbox(creds, creds_path)

    def _setup_inbox(self, creds, creds_path):
        """Create a new inbox and save config."""
        display = self.display_name or "FameClaw Outreach"
        inbox = self.client.inboxes.create(
            display_name=display
        )
        self.inbox_id = inbox.id
        self.from_email = inbox.email

        # Save back to config
        creds["inbox_id"] = self.inbox_id
        creds["from_email"] = self.from_email
        with open(creds_path, "w") as f:
            json.dump(creds, f, indent=2)
        print(f"✅ AgentMail inbox created: {self.from_email}")

    def _from_addr(self):
        if self.display_name:
            return f"{self.display_name} <{self.from_email}>"
        return self.from_email

    def send(self, to, subject, body, html=False, reply_to_msg_id=None, thread_subject=None):
        """Send an email via AgentMail. Returns message_id."""
        kwargs = {
            "to": [{"email": to}],
            "subject": subject,
        }

        if html:
            kwargs["html"] = body
        else:
            kwargs["text"] = body

        if self.display_name:
            kwargs["from_"] = {"name": self.display_name, "email": self.from_email}

        if reply_to_msg_id:
            kwargs["in_reply_to"] = reply_to_msg_id
            kwargs["references"] = [reply_to_msg_id]

        msg = self.client.messages.send(
            inbox_id=self.inbox_id,
            **kwargs
        )

        return msg.message_id if hasattr(msg, "message_id") else str(msg.id)

    def check_replies(self, sent_emails, since_date=None):
        """Check for replies from specific email addresses.
        Returns dict: {email: [{subject, date, snippet, uid, message_id}]}
        """
        replies = {}

        for sender_email in sent_emails:
            try:
                threads = self.client.threads.list(
                    inbox_id=self.inbox_id
                )

                for thread in threads.data if hasattr(threads, "data") else threads:
                    thread_id = thread.id if hasattr(thread, "id") else thread
                    messages = self.client.messages.list(
                        inbox_id=self.inbox_id,
                        thread_id=str(thread_id)
                    )

                    msg_list = messages.data if hasattr(messages, "data") else messages
                    for msg in msg_list:
                        from_addr = ""
                        if hasattr(msg, "from_"):
                            from_addr = msg.from_.email if hasattr(msg.from_, "email") else str(msg.from_)
                        elif hasattr(msg, "from_address"):
                            from_addr = msg.from_address

                        if sender_email.lower() in from_addr.lower():
                            if sender_email not in replies:
                                replies[sender_email] = []

                            created = ""
                            if hasattr(msg, "created_at"):
                                created = str(msg.created_at)

                            snippet = ""
                            if hasattr(msg, "text"):
                                snippet = (msg.text or "")[:200]
                            elif hasattr(msg, "snippet"):
                                snippet = (msg.snippet or "")[:200]

                            replies[sender_email].append({
                                "subject": getattr(msg, "subject", ""),
                                "date": created,
                                "message_id": getattr(msg, "message_id", ""),
                                "snippet": snippet,
                                "uid": str(getattr(msg, "id", "")),
                            })

            except Exception as e:
                print(f"  ⚠️ Error checking {sender_email}: {e}")
                continue

        return replies

    def search_inbox(self, query="", max_results=20):
        """List recent messages."""
        results = []
        try:
            messages = self.client.messages.list(
                inbox_id=self.inbox_id
            )
            msg_list = messages.data if hasattr(messages, "data") else messages

            for msg in list(msg_list)[:max_results]:
                from_addr = ""
                if hasattr(msg, "from_"):
                    from_addr = str(msg.from_)

                results.append({
                    "from": from_addr,
                    "subject": getattr(msg, "subject", ""),
                    "date": str(getattr(msg, "created_at", "")),
                    "uid": str(getattr(msg, "id", "")),
                })
        except Exception as e:
            print(f"  ⚠️ Error listing inbox: {e}")

        return results

    def test_connection(self):
        """Test AgentMail connection."""
        errors = []

        try:
            # Test API connection
            inboxes = self.client.inboxes.list()
            inbox_count = len(inboxes.data) if hasattr(inboxes, "data") else len(list(inboxes))
            print(f"  ✅ AgentMail API: connected ({inbox_count} inboxes)")

            if self.inbox_id:
                inbox = self.client.inboxes.get(self.inbox_id)
                print(f"  ✅ Inbox: {self.from_email}")
            else:
                print(f"  ⚠️ No inbox configured (will auto-create on first use)")

        except Exception as e:
            errors.append(str(e))
            print(f"  ❌ AgentMail API: {e}")

        return len(errors) == 0


def get_mail_client(creds_path=None):
    """Factory function — returns the right client based on config.
    
    Use this instead of importing GmailClient or AgentMailClient directly.
    """
    if creds_path is None:
        creds_path = str(DEFAULT_CREDS)

    with open(creds_path) as f:
        creds = json.load(f)

    provider = creds.get("provider", "").lower()

    if provider == "agentmail" or creds.get("api_key") or creds.get("agentmail_api_key"):
        return AgentMailClient(creds_path)
    else:
        # Fall back to SMTP/IMAP
        from gmail import GmailClient
        return GmailClient(creds_path)


# --- CLI ---
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FameClaw AgentMail Provider")
    sub = parser.add_subparsers(dest="command")

    p_setup = sub.add_parser("setup", help="Setup AgentMail")
    p_setup.add_argument("--api-key", required=True, help="AgentMail API key")
    p_setup.add_argument("--display-name", default="FameClaw Outreach")

    p_test = sub.add_parser("test", help="Test connection")
    p_test.add_argument("--creds", default=str(DEFAULT_CREDS))

    args = parser.parse_args()

    if args.command == "setup":
        creds_path = str(DEFAULT_CREDS)
        creds_path_obj = Path(creds_path)
        creds_path_obj.parent.mkdir(parents=True, exist_ok=True)

        config = {
            "provider": "agentmail",
            "api_key": args.api_key,
            "display_name": args.display_name,
        }

        # If existing config, merge
        if creds_path_obj.exists():
            with open(creds_path) as f:
                existing = json.load(f)
            existing.update(config)
            config = existing

        with open(creds_path, "w") as f:
            json.dump(config, f, indent=2)
        creds_path_obj.chmod(0o600)

        print(f"✅ Config saved to {creds_path}")
        print("Testing connection...")
        client = AgentMailClient(creds_path)
        client.test_connection()

    elif args.command == "test":
        client = AgentMailClient(args.creds)
        client.test_connection()

    else:
        parser.print_help()
