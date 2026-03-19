"""Tests for campaign lifecycle management."""

from datetime import datetime
from pathlib import Path

import pytest

from fameclaw.campaigner import CampaignManager
from fameclaw.models import Campaign, CampaignConfig, OutreachConfig
from fameclaw.exceptions import ValidationError, CampaignError


@pytest.fixture
def campaign_manager(temp_state_dir):
    """Create a campaign manager."""
    return CampaignManager(temp_state_dir)


class TestCampaignCreation:
    """Test campaign creation and validation."""

    def test_create_campaign_valid(
        self, campaign_manager, sample_campaign_config, sample_recipients, temp_templates_dir
    ):
        """Test creating a valid campaign."""
        campaign = campaign_manager.create(
            campaign_id="test-campaign-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello {{ name }}",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip | Brooklyn, NY",
        )

        assert campaign.id == "test-campaign-001"
        assert campaign.status == "draft"
        assert len(campaign.recipients) == 3

    def test_create_campaign_invalid_id(self, campaign_manager, sample_campaign_config):
        """Test campaign creation fails with invalid ID."""
        with pytest.raises(ValidationError):
            campaign_manager.create(
                campaign_id="Invalid ID!",
                from_inbox="hello@souls.zip",
                subject_template="Hello",
                body_template_path=sample_campaign_config.body_template_path,
                recipients=[],
                physical_address="souls.zip",
            )

    def test_create_campaign_duplicate_id(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test campaign creation fails with duplicate ID."""
        # Create first campaign
        campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        # Try to create with same ID
        with pytest.raises(ValidationError):
            campaign_manager.create(
                campaign_id="test-001",
                from_inbox="hello@souls.zip",
                subject_template="Hello",
                body_template_path=sample_campaign_config.body_template_path,
                recipients=sample_recipients,
                physical_address="souls.zip",
            )

    # CAN-SPAM enforcement disabled - test no longer applicable
    # def test_create_campaign_missing_can_spam_address(
    #     self, campaign_manager, sample_campaign_config, sample_recipients
    # ):
    #     """Test campaign creation fails without physical address."""
    #     with pytest.raises(ValidationError):
    #         campaign_manager.create(
    #             campaign_id="test-001",
    #             from_inbox="hello@souls.zip",
    #             subject_template="Hello",
    #             body_template_path=sample_campaign_config.body_template_path,
    #             recipients=sample_recipients,
    #             physical_address="",  # Missing
    #         )

    def test_create_campaign_no_duplicates_in_recipients(
        self, campaign_manager, sample_campaign_config
    ):
        """Test campaign creation fails with duplicate recipients."""
        duplicate_recipients = [
            {"email": "alice@example.com", "name": "Alice"},
            {"email": "alice@example.com", "name": "Alice"},  # Duplicate
        ]

        with pytest.raises(ValidationError):
            campaign_manager.create(
                campaign_id="test-001",
                from_inbox="hello@souls.zip",
                subject_template="Hello",
                body_template_path=sample_campaign_config.body_template_path,
                recipients=duplicate_recipients,
                physical_address="souls.zip",
            )


class TestCampaignLifecycle:
    """Test campaign status transitions."""

    def test_status_draft_to_preview(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test transition from draft to preview."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        assert campaign.status == "draft"

        # Transition to preview
        updated = campaign_manager.preview(campaign.id)
        assert updated.status == "preview"

    def test_status_preview_to_strategic_review(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test transition from preview to strategic_review."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        campaign_manager.preview(campaign.id)
        updated = campaign_manager.strategic_review(campaign.id, reviewed_by="lacie")

        assert updated.status == "strategic_review"
        assert updated.strategic_reviewed_by == "lacie"
        assert updated.strategic_reviewed_at is not None

    def test_status_strategic_review_to_approved(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test transition from strategic_review to approved."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        campaign_manager.preview(campaign.id)
        campaign_manager.strategic_review(campaign.id, reviewed_by="lacie")
        updated = campaign_manager.approve(campaign.id, approved_by="toli")

        assert updated.status == "approved"
        assert updated.approved_by == "toli"
        assert updated.approved_at is not None

    def test_status_approved_to_running(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test transition from approved to running."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        campaign_manager.preview(campaign.id)
        campaign_manager.strategic_review(campaign.id, reviewed_by="lacie")
        campaign_manager.approve(campaign.id, approved_by="toli")
        updated = campaign_manager.run(campaign.id)

        assert updated.status == "running"
        assert updated.started_at is not None

    def test_invalid_status_transitions(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test that invalid status transitions are blocked."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        # Can't approve draft (skip preview and review)
        with pytest.raises(CampaignError):
            campaign_manager.approve(campaign.id, approved_by="toli")


class TestTwoStepApproval:
    """Test two-step approval workflow."""

    def test_lacie_strategic_review(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test Lacie's strategic review step."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        campaign_manager.preview(campaign.id)
        reviewed = campaign_manager.strategic_review(campaign.id, reviewed_by="lacie")

        assert reviewed.strategic_reviewed_by == "lacie"
        assert reviewed.strategic_reviewed_at is not None

    def test_toli_final_approval(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test toli's final approval step."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        campaign_manager.preview(campaign.id)
        campaign_manager.strategic_review(campaign.id, reviewed_by="lacie")
        approved = campaign_manager.approve(campaign.id, approved_by="toli")

        assert approved.approved_by == "toli"
        assert approved.approved_at is not None

    def test_cannot_run_without_approval(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test campaign cannot run without full approval."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        campaign_manager.preview(campaign.id)

        # Can't run at preview stage
        with pytest.raises(CampaignError):
            campaign_manager.run(campaign.id)


class TestCampaignPauseResume:
    """Test pausing and resuming campaigns."""

    def test_pause_running_campaign(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test pausing a running campaign."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        campaign_manager.preview(campaign.id)
        campaign_manager.strategic_review(campaign.id, reviewed_by="lacie")
        campaign_manager.approve(campaign.id, approved_by="toli")
        campaign_manager.run(campaign.id)

        paused = campaign_manager.pause(campaign.id)
        assert paused.status == "paused"

    def test_resume_paused_campaign(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test resuming a paused campaign."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        campaign_manager.preview(campaign.id)
        campaign_manager.strategic_review(campaign.id, reviewed_by="lacie")
        campaign_manager.approve(campaign.id, approved_by="toli")
        campaign_manager.run(campaign.id)
        campaign_manager.pause(campaign.id)

        resumed = campaign_manager.resume(campaign.id)
        assert resumed.status == "running"


class TestCampaignCompletion:
    """Test campaign completion."""

    def test_mark_campaign_completed(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test marking campaign as completed."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        campaign_manager.preview(campaign.id)
        campaign_manager.strategic_review(campaign.id, reviewed_by="lacie")
        campaign_manager.approve(campaign.id, approved_by="toli")
        campaign_manager.run(campaign.id)

        completed = campaign_manager.complete(campaign.id)
        assert completed.status == "completed"
        assert completed.completed_at is not None


class TestCampaignCancellation:
    """Test campaign cancellation."""

    def test_cancel_draft_campaign(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test cancelling a draft campaign."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        cancelled = campaign_manager.cancel(campaign.id)
        assert cancelled.status == "cancelled"

    def test_cancel_approved_campaign(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test cancelling an approved campaign."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        campaign_manager.preview(campaign.id)
        campaign_manager.strategic_review(campaign.id, reviewed_by="lacie")
        campaign_manager.approve(campaign.id, approved_by="toli")

        cancelled = campaign_manager.cancel(campaign.id)
        assert cancelled.status == "cancelled"


class TestCampaignRetrieval:
    """Test campaign retrieval and listing."""

    def test_get_campaign_by_id(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test retrieving campaign by ID."""
        campaign = campaign_manager.create(
            campaign_id="test-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=sample_campaign_config.body_template_path,
            recipients=sample_recipients,
            physical_address="souls.zip",
        )

        retrieved = campaign_manager.get(campaign.id)
        assert retrieved.id == campaign.id
        assert retrieved.status == campaign.status

    def test_list_campaigns(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test listing all campaigns."""
        for i in range(3):
            campaign_manager.create(
                campaign_id=f"test-{i:03d}",
                from_inbox="hello@souls.zip",
                subject_template="Hello",
                body_template_path=sample_campaign_config.body_template_path,
                recipients=sample_recipients,
                physical_address="souls.zip",
            )

        campaigns = campaign_manager.list()
        assert len(campaigns) == 3

    def test_list_campaigns_by_status(
        self, campaign_manager, sample_campaign_config, sample_recipients
    ):
        """Test listing campaigns by status."""
        for i in range(2):
            campaign_manager.create(
                campaign_id=f"test-{i:03d}",
                from_inbox="hello@souls.zip",
                subject_template="Hello",
                body_template_path=sample_campaign_config.body_template_path,
                recipients=sample_recipients,
                physical_address="souls.zip",
            )

        drafts = campaign_manager.list_by_status("draft")
        assert len(drafts) == 2
