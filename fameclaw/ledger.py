"""
Ledger management - records of all sent messages and campaign activity.
"""

from datetime import datetime, timedelta
from typing import Optional

from .state import StateManager
from .models import Ledger, LedgerEntry
from .validation import normalize_email


class LedgerManager:
    """Manage the outreach ledger (all sent messages)."""

    LEDGER_FILE = "ledger.json"

    def __init__(self, state_dir: str = "~/.openclaw/outreach"):
        """Initialize ledger manager."""
        self.state_dir = state_dir
        self.state_manager = StateManager(state_dir)

    def load(self) -> Ledger:
        """Load ledger from state."""
        ledger_data = self.state_manager.read(self.LEDGER_FILE)

        if not ledger_data:
            return Ledger(version=1, entries=[])

        entries = [
            LedgerEntry(
                campaign_id=e["campaign_id"],
                recipient_email=normalize_email(e["recipient_email"]),
                message_id=e["message_id"],
                sent_at=e["sent_at"],
                status=e["status"],
                bounce_type=e.get("bounce_type"),
                error_message=e.get("error_message"),
            )
            for e in ledger_data.get("entries", [])
        ]

        return Ledger(version=ledger_data.get("version", 1), entries=entries)

    def save(self, ledger: Ledger) -> None:
        """Save ledger to state."""
        ledger_data = {
            "version": ledger.version,
            "entries": [
                {
                    "campaign_id": e.campaign_id,
                    "recipient_email": e.recipient_email,
                    "message_id": e.message_id,
                    "sent_at": e.sent_at,
                    "status": e.status,
                    "bounce_type": e.bounce_type,
                    "error_message": e.error_message,
                }
                for e in ledger.entries
            ],
        }
        self.state_manager.write(self.LEDGER_FILE, ledger_data)

    def add_entry(
        self,
        campaign_id=None,
        recipient_email: Optional[str] = None,
        message_id: Optional[str] = None,
        status: str = "sending",
        bounce_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> LedgerEntry:
        """
        Add entry to ledger.

        Can be called with:
        1. A LedgerEntry object: add_entry(entry)
        2. Individual parameters: add_entry(campaign_id, recipient_email, message_id, ...)

        Args:
            campaign_id: Campaign ID or LedgerEntry object
            recipient_email: Recipient email (if not using LedgerEntry object)
            message_id: AgentMail message ID
            status: Message status
            bounce_type: Type of bounce (hard/soft) if bounced
            error_message: Error message if failed

        Returns:
            Created LedgerEntry
        """
        ledger = self.load()

        # Handle both LedgerEntry object and individual parameters
        if isinstance(campaign_id, LedgerEntry):
            entry = campaign_id
            entry.recipient_email = normalize_email(entry.recipient_email)
        else:
            recipient_email = normalize_email(recipient_email)
            sent_at = datetime.utcnow().isoformat() + "Z"

            entry = LedgerEntry(
                campaign_id=campaign_id,
                recipient_email=recipient_email,
                message_id=message_id,
                sent_at=sent_at,
                status=status,
                bounce_type=bounce_type,
                error_message=error_message,
            )

        ledger.entries.append(entry)
        self.save(ledger)
        return entry

    def update_entry_status(
        self,
        message_id: str,
        status: str,
        bounce_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[LedgerEntry]:
        """
        Update entry status by message ID.

        Args:
            message_id: AgentMail message ID
            status: New status
            bounce_type: Type of bounce if applicable
            error_message: Error message if applicable

        Returns:
            Updated entry or None if not found
        """
        ledger = self.load()

        for entry in ledger.entries:
            if entry.message_id == message_id:
                entry.status = status
                if bounce_type is not None:
                    entry.bounce_type = bounce_type
                if error_message is not None:
                    entry.error_message = error_message
                self.save(ledger)
                return entry

        return None

    def update_status(
        self,
        lookup_value: str,
        new_status: str,
        lookup_field: str = "message_id",
        bounce_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[LedgerEntry]:
        """
        Update entry status by flexible field lookup.

        Args:
            lookup_value: Value to search for
            new_status: New status
            lookup_field: Field to search by (message_id, campaign_id, recipient_email)
            bounce_type: Type of bounce if applicable
            error_message: Error message if applicable

        Returns:
            Updated entry or None if not found
        """
        ledger = self.load()
        field_map = {
            "message_id": "message_id",
            "campaign_id": "campaign_id",
            "recipient_email": "recipient_email",
        }

        if lookup_field not in field_map:
            raise ValueError(f"Unknown lookup field: {lookup_field}")

        for entry in ledger.entries:
            if getattr(entry, field_map[lookup_field]) == lookup_value:
                entry.status = new_status
                if bounce_type is not None:
                    entry.bounce_type = bounce_type
                if error_message is not None:
                    entry.error_message = error_message
                self.save(ledger)
                return entry

        return None

    def get_by_message_id(self, message_id: str) -> Optional[LedgerEntry]:
        """Get ledger entry by message ID."""
        ledger = self.load()
        for entry in ledger.entries:
            if entry.message_id == message_id:
                return entry
        return None

    def get_by_campaign(self, campaign_id: str) -> list[LedgerEntry]:
        """Get all ledger entries for a campaign."""
        ledger = self.load()
        return [e for e in ledger.entries if e.campaign_id == campaign_id]

    def get_by_recipient(self, recipient_email: str) -> list[LedgerEntry]:
        """Get all ledger entries for a recipient."""
        ledger = self.load()
        recipient_email = normalize_email(recipient_email)
        return [
            e for e in ledger.entries if e.recipient_email == recipient_email
        ]

    def find_by_message_id(self, message_id: str) -> Optional[LedgerEntry]:
        """Alias for get_by_message_id."""
        return self.get_by_message_id(message_id)

    def find_by_email(self, recipient_email: str) -> list[LedgerEntry]:
        """Alias for get_by_recipient."""
        return self.get_by_recipient(recipient_email)

    def find_by_campaign(self, campaign_id: str) -> list[LedgerEntry]:
        """Alias for get_by_campaign."""
        return self.get_by_campaign(campaign_id)

    def find_by_status(self, status: str) -> list[LedgerEntry]:
        """Get all ledger entries with a specific status."""
        ledger = self.load()
        return [e for e in ledger.entries if e.status == status]

    def campaign_stats(self, campaign_id: str) -> dict:
        """Get statistics for a campaign."""
        entries = self.find_by_campaign(campaign_id)
        
        stats = {
            "total_sent": len(entries),
            "total_bounced": len([e for e in entries if "bounce" in e.status.lower()]),
            "total_opened": len([e for e in entries if e.status == "opened"]),
            "total_clicked": len([e for e in entries if e.status == "clicked"]),
            "total_replied": len([e for e in entries if e.status == "replied"]),
        }
        
        return stats

    def get_recent_campaigns_for_recipient(
        self, recipient_email: str, days: int = 30
    ) -> list[str]:
        """
        Get campaigns sent to a recipient in the last N days (for cooldown check).

        Args:
            recipient_email: Recipient email
            days: Look back this many days

        Returns:
            List of campaign IDs (unique)
        """
        recipient_email = normalize_email(recipient_email)
        cutoff = datetime.utcnow() - timedelta(days=days)
        cutoff_iso = cutoff.isoformat() + "Z"

        ledger = self.load()
        campaigns = set()

        for entry in ledger.entries:
            if (
                entry.recipient_email == recipient_email
                and entry.sent_at >= cutoff_iso
            ):
                campaigns.add(entry.campaign_id)

        return sorted(list(campaigns))

    def check_dedup(self, campaign_id: str, recipient_email: str) -> bool:
        """
        Check if recipient is already in this campaign.

        Args:
            campaign_id: Campaign ID
            recipient_email: Recipient email

        Returns:
            True if already sent to this recipient in this campaign
        """
        recipient_email = normalize_email(recipient_email)
        ledger = self.load()

        for entry in ledger.entries:
            if (
                entry.campaign_id == campaign_id
                and entry.recipient_email == recipient_email
                and entry.status in ("sending", "sent", "opened", "clicked", "replied")
            ):
                return True

        return False

    def is_duplicate(self, entry: LedgerEntry) -> Optional[LedgerEntry]:
        """
        Check if entry is a duplicate.
        
        Duplicates are detected by:
        1. Same message_id (exact duplicate)
        2. Same campaign_id + recipient_email (campaign dedup)

        Args:
            entry: Entry to check

        Returns:
            Existing entry if duplicate found, None otherwise
        """
        ledger = self.load()
        recipient_email = normalize_email(entry.recipient_email)

        for existing in ledger.entries:
            # Check by message_id first
            if existing.message_id == entry.message_id:
                return existing
            
            # Check by campaign + recipient
            if (
                existing.campaign_id == entry.campaign_id
                and normalize_email(existing.recipient_email) == recipient_email
            ):
                return existing

        return None

    def count_sends_today(self) -> int:
        """Count total sends today (UTC)."""
        ledger = self.load()
        today = datetime.utcnow().date().isoformat()

        count = 0
        for entry in ledger.entries:
            entry_date = entry.sent_at.split("T")[0]
            if entry_date == today and entry.status in ("sending", "sent", "opened", "clicked", "replied"):
                count += 1

        return count

    def count_sends_in_hour(self) -> int:
        """Count sends in the last hour."""
        ledger = self.load()
        cutoff = datetime.utcnow() - timedelta(hours=1)
        cutoff_iso = cutoff.isoformat() + "Z"

        count = 0
        for entry in ledger.entries:
            if entry.sent_at >= cutoff_iso and entry.status in ("sending", "sent", "opened", "clicked", "replied"):
                count += 1

        return count

    def get_hard_bounces(self, campaign_id: Optional[str] = None) -> list[LedgerEntry]:
        """Get all hard bounces, optionally filtered by campaign."""
        ledger = self.load()
        bounces = [e for e in ledger.entries if e.bounce_type == "hard"]

        if campaign_id:
            bounces = [e for e in bounces if e.campaign_id == campaign_id]

        return bounces

    def get_soft_bounces(self, campaign_id: Optional[str] = None) -> list[LedgerEntry]:
        """Get all soft bounces, optionally filtered by campaign."""
        ledger = self.load()
        bounces = [e for e in ledger.entries if e.bounce_type == "soft"]

        if campaign_id:
            bounces = [e for e in bounces if e.campaign_id == campaign_id]

        return bounces

    def reverse_index_by_email(self) -> dict[str, list[str]]:
        """
        Build reverse index: email -> [campaign_ids].

        Returns:
            Dict mapping email to list of campaign IDs
        """
        ledger = self.load()
        index = {}

        for entry in ledger.entries:
            email = entry.recipient_email
            if email not in index:
                index[email] = []
            if entry.campaign_id not in index[email]:
                index[email].append(entry.campaign_id)

        return index
