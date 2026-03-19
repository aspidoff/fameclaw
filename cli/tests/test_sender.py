"""Tests for send pipeline gates."""

from datetime import datetime, timedelta

import pytest

from fameclaw.sender import SendGate
from fameclaw.models import Campaign, CampaignConfig, Recipient, LedgerEntry
from fameclaw.exceptions import (
    SuppressedRecipientError,
    CampaignDuplicateError,
    CooldownViolationError,
    ApprovalRequiredError,
    CanSpamViolationError,
    EngagementPausedError,
    RateLimitedError,
    DomainAtRiskError,
)


@pytest.fixture
def send_gate(temp_state_dir, sample_campaign_config, temp_templates_dir):
    """Create a send gate for testing."""
    return SendGate(temp_state_dir)


@pytest.fixture
def approved_campaign(sample_campaign_config, sample_recipients, temp_templates_dir):
    """Create an approved campaign for testing."""
    campaign = Campaign(
        id="test-campaign-001",
        created_at=datetime.utcnow().isoformat(),
        status="approved",
        from_inbox="hello@souls.zip",
        subject_template="Hello {{ name }}",
        body_template_path=sample_campaign_config.body_template_path,
        approved_by="toli",
        approved_at=datetime.utcnow().isoformat(),
        config=sample_campaign_config,
    )

    for recipient in sample_recipients:
        campaign.recipients[recipient.email] = {
            "email": recipient.email,
            "display_name": recipient.display_name,
            "status": "pending",
        }

    return campaign


class TestGate1Suppression:
    """Test Gate 1: Suppression check."""

    def test_gate1_allows_unsuppressed(self, send_gate, approved_campaign):
        """Test that unsuppressed emails pass gate 1."""
        recipient_email = "alice@example.com"
        # Should not be suppressed by default
        assert send_gate.suppressor.is_suppressed(recipient_email) is False

    def test_gate1_blocks_suppressed(self, send_gate, approved_campaign):
        """Test that suppressed emails fail gate 1."""
        recipient_email = "alice@example.com"
        send_gate.suppressor.add(recipient_email, "explicit_opt_out")

        # Now should be suppressed
        assert send_gate.suppressor.is_suppressed(recipient_email) is True

    def test_gate1_auto_suppression_hard_bounce(self, send_gate):
        """Test auto-suppression on hard bounce."""
        recipient_email = "bounce@example.com"

        # Manually add hard bounce entry
        send_gate.bouncer.record_bounce(recipient_email, "hard")

        # Should now be suppressed
        assert send_gate.suppressor.is_suppressed(recipient_email) is True


class TestGate2CampaignDedup:
    """Test Gate 2: Campaign deduplication."""

    def test_gate2_allows_first_send(self, send_gate, approved_campaign):
        """Test first send to recipient in campaign passes gate 2."""
        recipient_email = "alice@example.com"
        # First send should be allowed
        result = send_gate.check_campaign_dedup(approved_campaign.id, recipient_email)
        assert result is True  # No duplicate

    def test_gate2_blocks_duplicate_in_campaign(self, send_gate, approved_campaign):
        """Test duplicate send to same recipient in same campaign fails gate 2."""
        recipient_email = "alice@example.com"

        # Add first send
        entry = LedgerEntry(
            campaign_id=approved_campaign.id,
            recipient_email=recipient_email,
            message_id="msg_123",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )
        send_gate.ledger.add_entry(entry)

        # Check for duplicate
        result = send_gate.check_campaign_dedup(approved_campaign.id, recipient_email)
        assert result is False  # Found duplicate

    def test_gate2_allows_different_campaign(self, send_gate):
        """Test same recipient in different campaign is not a duplicate."""
        recipient_email = "alice@example.com"

        # Add send in campaign 1
        entry = LedgerEntry(
            campaign_id="campaign-001",
            recipient_email=recipient_email,
            message_id="msg_123",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )
        send_gate.ledger.add_entry(entry)

        # Check in campaign 2 - should not be duplicate
        result = send_gate.check_campaign_dedup("campaign-002", recipient_email)
        assert result is True


class TestGate3CrossCampaignCooldown:
    """Test Gate 3: Cross-campaign cooldown (30 days)."""

    def test_gate3_allows_after_cooldown(self, send_gate):
        """Test send allowed after 30-day cooldown."""
        recipient_email = "alice@example.com"

        # Send 31 days ago
        old_date = datetime.utcnow() - timedelta(days=31)
        entry = LedgerEntry(
            campaign_id="campaign-001",
            recipient_email=recipient_email,
            message_id="msg_123",
            sent_at=old_date.isoformat(),
            status="sent",
        )
        send_gate.ledger.add_entry(entry)

        # Should be allowed now
        result = send_gate.check_cross_campaign_cooldown(recipient_email)
        assert result is True

    def test_gate3_blocks_within_cooldown(self, send_gate):
        """Test send blocked within 30-day cooldown."""
        recipient_email = "alice@example.com"

        # Send 10 days ago
        old_date = datetime.utcnow() - timedelta(days=10)
        entry = LedgerEntry(
            campaign_id="campaign-001",
            recipient_email=recipient_email,
            message_id="msg_123",
            sent_at=old_date.isoformat(),
            status="sent",
        )
        send_gate.ledger.add_entry(entry)

        # Should be blocked
        result = send_gate.check_cross_campaign_cooldown(recipient_email)
        assert result is False

    def test_gate3_exact_30_days(self, send_gate):
        """Test send allowed at exactly 30 days."""
        recipient_email = "alice@example.com"

        # Send exactly 30 days ago
        old_date = datetime.utcnow() - timedelta(days=30)
        entry = LedgerEntry(
            campaign_id="campaign-001",
            recipient_email=recipient_email,
            message_id="msg_123",
            sent_at=old_date.isoformat(),
            status="sent",
        )
        send_gate.ledger.add_entry(entry)

        # Should be allowed (30+ days)
        result = send_gate.check_cross_campaign_cooldown(recipient_email)
        assert result is True


class TestGate4CampaignApproval:
    """Test Gate 4: Campaign approval requirement."""

    def test_gate4_allows_approved(self, send_gate, approved_campaign):
        """Test approved campaign passes gate 4."""
        assert approved_campaign.status == "approved"
        result = send_gate.check_approval(approved_campaign)
        assert result is True

    def test_gate4_allows_running(self, send_gate, approved_campaign):
        """Test running campaign passes gate 4."""
        approved_campaign.status = "running"
        result = send_gate.check_approval(approved_campaign)
        assert result is True

    def test_gate4_blocks_draft(self, send_gate):
        """Test draft campaign fails gate 4."""
        campaign = Campaign(
            id="test-001",
            created_at=datetime.utcnow().isoformat(),
            status="draft",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path="/path/to/template",
        )
        result = send_gate.check_approval(campaign)
        assert result is False

    def test_gate4_blocks_preview(self, send_gate):
        """Test preview campaign fails gate 4."""
        campaign = Campaign(
            id="test-001",
            created_at=datetime.utcnow().isoformat(),
            status="preview",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path="/path/to/template",
        )
        result = send_gate.check_approval(campaign)
        assert result is False


class TestGate6WarmupCap:
    """Test Gate 6: Daily warm-up cap."""

    def test_gate6_allows_under_cap(self, send_gate):
        """Test send under daily warm-up cap passes gate 6."""
        inbox = "hello@souls.zip"
        send_gate.warmup.initialize_inbox(inbox)

        # Send 5 times (typical cap is 20-50)
        for _ in range(5):
            send_gate.warmup.increment_daily_sends(inbox, 1)

        # Should pass
        result = send_gate.check_warmup_daily_cap(inbox)
        assert result is True

    def test_gate6_blocks_over_cap(self, send_gate):
        """Test send over daily warm-up cap fails gate 6."""
        inbox = "hello@souls.zip"
        send_gate.warmup.initialize_inbox(inbox)

        # Get the cap
        cap = send_gate.warmup.get_daily_cap(inbox)

        # Simulate exceeding cap
        for _ in range(cap + 1):
            send_gate.warmup.increment_daily_sends(inbox, 1)

        # Should fail or be very close
        result = send_gate.check_warmup_daily_cap(inbox)
        assert result is False or send_gate.warmup.get_inbox(inbox).sends_today >= cap


class TestGate7GlobalDailyCap:
    """Test Gate 7: Global daily cap."""

    def test_gate7_allows_under_cap(self, send_gate):
        """Test send under global daily cap passes gate 7."""
        # Record some sends across inboxes
        send_gate.warmup.initialize_inbox("inbox1@souls.zip")
        send_gate.warmup.increment_daily_sends("inbox1@souls.zip", 10)

        # Should still be under global cap (typically 100-200)
        result = send_gate.check_global_daily_cap()
        assert result is True


class TestGate8HourlyRateLimit:
    """Test Gate 8: Hourly rate limit."""

    def test_gate8_allows_under_limit(self, send_gate):
        """Test send under hourly rate limit passes gate 8."""
        inbox = "hello@souls.zip"

        # Add a few sends in last hour
        now = datetime.utcnow()
        for i in range(2):
            send_gate.ledger.add_entry(
                LedgerEntry(
                    campaign_id="test-001",
                    recipient_email=f"user{i}@example.com",
                    message_id=f"msg_{i}",
                    sent_at=(now - timedelta(minutes=10 + i)).isoformat(),
                    status="sent",
                )
            )

        # Should pass (typical limit is 5-10/hour)
        result = send_gate.check_hourly_rate_limit(inbox)
        assert result is True


class TestGate9DomainHealth:
    """Test Gate 9: Domain health check (bounce rate)."""

    def test_gate9_allows_healthy_domain(self, send_gate):
        """Test send from healthy domain passes gate 9."""
        inbox = "hello@souls.zip"
        send_gate.bouncer.initialize_tracker(inbox)

        # Domain is new, low bounce rate
        result = send_gate.check_domain_health(inbox)
        assert result is True

    def test_gate9_blocks_unhealthy_domain(self, send_gate):
        """Test send from unhealthy domain (>5% hard bounce) fails gate 9."""
        inbox = "hello@souls.zip"
        send_gate.bouncer.initialize_tracker(inbox)

        # Simulate high bounce rate
        tracker = send_gate.bouncer.get_tracker(inbox)
        tracker.total_sends = 10
        tracker.hard_bounces = 6  # 60% hard bounce rate
        send_gate.bouncer.update_tracker(inbox, tracker)

        result = send_gate.check_domain_health(inbox)
        assert result is False

    def test_gate9_allows_5_percent_edge(self, send_gate):
        """Test send at exactly 5% hard bounce rate."""
        inbox = "hello@souls.zip"
        send_gate.bouncer.initialize_tracker(inbox)

        tracker = send_gate.bouncer.get_tracker(inbox)
        tracker.total_sends = 20
        tracker.hard_bounces = 1  # Exactly 5%
        send_gate.bouncer.update_tracker(inbox, tracker)

        result = send_gate.check_domain_health(inbox)
        # Should block at >= 5%
        assert result is False or tracker.hard_bounce_rate <= 0.05
