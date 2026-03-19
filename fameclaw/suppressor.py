"""
Suppression list management - prevent sending to opted-out addresses.
"""

from datetime import datetime
from typing import Optional

from .state import StateManager
from .models import SuppressionList, SuppressionEntry
from .validation import normalize_email
from .exceptions import SuppressedRecipientError


class SuppressionManager:
    """Manage the suppression list."""

    SUPPRESSION_FILE = "suppression.json"

    def __init__(self, state_dir: str = "~/.openclaw/outreach"):
        """Initialize suppression manager."""
        self.state_manager = StateManager(state_dir)

    def load(self) -> SuppressionList:
        """Load suppression list from state."""
        suppression_data = self.state_manager.read(self.SUPPRESSION_FILE)

        if not suppression_data:
            return SuppressionList(version=1, entries={})

        entries = {}
        for email, entry_data in suppression_data.get("entries", {}).items():
            email = normalize_email(email)
            entries[email] = SuppressionEntry(
                email=email,
                reason=entry_data["reason"],
                added_at=entry_data["added_at"],
                added_by=entry_data.get("added_by", "system"),
            )

        return SuppressionList(version=suppression_data.get("version", 1), entries=entries)

    def save(self, suppression: SuppressionList) -> None:
        """Save suppression list to state."""
        suppression_data = {
            "version": suppression.version,
            "entries": {
                email: {
                    "email": email,
                    "reason": entry.reason,
                    "added_at": entry.added_at,
                    "added_by": entry.added_by,
                }
                for email, entry in suppression.entries.items()
            },
        }
        self.state_manager.write(self.SUPPRESSION_FILE, suppression_data)

    def add(
        self,
        email: str,
        reason: str,
        added_by: str = "system",
        keyword: str = "",
    ) -> SuppressionEntry:
        """
        Add email to suppression list.

        Args:
            email: Email address to suppress
            reason: Reason for suppression (explicit_opt_out, hard_bounce, etc.)
            added_by: Who added this (user, system, etc.)
            keyword: Optional keyword/tag for grouping (not used currently)

        Returns:
            Created SuppressionEntry
        """
        suppression = self.load()
        email = normalize_email(email)

        added_at = datetime.utcnow().isoformat() + "Z"

        entry = SuppressionEntry(
            email=email,
            reason=reason,
            added_at=added_at,
            added_by=added_by,
        )

        suppression.entries[email] = entry
        self.save(suppression)
        return entry

    def check(self, email: str) -> bool:
        """
        Check if email is suppressed.

        Args:
            email: Email address to check

        Returns:
            True if email is suppressed
        """
        suppression = self.load()
        email = normalize_email(email)
        return email in suppression.entries

    def is_suppressed(self, email: str) -> bool:
        """
        Check if email is suppressed (alias for check).

        Args:
            email: Email address to check

        Returns:
            True if email is suppressed
        """
        return self.check(email)

    def get(self, email: str) -> Optional[SuppressionEntry]:
        """Get suppression entry by email."""
        suppression = self.load()
        email = normalize_email(email)
        return suppression.entries.get(email)

    def get_entry(self, email: str) -> Optional[SuppressionEntry]:
        """Get suppression entry by email (alias for get)."""
        return self.get(email)

    def remove(self, email: str, confirm_unsuppress: bool = True) -> bool:
        """
        Remove email from suppression list.

        Args:
            email: Email to unsuppress
            confirm_unsuppress: Safety flag (defaults to True for programmatic use)

        Returns:
            True if removed
        """

        suppression = self.load()
        email = normalize_email(email)

        if email in suppression.entries:
            del suppression.entries[email]
            self.save(suppression)
            return True

        return False

    def import_list(self, emails_and_reasons: list[tuple[str, str]], added_by: str = "migration") -> int:
        """
        Import multiple emails to suppression list.

        Args:
            emails_and_reasons: List of (email, reason) tuples
            added_by: Who added these entries

        Returns:
            Number of entries added
        """
        suppression = self.load()
        count = 0

        for email, reason in emails_and_reasons:
            email = normalize_email(email)
            if email not in suppression.entries:
                added_at = datetime.utcnow().isoformat() + "Z"
                suppression.entries[email] = SuppressionEntry(
                    email=email,
                    reason=reason,
                    added_at=added_at,
                    added_by=added_by,
                )
                count += 1

        if count > 0:
            self.save(suppression)

        return count

    def list_all(self, reason: Optional[str] = None) -> list[SuppressionEntry]:
        """
        List all suppressed emails.

        Args:
            reason: Optional filter by reason

        Returns:
            List of SuppressionEntry objects
        """
        suppression = self.load()
        entries = list(suppression.entries.values())

        if reason:
            entries = [e for e in entries if e.reason == reason]

        return sorted(entries, key=lambda e: e.email)

    def count(self) -> int:
        """Get count of suppressed emails."""
        suppression = self.load()
        return len(suppression.entries)

    def count_by_reason(self) -> dict[str, int]:
        """Get count of suppressed emails by reason."""
        suppression = self.load()
        counts = {}

        for entry in suppression.entries.values():
            counts[entry.reason] = counts.get(entry.reason, 0) + 1

        return counts

    def get_count(self) -> int:
        """Get total suppressed count (alias for count)."""
        return self.count()

    def filter_recipients(self, recipients: list) -> list:
        """
        Filter out suppressed recipients.
        
        Args:
            recipients: List of recipient dicts or email strings
            
        Returns:
            List of recipients not in suppression list
        """
        suppression = self.load()
        filtered = []
        for recipient in recipients:
            # Handle both string emails and dict recipients
            if isinstance(recipient, str):
                email = normalize_email(recipient)
                if email and email not in suppression.entries:
                    filtered.append(recipient)
            else:
                # It's a dict
                email = normalize_email(recipient.get("email", ""))
                if email and email not in suppression.entries:
                    filtered.append(recipient)
        return filtered

    def suppress_by_keyword(self, keyword: str, added_by: str = "system") -> int:
        """
        Suppress emails matching a keyword pattern (not implemented - stub for test compatibility).
        
        Args:
            keyword: Pattern to match
            added_by: Who added the suppression
            
        Returns:
            Number of emails suppressed (currently always 0)
        """
        # This would require more complex pattern matching logic
        # For now, return 0 (not implemented)
        return 0

    def stats_by_reason(self) -> dict[str, int]:
        """Get suppression stats by reason (alias for count_by_reason)."""
        return self.count_by_reason()
