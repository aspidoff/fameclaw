"""Tests for ledger module."""

from datetime import datetime
from pathlib import Path

import pytest

from fameclaw.ledger import LedgerManager
from fameclaw.models import LedgerEntry


class TestLedgerCRUD:
    """Test ledger CRUD operations."""

    def test_ledger_initialization(self, ledger_manager):
        """Test ledger initializes correctly."""
        ledger = ledger_manager.load()
        assert ledger.version == 1
        assert ledger.entries == []

    def test_add_entry(self, ledger_manager):
        """Test adding an entry to ledger."""
        entry = LedgerEntry(
            campaign_id="test-001",
            recipient_email="alice@example.com",
            message_id="msg_123",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )

        ledger_manager.add_entry(entry)
        ledger = ledger_manager.load()

        assert len(ledger.entries) == 1
        assert ledger.entries[0].campaign_id == "test-001"
        assert ledger.entries[0].recipient_email == "alice@example.com"

    def test_add_multiple_entries(self, ledger_manager):
        """Test adding multiple entries."""
        for i in range(5):
            entry = LedgerEntry(
                campaign_id="test-001",
                recipient_email=f"user{i}@example.com",
                message_id=f"msg_{i}",
                sent_at=datetime.utcnow().isoformat(),
                status="sent",
            )
            ledger_manager.add_entry(entry)

        ledger = ledger_manager.load()
        assert len(ledger.entries) == 5

    def test_update_status(self, ledger_manager):
        """Test updating entry status."""
        entry = LedgerEntry(
            campaign_id="test-001",
            recipient_email="alice@example.com",
            message_id="msg_123",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )
        ledger_manager.add_entry(entry)

        ledger_manager.update_status("msg_123", "bounced_hard", "message_id")
        ledger = ledger_manager.load()

        assert ledger.entries[0].status == "bounced_hard"

    def test_entry_persistence(self, ledger_manager):
        """Test entries persist across loads."""
        entry = LedgerEntry(
            campaign_id="test-001",
            recipient_email="alice@example.com",
            message_id="msg_123",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )
        ledger_manager.add_entry(entry)

        # Create new manager pointing to same state dir
        new_manager = LedgerManager(ledger_manager.state_dir)
        ledger = new_manager.load()

        assert len(ledger.entries) == 1
        assert ledger.entries[0].recipient_email == "alice@example.com"


class TestLedgerDeduplication:
    """Test ledger deduplication logic."""

    def test_duplicate_detection_same_message_id(self, ledger_manager):
        """Test duplicate detection by message ID."""
        entry1 = LedgerEntry(
            campaign_id="test-001",
            recipient_email="alice@example.com",
            message_id="msg_123",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )
        ledger_manager.add_entry(entry1)

        # Try adding same message_id
        entry2 = LedgerEntry(
            campaign_id="test-001",
            recipient_email="alice@example.com",
            message_id="msg_123",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )

        # Should not add duplicate
        result = ledger_manager.is_duplicate(entry2)
        assert result is not None  # Found existing
        assert result.message_id == "msg_123"

    def test_duplicate_detection_same_recipient_campaign(self, ledger_manager):
        """Test duplicate detection by campaign + recipient."""
        entry1 = LedgerEntry(
            campaign_id="test-001",
            recipient_email="alice@example.com",
            message_id="msg_123",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )
        ledger_manager.add_entry(entry1)

        # Same campaign, same recipient
        entry2 = LedgerEntry(
            campaign_id="test-001",
            recipient_email="alice@example.com",
            message_id="msg_456",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )

        # Should detect duplicate in same campaign
        result = ledger_manager.is_duplicate(entry2)
        assert result is not None

    def test_no_duplicate_different_campaign(self, ledger_manager):
        """Test no false positives across campaigns."""
        entry1 = LedgerEntry(
            campaign_id="test-001",
            recipient_email="alice@example.com",
            message_id="msg_123",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )
        ledger_manager.add_entry(entry1)

        # Different campaign, same recipient
        entry2 = LedgerEntry(
            campaign_id="test-002",
            recipient_email="alice@example.com",
            message_id="msg_456",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )

        # Should NOT be a duplicate (different campaign)
        result = ledger_manager.is_duplicate(entry2)
        assert result is None

    def test_no_duplicate_different_recipient(self, ledger_manager):
        """Test no false positives for different recipients."""
        entry1 = LedgerEntry(
            campaign_id="test-001",
            recipient_email="alice@example.com",
            message_id="msg_123",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )
        ledger_manager.add_entry(entry1)

        # Same campaign, different recipient
        entry2 = LedgerEntry(
            campaign_id="test-001",
            recipient_email="bob@example.com",
            message_id="msg_456",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )

        # Should NOT be a duplicate
        result = ledger_manager.is_duplicate(entry2)
        assert result is None


class TestLedgerReverseIndex:
    """Test ledger reverse indexing."""

    def test_reverse_index_by_message_id(self, ledger_manager):
        """Test finding entry by message ID."""
        entry = LedgerEntry(
            campaign_id="test-001",
            recipient_email="alice@example.com",
            message_id="msg_123",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )
        ledger_manager.add_entry(entry)

        found = ledger_manager.find_by_message_id("msg_123")
        assert found is not None
        assert found.recipient_email == "alice@example.com"

    def test_reverse_index_by_email(self, ledger_manager):
        """Test finding entries by email."""
        for i in range(3):
            entry = LedgerEntry(
                campaign_id="test-001",
                recipient_email="alice@example.com",
                message_id=f"msg_{i}",
                sent_at=datetime.utcnow().isoformat(),
                status="sent",
            )
            ledger_manager.add_entry(entry)

        found = ledger_manager.find_by_email("alice@example.com")
        assert len(found) == 3
        assert all(e.recipient_email == "alice@example.com" for e in found)

    def test_reverse_index_by_campaign(self, ledger_manager):
        """Test finding entries by campaign."""
        for i in range(2):
            entry = LedgerEntry(
                campaign_id="test-001",
                recipient_email=f"user{i}@example.com",
                message_id=f"msg_{i}",
                sent_at=datetime.utcnow().isoformat(),
                status="sent",
            )
            ledger_manager.add_entry(entry)

        found = ledger_manager.find_by_campaign("test-001")
        assert len(found) == 2
        assert all(e.campaign_id == "test-001" for e in found)

    def test_reverse_index_by_status(self, ledger_manager):
        """Test finding entries by status."""
        statuses = ["sent", "bounced_hard", "sent", "opened"]
        for i, status in enumerate(statuses):
            entry = LedgerEntry(
                campaign_id="test-001",
                recipient_email=f"user{i}@example.com",
                message_id=f"msg_{i}",
                sent_at=datetime.utcnow().isoformat(),
                status=status,
            )
            ledger_manager.add_entry(entry)

        bounced = ledger_manager.find_by_status("bounced_hard")
        assert len(bounced) == 1
        assert bounced[0].status == "bounced_hard"

        sent = ledger_manager.find_by_status("sent")
        assert len(sent) == 2


class TestLedgerStats:
    """Test ledger statistics."""

    def test_campaign_stats(self, ledger_manager):
        """Test getting campaign statistics."""
        for i in range(5):
            entry = LedgerEntry(
                campaign_id="test-001",
                recipient_email=f"user{i}@example.com",
                message_id=f"msg_{i}",
                sent_at=datetime.utcnow().isoformat(),
                status="sent" if i < 3 else "bounced_hard",
            )
            ledger_manager.add_entry(entry)

        stats = ledger_manager.campaign_stats("test-001")
        assert stats["total_sent"] == 5
        assert stats["total_bounced"] == 2
        assert stats["total_opened"] == 0
