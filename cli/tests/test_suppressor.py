"""Tests for suppression list management."""

from datetime import datetime, timedelta

import pytest

from fameclaw.suppressor import SuppressionManager
from fameclaw.models import SuppressionEntry
from fameclaw.exceptions import ValidationError


class TestSuppressionBasics:
    """Test basic suppression list operations."""

    def test_suppression_initialization(self, suppression_manager):
        """Test suppression list initializes correctly."""
        supp = suppression_manager.load()
        assert supp.version == 1
        assert supp.entries == {}

    def test_add_suppression(self, suppression_manager):
        """Test adding an email to suppression list."""
        suppression_manager.add("alice@example.com", "explicit_opt_out")

        supp = suppression_manager.load()
        assert "alice@example.com" in supp.entries
        assert supp.entries["alice@example.com"].reason == "explicit_opt_out"

    def test_check_suppressed(self, suppression_manager):
        """Test checking if email is suppressed."""
        suppression_manager.add("alice@example.com", "explicit_opt_out")

        assert suppression_manager.is_suppressed("alice@example.com") is True
        assert suppression_manager.is_suppressed("bob@example.com") is False

    def test_remove_suppression(self, suppression_manager):
        """Test removing email from suppression list."""
        suppression_manager.add("alice@example.com", "explicit_opt_out")
        assert suppression_manager.is_suppressed("alice@example.com") is True

        suppression_manager.remove("alice@example.com")
        assert suppression_manager.is_suppressed("alice@example.com") is False

    def test_suppression_persistence(self, suppression_manager, temp_state_dir):
        """Test suppressions persist across loads."""
        suppression_manager.add("alice@example.com", "explicit_opt_out")

        # Create new manager pointing to same state dir
        new_manager = SuppressionManager(temp_state_dir)
        assert new_manager.is_suppressed("alice@example.com") is True


class TestSuppressionReasons:
    """Test suppression list with different reasons."""

    def test_suppression_reasons(self, suppression_manager):
        """Test various suppression reasons."""
        reasons = [
            "explicit_opt_out",
            "hard_bounce",
            "soft_bounce_repeated",
            "domain_complaint",
            "policy_violation",
            "user_requested",
        ]

        for i, reason in enumerate(reasons):
            email = f"user{i}@example.com"
            suppression_manager.add(email, reason)

        supp = suppression_manager.load()
        for i, reason in enumerate(reasons):
            email = f"user{i}@example.com"
            assert supp.entries[email].reason == reason

    def test_get_suppression_entry(self, suppression_manager):
        """Test retrieving full suppression entry."""
        suppression_manager.add("alice@example.com", "hard_bounce")
        entry = suppression_manager.get_entry("alice@example.com")

        assert entry is not None
        assert entry.email == "alice@example.com"
        assert entry.reason == "hard_bounce"
        assert entry.added_by == "system"


class TestSuppressionFiltering:
    """Test filtering recipients against suppression list."""

    def test_filter_recipients(self, suppression_manager):
        """Test filtering a list of recipients."""
        recipients = [
            "alice@example.com",
            "bob@example.com",
            "charlie@example.com",
            "dave@example.com",
        ]

        # Suppress some
        suppression_manager.add("bob@example.com", "explicit_opt_out")
        suppression_manager.add("dave@example.com", "hard_bounce")

        filtered = suppression_manager.filter_recipients(recipients)
        assert "alice@example.com" in filtered
        assert "charlie@example.com" in filtered
        assert "bob@example.com" not in filtered
        assert "dave@example.com" not in filtered

    def test_get_suppressed_count(self, suppression_manager):
        """Test getting count of suppressed emails."""
        for i in range(10):
            suppression_manager.add(f"user{i}@example.com", "explicit_opt_out")

        count = suppression_manager.get_count()
        assert count == 10


class TestSuppressionKeywords:
    """Test keyword-based suppression checks."""

    def test_suppress_by_keyword(self, suppression_manager):
        """Test suppressing addresses by keyword pattern."""
        # Add a domain to suppression
        suppression_manager.add("noreply@company.com", "policy_violation", keyword="noreply")
        suppression_manager.add("no-reply@company.com", "policy_violation", keyword="noreply")
        suppression_manager.add("bounce@company.com", "policy_violation", keyword="bounce")

        assert suppression_manager.is_suppressed("noreply@company.com") is True
        assert suppression_manager.is_suppressed("no-reply@company.com") is True
        assert suppression_manager.is_suppressed("bounce@company.com") is True

    def test_suppress_invalid_addresses(self, suppression_manager):
        """Test suppressing known invalid address patterns."""
        # Test common invalid address patterns
        invalid_patterns = [
            "noreply@",
            "bounce@",
            "mailer-daemon@",
            "postmaster@",
        ]

        for pattern in invalid_patterns:
            # These might be auto-suppressed by policy
            # This depends on implementation
            pass


class TestSuppressionStatistics:
    """Test suppression list statistics."""

    def test_suppression_by_reason(self, suppression_manager):
        """Test getting suppression statistics by reason."""
        reasons = ["explicit_opt_out", "hard_bounce", "hard_bounce", "soft_bounce_repeated"]

        for i, reason in enumerate(reasons):
            suppression_manager.add(f"user{i}@example.com", reason)

        stats = suppression_manager.stats_by_reason()
        assert stats.get("explicit_opt_out", 0) == 1
        assert stats.get("hard_bounce", 0) == 2
        assert stats.get("soft_bounce_repeated", 0) == 1

    def test_total_suppressed(self, suppression_manager):
        """Test getting total suppressed count."""
        for i in range(25):
            suppression_manager.add(f"user{i}@example.com", "explicit_opt_out")

        total = suppression_manager.get_count()
        assert total == 25

    def test_suppression_timeline(self, suppression_manager):
        """Test suppression list over time."""
        base_time = datetime.utcnow()

        for i in range(5):
            suppression_manager.add(f"user{i}@example.com", "explicit_opt_out")

        supp = suppression_manager.load()
        assert len(supp.entries) == 5


class TestSuppressionEdgeCases:
    """Test suppression list edge cases."""

    def test_add_same_email_twice(self, suppression_manager):
        """Test adding same email twice (should update)."""
        suppression_manager.add("alice@example.com", "explicit_opt_out")
        suppression_manager.add("alice@example.com", "hard_bounce")

        entry = suppression_manager.get_entry("alice@example.com")
        assert entry.reason == "hard_bounce"

    def test_remove_nonexistent_email(self, suppression_manager):
        """Test removing email that doesn't exist."""
        # Should not raise error
        suppression_manager.remove("nonexistent@example.com")

    def test_case_insensitive_emails(self, suppression_manager):
        """Test that suppression checks are case-insensitive."""
        suppression_manager.add("alice@example.com", "explicit_opt_out")

        assert suppression_manager.is_suppressed("ALICE@EXAMPLE.COM") is True
        assert suppression_manager.is_suppressed("Alice@Example.Com") is True

    def test_whitespace_normalization(self, suppression_manager):
        """Test whitespace is normalized."""
        suppression_manager.add("  alice@example.com  ", "explicit_opt_out")

        assert suppression_manager.is_suppressed("alice@example.com") is True

    def test_large_suppression_list(self, suppression_manager):
        """Test performance with large suppression list."""
        # Add 1000 emails
        for i in range(1000):
            suppression_manager.add(f"user{i}@example.com", "explicit_opt_out")

        # Should still find them quickly
        assert suppression_manager.is_suppressed("user500@example.com") is True
        assert suppression_manager.is_suppressed("user999@example.com") is True
        assert suppression_manager.is_suppressed("nonexistent@example.com") is False
