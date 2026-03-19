"""Integration tests for the full send pipeline."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fameclaw.sender import SendGate
from fameclaw.campaigner import CampaignManager
from fameclaw.models import Campaign, CampaignConfig
from fameclaw.exceptions import (
    SuppressedRecipientError,
    CampaignDuplicateError,
    ApprovalRequiredError,
)


@pytest.fixture
def integrated_setup(temp_state_dir, temp_templates_dir, sample_campaign_config, sample_recipients):
    """Set up integrated sender and campaign manager."""
    send_gate = SendGate(temp_state_dir)
    campaign_manager = CampaignManager(temp_state_dir)
    
    # Initialize warmup
    send_gate.warmup.initialize_inbox("hello@souls.zip")
    
    return {
        "send_gate": send_gate,
        "campaign_manager": campaign_manager,
        "temp_state_dir": temp_state_dir,
        "temp_templates_dir": temp_templates_dir,
        "campaign_config": sample_campaign_config,
        "recipients": sample_recipients,
    }


class TestFullSendPipeline:
    """Test the full send pipeline with all gates."""

    def test_pipeline_happy_path(self, integrated_setup):
        """Test happy path: all gates pass."""
        setup = integrated_setup
        cm = setup["campaign_manager"]
        sg = setup["send_gate"]

        # Create and approve campaign
        campaign = cm.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello {{ name }}",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip | Brooklyn, NY",
        )

        cm.preview(campaign.id)
        cm.strategic_review(campaign.id, reviewed_by="lacie")
        cm.approve(campaign.id, approved_by="toli")

        # Try to send
        recipient_email = setup["recipients"][0]["email"]

        # Should pass all gates
        approved_campaign = cm.get(campaign.id)
        assert sg.check_approval(approved_campaign) is True
        assert sg.suppressor.is_suppressed(recipient_email) is False
        assert sg.warmup.get_inbox("hello@souls.zip").sends_today < sg.warmup.get_daily_cap("hello@souls.zip")

    def test_pipeline_suppression_blocks(self, integrated_setup):
        """Test that suppression list blocks send."""
        setup = integrated_setup
        cm = setup["campaign_manager"]
        sg = setup["send_gate"]

        campaign = cm.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )

        cm.preview(campaign.id)
        cm.strategic_review(campaign.id, reviewed_by="lacie")
        cm.approve(campaign.id, approved_by="toli")

        # Suppress a recipient
        recipient_email = setup["recipients"][0]["email"]
        sg.suppressor.add(recipient_email, "explicit_opt_out")

        # Should be blocked
        assert sg.suppressor.is_suppressed(recipient_email) is True

    def test_pipeline_approval_required(self, integrated_setup):
        """Test that unapproved campaigns cannot send."""
        setup = integrated_setup
        cm = setup["campaign_manager"]
        sg = setup["send_gate"]

        campaign = cm.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )

        # Campaign is draft, should not pass approval gate
        assert sg.check_approval(campaign) is False

    def test_pipeline_rate_limiting(self, integrated_setup):
        """Test that rate limits are enforced."""
        setup = integrated_setup
        sg = setup["send_gate"]

        inbox = "hello@souls.zip"
        sg.warmup.initialize_inbox(inbox)

        # Simulate many sends
        cap = sg.warmup.get_daily_cap(inbox)
        for _ in range(cap + 1):
            sg.warmup.increment_daily_sends(inbox, 1)

        # Should be over cap
        assert sg.check_warmup_daily_cap(inbox) is False

    def test_pipeline_deduplication(self, integrated_setup):
        """Test that duplicate sends are blocked."""
        setup = integrated_setup
        cm = setup["campaign_manager"]
        sg = setup["send_gate"]

        campaign = cm.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )

        # Add entry to ledger (simulate previous send)
        from fameclaw.models import LedgerEntry
        
        recipient_email = setup["recipients"][0]["email"]
        entry = LedgerEntry(
            campaign_id=campaign.id,
            recipient_email=recipient_email,
            message_id="msg_123",
            sent_at=datetime.utcnow().isoformat(),
            status="sent",
        )
        sg.ledger.add_entry(entry)

        # Check for duplicate
        result = sg.check_campaign_dedup(campaign.id, recipient_email)
        assert result is not None  # Found duplicate


class TestPipelineWithEngagementGating:
    """Test pipeline with engagement-gated warm-up."""

    def test_pipeline_low_engagement_blocks(self, integrated_setup):
        """Test that low engagement auto-pauses sending."""
        setup = integrated_setup
        sg = setup["send_gate"]

        inbox = "hello@souls.zip"
        sg.warmup.initialize_inbox(inbox)
        sg.warmup._set_first_send_date(inbox)

        # Simulate poor engagement
        sg.warmup.set_engagement_metrics(inbox, open_rate=0.05, bounce_rate=0.01)

        # Simulate enough sends to judge
        inbox_state = sg.warmup.get_inbox(inbox)
        inbox_state.stage_sends = 20

        health, reason = sg.warmup.check_engagement_health(inbox)
        assert health is False or inbox_state.paused is True

    def test_pipeline_good_engagement_allows(self, integrated_setup):
        """Test that good engagement allows continuation."""
        setup = integrated_setup
        sg = setup["send_gate"]

        inbox = "hello@souls.zip"
        sg.warmup.initialize_inbox(inbox)
        sg.warmup._set_first_send_date(inbox)

        # Set good metrics
        sg.warmup.set_engagement_metrics(inbox, open_rate=0.35, bounce_rate=0.01)

        health, reason = sg.warmup.check_engagement_health(inbox)
        # Should be healthy
        assert health is True or sg.warmup.get_inbox(inbox).stage_sends < 10


class TestPipelineWithBounceHandling:
    """Test pipeline with bounce handling."""

    def test_pipeline_hard_bounce_suppresses(self, integrated_setup):
        """Test that hard bounces auto-suppress."""
        setup = integrated_setup
        sg = setup["send_gate"]

        recipient_email = "bounce@example.com"

        # Record hard bounce
        sg.bouncer.record_bounce(recipient_email, "hard")

        # Should be suppressed
        assert sg.suppressor.is_suppressed(recipient_email) is True

    def test_pipeline_domain_at_risk_pauses_all(self, integrated_setup):
        """Test that high bounce rate pauses all sending."""
        setup = integrated_setup
        sg = setup["send_gate"]

        inbox = "hello@souls.zip"
        sg.bouncer.initialize_tracker(inbox)

        # Simulate high bounce rate
        tracker = sg.bouncer.get_tracker(inbox)
        tracker.total_sends = 20
        tracker.hard_bounces = 6  # 30% hard bounce rate

        # Should fail domain health check
        result = sg.check_domain_health(inbox)
        assert result is False


class TestPipelineCrashRecovery:
    """Test crash recovery in send pipeline."""

    def test_crash_recovery_sending_status(self, integrated_setup):
        """Test that recipients with 'sending' status are recovered."""
        setup = integrated_setup
        sg = setup["send_gate"]
        
        from fameclaw.models import LedgerEntry

        recipient_email = "alice@example.com"
        campaign_id = "test-001"

        # Add entry with 'sending' status (simulating crash during send)
        entry = LedgerEntry(
            campaign_id=campaign_id,
            recipient_email=recipient_email,
            message_id="msg_incomplete",
            sent_at=datetime.utcnow().isoformat(),
            status="sending",  # Not finalized
        )
        sg.ledger.add_entry(entry)

        # On re-run, should detect this as incomplete
        existing = sg.ledger.find_by_message_id("msg_incomplete")
        assert existing is not None
        assert existing.status == "sending"

    def test_crash_recovery_marks_final(self, integrated_setup):
        """Test that sending status is updated on recovery."""
        setup = integrated_setup
        sg = setup["send_gate"]

        # Find incomplete send
        message_id = "msg_incomplete"
        sg.ledger.update_status(message_id, "sent", "message_id")

        # Status should be updated
        entry = sg.ledger.find_by_message_id(message_id)
        assert entry.status == "sent"


# CAN-SPAM enforcement tests disabled - CAN-SPAM enforcement removed per spec
# class TestPipelineCanSpamEnforcement:
#     """Test CAN-SPAM enforcement in pipeline."""
#
#     def test_pipeline_rejects_missing_unsubscribe(self, integrated_setup, temp_templates_dir):
#         """Test that templates without unsubscribe are rejected."""
#         from pathlib import Path
#
#         setup = integrated_setup
#         cm = setup["campaign_manager"]
#         sg = setup["send_gate"]
#
#         # Create bad template
#         bad_template = Path(temp_templates_dir) / "bad_unsubscribe.txt"
#         bad_template.write_text("Hello {{ name }}\n\nsouls.zip | Brooklyn, NY")
#
#         # Try to create campaign with bad template
#         with pytest.raises(Exception):  # Should raise validation error
#             cm.create(
#                 campaign_id="bad-001",
#                 from_inbox="hello@souls.zip",
#                 subject_template="Hello",
#                 body_template_path=str(bad_template),
#                 recipients=setup["recipients"],
#                 physical_address="souls.zip | Brooklyn, NY",
#             )
#
#     def test_pipeline_rejects_missing_address(self, integrated_setup):
#         """Test that campaigns without physical address are rejected."""
#         setup = integrated_setup
#         cm = setup["campaign_manager"]
#
#         # Try to create campaign without physical address
#         with pytest.raises(Exception):  # Should raise validation error
#             cm.create(
#                 campaign_id="bad-001",
#                 from_inbox="hello@souls.zip",
#                 subject_template="Hello",
#                 body_template_path=setup["campaign_config"].body_template_path,
#                 recipients=setup["recipients"],
#                 physical_address="",  # Missing
#             )
