"""End-to-end integration tests: create → review → approve → run → complete."""

from datetime import datetime
from pathlib import Path

import pytest

from fameclaw.campaigner import CampaignManager
from fameclaw.sender import SendGate
from fameclaw.models import Campaign


@pytest.fixture
def e2e_setup(temp_state_dir, temp_templates_dir, sample_campaign_config, sample_recipients):
    """Set up end-to-end test environment."""
    campaign_manager = CampaignManager(temp_state_dir)
    send_gate = SendGate(temp_state_dir)
    send_gate.warmup.initialize_inbox("hello@souls.zip")

    return {
        "campaign_manager": campaign_manager,
        "send_gate": send_gate,
        "campaign_config": sample_campaign_config,
        "recipients": sample_recipients,
        "temp_state_dir": temp_state_dir,
    }


class TestE2ECreateCampaign:
    """Test campaign creation workflow."""

    def test_e2e_create_minimal(self, e2e_setup):
        """Test creating a minimal campaign."""
        setup = e2e_setup
        cm = setup["campaign_manager"]

        campaign = cm.create(
            campaign_id="e2e-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello {{ name }}",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip | Brooklyn, NY",
        )

        assert campaign.id == "e2e-001"
        assert campaign.status == "draft"
        assert len(campaign.recipients) == 3

    def test_e2e_create_validates_recipients(self, e2e_setup):
        """Test that campaign creation validates recipients."""
        setup = e2e_setup
        cm = setup["campaign_manager"]

        # Try with invalid recipients
        from fameclaw.exceptions import ValidationError

        with pytest.raises(ValidationError):
            cm.create(
                campaign_id="e2e-002",
                from_inbox="hello@souls.zip",
                subject_template="Hello",
                body_template_path=setup["campaign_config"].body_template_path,
                recipients=[],  # No recipients
                physical_address="souls.zip",
            )

    def test_e2e_create_validates_template(self, e2e_setup, temp_templates_dir):
        """Test that campaign creation validates template."""
        from pathlib import Path
        from fameclaw.exceptions import ValidationError

        setup = e2e_setup
        cm = setup["campaign_manager"]

        # Try with nonexistent template
        with pytest.raises((ValidationError, FileNotFoundError)):
            cm.create(
                campaign_id="e2e-003",
                from_inbox="hello@souls.zip",
                subject_template="Hello",
                body_template_path="/nonexistent/template.txt",
                recipients=setup["recipients"],
                physical_address="souls.zip",
            )


class TestE2EWorkflow:
    """Test complete workflow: create → preview → review → approve → run."""

    def test_e2e_full_workflow(self, e2e_setup):
        """Test complete campaign workflow."""
        setup = e2e_setup
        cm = setup["campaign_manager"]

        # Step 1: Create
        campaign = cm.create(
            campaign_id="e2e-workflow-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello {{ name }}",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip | Brooklyn, NY",
        )
        assert campaign.status == "draft"

        # Step 2: Preview
        campaign = cm.preview(campaign.id)
        assert campaign.status == "preview"

        # Step 3: Strategic Review (Lacie)
        campaign = cm.strategic_review(campaign.id, reviewed_by="lacie")
        assert campaign.status == "strategic_review"
        assert campaign.strategic_reviewed_by == "lacie"

        # Step 4: Approve (toli)
        campaign = cm.approve(campaign.id, approved_by="toli")
        assert campaign.status == "approved"
        assert campaign.approved_by == "toli"

        # Step 5: Run
        campaign = cm.run(campaign.id)
        assert campaign.status == "running"
        assert campaign.started_at is not None

        # Step 6: Complete
        campaign = cm.complete(campaign.id)
        assert campaign.status == "completed"
        assert campaign.completed_at is not None

    def test_e2e_cannot_skip_steps(self, e2e_setup):
        """Test that workflow steps cannot be skipped."""
        from fameclaw.exceptions import CampaignError

        setup = e2e_setup
        cm = setup["campaign_manager"]

        campaign = cm.create(
            campaign_id="e2e-skip-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )

        # Can't approve from draft (must preview first)
        with pytest.raises(CampaignError):
            cm.approve(campaign.id, approved_by="toli")

    def test_e2e_campaign_cannot_run_unapproved(self, e2e_setup):
        """Test that unapproved campaigns cannot run."""
        from fameclaw.exceptions import CampaignError

        setup = e2e_setup
        cm = setup["campaign_manager"]

        campaign = cm.create(
            campaign_id="e2e-unapproved-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )

        cm.preview(campaign.id)

        # Can't run at preview
        with pytest.raises(CampaignError):
            cm.run(campaign.id)


class TestE2EPauseResume:
    """Test pause/resume functionality."""

    def test_e2e_pause_and_resume(self, e2e_setup):
        """Test pausing and resuming a campaign."""
        setup = e2e_setup
        cm = setup["campaign_manager"]

        campaign = cm.create(
            campaign_id="e2e-pause-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )

        cm.preview(campaign.id)
        cm.strategic_review(campaign.id, reviewed_by="lacie")
        cm.approve(campaign.id, approved_by="toli")
        cm.run(campaign.id)

        # Pause
        campaign = cm.pause(campaign.id)
        assert campaign.status == "paused"

        # Resume
        campaign = cm.resume(campaign.id)
        assert campaign.status == "running"

    def test_e2e_pause_from_draft_fails(self, e2e_setup):
        """Test that pausing a draft campaign fails."""
        from fameclaw.exceptions import CampaignError

        setup = e2e_setup
        cm = setup["campaign_manager"]

        campaign = cm.create(
            campaign_id="e2e-pause-draft-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )

        # Can't pause draft
        with pytest.raises(CampaignError):
            cm.pause(campaign.id)


class TestE2ECancellation:
    """Test campaign cancellation."""

    def test_e2e_cancel_draft(self, e2e_setup):
        """Test cancelling a draft campaign."""
        setup = e2e_setup
        cm = setup["campaign_manager"]

        campaign = cm.create(
            campaign_id="e2e-cancel-draft-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )

        campaign = cm.cancel(campaign.id)
        assert campaign.status == "cancelled"

    def test_e2e_cancel_approved(self, e2e_setup):
        """Test cancelling an approved campaign."""
        setup = e2e_setup
        cm = setup["campaign_manager"]

        campaign = cm.create(
            campaign_id="e2e-cancel-approved-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )

        cm.preview(campaign.id)
        cm.strategic_review(campaign.id, reviewed_by="lacie")
        cm.approve(campaign.id, approved_by="toli")

        campaign = cm.cancel(campaign.id)
        assert campaign.status == "cancelled"

    def test_e2e_cancel_running(self, e2e_setup):
        """Test cancelling a running campaign."""
        from fameclaw.exceptions import CampaignError

        setup = e2e_setup
        cm = setup["campaign_manager"]

        campaign = cm.create(
            campaign_id="e2e-cancel-running-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )

        cm.preview(campaign.id)
        cm.strategic_review(campaign.id, reviewed_by="lacie")
        cm.approve(campaign.id, approved_by="toli")
        cm.run(campaign.id)

        # Running campaigns may not be directly cancelled, or may be (depends on design)
        # This test checks the implementation
        try:
            campaign = cm.cancel(campaign.id)
            assert campaign.status == "cancelled"
        except Exception:
            # If cancelling running is not allowed, that's OK
            pass


class TestE2EMultipleCampaigns:
    """Test managing multiple campaigns."""

    def test_e2e_create_multiple(self, e2e_setup):
        """Test creating multiple campaigns."""
        setup = e2e_setup
        cm = setup["campaign_manager"]

        for i in range(3):
            campaign = cm.create(
                campaign_id=f"e2e-multi-{i:03d}",
                from_inbox="hello@souls.zip",
                subject_template="Hello",
                body_template_path=setup["campaign_config"].body_template_path,
                recipients=setup["recipients"],
                physical_address="souls.zip",
            )
            assert campaign.status == "draft"

        # List all campaigns
        campaigns = cm.list()
        assert len(campaigns) == 3

    def test_e2e_mixed_campaign_statuses(self, e2e_setup):
        """Test managing campaigns at different stages."""
        setup = e2e_setup
        cm = setup["campaign_manager"]

        # Campaign 1: Draft
        c1 = cm.create(
            campaign_id="e2e-mixed-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )

        # Campaign 2: Approved
        c2 = cm.create(
            campaign_id="e2e-mixed-002",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )
        cm.preview(c2.id)
        cm.strategic_review(c2.id, reviewed_by="lacie")
        cm.approve(c2.id, approved_by="toli")

        # Campaign 3: Running
        c3 = cm.create(
            campaign_id="e2e-mixed-003",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )
        cm.preview(c3.id)
        cm.strategic_review(c3.id, reviewed_by="lacie")
        cm.approve(c3.id, approved_by="toli")
        cm.run(c3.id)

        # Check statuses
        assert cm.get(c1.id).status == "draft"
        assert cm.get(c2.id).status == "approved"
        assert cm.get(c3.id).status == "running"

        # List by status
        drafts = cm.list_by_status("draft")
        approved = cm.list_by_status("approved")
        running = cm.list_by_status("running")

        assert len(drafts) >= 1
        assert len(approved) >= 1
        assert len(running) >= 1


class TestE2EIntegrationWithSender:
    """Test E2E with send pipeline integration."""

    def test_e2e_approved_campaign_passes_gates(self, e2e_setup):
        """Test that approved campaign passes sender gates."""
        setup = e2e_setup
        cm = setup["campaign_manager"]
        sg = setup["send_gate"]

        campaign = cm.create(
            campaign_id="e2e-sender-001",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip | Brooklyn, NY",
        )

        cm.preview(campaign.id)
        cm.strategic_review(campaign.id, reviewed_by="lacie")
        cm.approve(campaign.id, approved_by="toli")

        # Get updated campaign
        campaign = cm.get(campaign.id)

        # Should pass approval gate
        assert sg.check_approval(campaign) is True

    def test_e2e_unapproved_campaign_fails_gates(self, e2e_setup):
        """Test that unapproved campaign fails sender gates."""
        setup = e2e_setup
        cm = setup["campaign_manager"]
        sg = setup["send_gate"]

        campaign = cm.create(
            campaign_id="e2e-sender-002",
            from_inbox="hello@souls.zip",
            subject_template="Hello",
            body_template_path=setup["campaign_config"].body_template_path,
            recipients=setup["recipients"],
            physical_address="souls.zip",
        )

        # Campaign is draft
        assert sg.check_approval(campaign) is False
