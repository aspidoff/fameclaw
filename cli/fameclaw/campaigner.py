"""
Campaign lifecycle management with two-step approval workflow.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .exceptions import (
    CampaignNotFound,
    CampaignDuplicateError,
    CanSpamViolationError,
    OutreachError,
)
from .models import Campaign, CampaignConfig, Recipient, OutreachConfig
from .state import StateManager
from .validation import (
    normalize_email,
    validate_campaign_id,
    validate_email,
    validate_recipients,
    validate_can_spam,
)
from .templates import TemplateRenderer
from .sender import Sender


class CampaignManager:
    """Manage campaign lifecycle."""

    CAMPAIGNS_DIR = "campaigns"

    def __init__(self, state_dir: str = "~/.openclaw/outreach", config: Optional[OutreachConfig] = None):
        """Initialize campaign manager."""
        self.state_dir = Path(state_dir).expanduser()
        self.campaigns_dir = self.state_dir / self.CAMPAIGNS_DIR
        self.campaigns_dir.mkdir(parents=True, exist_ok=True)
        self.state_manager = StateManager(state_dir)
        self.config = config or OutreachConfig()
        self.renderer = TemplateRenderer()
        self.sender = Sender(state_dir)

    def _get_campaign_path(self, campaign_id: str) -> Path:
        """Get path to campaign directory."""
        return self.campaigns_dir / campaign_id

    def _get_campaign_file(self, campaign_id: str) -> Path:
        """Get path to campaign metadata file."""
        return self._get_campaign_path(campaign_id) / "campaign.json"

    def _get_recipients_file(self, campaign_id: str) -> Path:
        """Get path to recipients file."""
        return self._get_campaign_path(campaign_id) / "recipients.json"

    def _get_preview_file(self, campaign_id: str) -> Path:
        """Get path to preview markdown."""
        return self._get_campaign_path(campaign_id) / "preview.md"

    def _get_log_file(self, campaign_id: str) -> Path:
        """Get path to campaign log."""
        return self._get_campaign_path(campaign_id) / f"{campaign_id}.log"

    def create(
        self,
        campaign_id: str,
        from_inbox: str,
        subject_template: str,
        body_template_path: str,
        recipients: list[dict],
        hourly_cap: Optional[int] = None,
        physical_address: Optional[str] = None,
    ) -> Campaign:
        """
        Create a new campaign.

        Args:
            campaign_id: Campaign ID (must match ^[a-z0-9_-]{3,50}$)
            from_inbox: From email address
            subject_template: Subject Jinja2 template
            body_template_path: Path to body template file
            recipients: List of recipient dicts
            hourly_cap: Optional hourly send cap
            physical_address: Optional physical address (for CAN-SPAM compliance)

        Returns:
            Created Campaign object

        Raises:
            Various validation errors
        """
        # Validate campaign ID
        if not validate_campaign_id(campaign_id):
            raise ValueError(
                f"Invalid campaign ID: {campaign_id}. "
                f"Must match ^[a-z0-9_-]{{3,50}}$"
            )

        # Check if campaign already exists
        if self._get_campaign_file(campaign_id).exists():
            raise CampaignDuplicateError(f"Campaign {campaign_id} already exists")

        # Validate from_inbox
        from_inbox = normalize_email(from_inbox)
        if not validate_email(from_inbox):
            raise ValueError(f"Invalid from_inbox email: {from_inbox}")

        # Validate body template path
        body_path = Path(body_template_path).expanduser()
        if not body_path.exists():
            raise FileNotFoundError(f"Body template not found: {body_template_path}")

        # Read body template
        with open(body_path, "r") as f:
            body_template = f.read()

        # Validate CAN-SPAM compliance
        violations = validate_can_spam(body_template, self.config)
        if violations:
            raise CanSpamViolationError(
                "CAN-SPAM violations:\n" + "\n".join(violations)
            )

        # Validate recipients
        recipient_errors = validate_recipients(recipients)
        if recipient_errors:
            raise ValueError(f"Invalid recipients:\n" + "\n".join(recipient_errors))

        # Validate template variables
        template_vars = TemplateRenderer._extract_variables(subject_template)
        # body_template is already the file content (read above)
        template_vars.update(TemplateRenderer._extract_variables(body_template))

        for recipient in recipients:
            missing_vars = self.renderer.validate_recipient_has_variables(
                recipient, template_vars
            )
            if missing_vars:
                if isinstance(recipient, dict):
                    email = recipient.get("email", "unknown")
                else:
                    email = getattr(recipient, "email", "unknown")
                raise ValueError(
                    f"Recipient {email} missing variables: {', '.join(missing_vars)}"
                )

        # Create campaign directory
        campaign_path = self._get_campaign_path(campaign_id)
        campaign_path.mkdir(parents=True, exist_ok=True)

        # Create campaign metadata
        now = datetime.utcnow().isoformat() + "Z"
        campaign = Campaign(
            id=campaign_id,
            created_at=now,
            status="draft",
            from_inbox=from_inbox,
            subject_template=subject_template,
            body_template_path=str(body_path),
            config=CampaignConfig(
                from_inbox=from_inbox,
                subject_template=subject_template,
                body_template_path=str(body_path),
                hourly_cap=hourly_cap,
            ),
        )

        # Normalize and save recipients
        for recipient in recipients:
            if isinstance(recipient, dict):
                email = normalize_email(recipient["email"])
                display_name = recipient.get("display_name", "")
                personalization = recipient.get("personalization", {})
            else:
                # Recipient object
                email = normalize_email(recipient.email)
                display_name = getattr(recipient, "display_name", "")
                personalization = getattr(recipient, "personalization", {})
            
            campaign.recipients[email] = Recipient(
                email=email,
                display_name=display_name,
                personalization=personalization,
            )

        self._save_campaign(campaign)

        # Save recipients separately for reference
        recipients_data = {
            email: {
                "email": r.email,
                "display_name": r.display_name,
                "personalization": r.personalization,
            }
            for email, r in campaign.recipients.items()
        }
        recipients_file = self._get_recipients_file(campaign_id)
        with open(recipients_file, "w") as f:
            json.dump(recipients_data, f, indent=2)

        return campaign

    def _save_campaign(self, campaign: Campaign) -> None:
        """Save campaign to file."""
        campaign_file = self._get_campaign_file(campaign.id)
        campaign_data = {
            "id": campaign.id,
            "created_at": campaign.created_at,
            "status": campaign.status,
            "from_inbox": campaign.from_inbox,
            "subject_template": campaign.subject_template,
            "body_template_path": campaign.body_template_path,
            "strategic_reviewed_by": campaign.strategic_reviewed_by,
            "strategic_reviewed_at": campaign.strategic_reviewed_at,
            "approved_by": campaign.approved_by,
            "approved_at": campaign.approved_at,
            "started_at": campaign.started_at,
            "completed_at": campaign.completed_at,
            "config": {
                "from_inbox": campaign.config.from_inbox,
                "subject_template": campaign.config.subject_template,
                "body_template_path": campaign.config.body_template_path,
                "hourly_cap": campaign.config.hourly_cap,
            },
            "recipients": {
                email: {
                    "email": r.email,
                    "display_name": r.display_name,
                    "personalization": r.personalization,
                    "status": r.status,
                    "sent_at": r.sent_at,
                    "message_id": r.message_id,
                    "skip_reason": r.skip_reason,
                }
                for email, r in campaign.recipients.items()
            },
        }

        with open(campaign_file, "w") as f:
            json.dump(campaign_data, f, indent=2)

    def load(self, campaign_id: str) -> Campaign:
        """Load campaign from file."""
        campaign_file = self._get_campaign_file(campaign_id)

        if not campaign_file.exists():
            raise CampaignNotFound(f"Campaign {campaign_id} not found")

        with open(campaign_file, "r") as f:
            campaign_data = json.load(f)

        recipients = {}
        for email, r_data in campaign_data.get("recipients", {}).items():
            email = normalize_email(email)
            recipients[email] = Recipient(
                email=email,
                display_name=r_data.get("display_name", ""),
                personalization=r_data.get("personalization", {}),
                status=r_data.get("status", "pending"),
                sent_at=r_data.get("sent_at"),
                message_id=r_data.get("message_id"),
                skip_reason=r_data.get("skip_reason"),
            )

        campaign = Campaign(
            id=campaign_data["id"],
            created_at=campaign_data["created_at"],
            status=campaign_data["status"],
            from_inbox=campaign_data["from_inbox"],
            subject_template=campaign_data["subject_template"],
            body_template_path=campaign_data["body_template_path"],
            strategic_reviewed_by=campaign_data.get("strategic_reviewed_by"),
            strategic_reviewed_at=campaign_data.get("strategic_reviewed_at"),
            approved_by=campaign_data.get("approved_by"),
            approved_at=campaign_data.get("approved_at"),
            started_at=campaign_data.get("started_at"),
            completed_at=campaign_data.get("completed_at"),
            config=CampaignConfig(
                from_inbox=campaign_data["config"]["from_inbox"],
                subject_template=campaign_data["config"]["subject_template"],
                body_template_path=campaign_data["config"]["body_template_path"],
                hourly_cap=campaign_data["config"].get("hourly_cap"),
            ),
            recipients=recipients,
        )

        return campaign

    def preview(self, campaign_id: str) -> Campaign:
        """
        Move campaign to preview status.

        Args:
            campaign_id: Campaign ID

        Returns:
            Updated Campaign object
        """
        campaign = self.load(campaign_id)

        if campaign.status != "draft":
            raise ValueError(f"Cannot preview campaign in {campaign.status} status. Must be draft.")

        campaign.status = "preview"
        self._save_campaign(campaign)
        self._generate_preview_markdown(campaign_id)
        
        return campaign

    def _generate_preview_markdown(self, campaign_id: str) -> str:
        """
        Generate preview markdown for a campaign.

        Args:
            campaign_id: Campaign ID

        Returns:
            Markdown preview string
        """
        campaign = self.load(campaign_id)

        if not campaign.recipients:
            raise ValueError("No recipients in campaign")

        # Generate preview with first recipient
        first_recipient = list(campaign.recipients.values())[0]

        render_context = {
            "email": first_recipient.email,
            "display_name": first_recipient.display_name or "Recipient Name",
            **first_recipient.personalization,
        }

        subject_rendered, _ = TemplateRenderer._render_content(
            campaign.subject_template, render_context
        )
        body_rendered, _ = TemplateRenderer.render_from_file(
            campaign.body_template_path, render_context
        )

        preview = f"""# Campaign Preview: {campaign_id}

**From:** {campaign.from_inbox}
**Subject:** {subject_rendered}
**Recipients:** {len(campaign.recipients)}
**Status:** {campaign.status}

## Email Body (sample for first recipient)

{body_rendered}

---

*This is a preview. Once approved, emails will be sent to all {len(campaign.recipients)} recipients.*
"""

        # Save preview
        preview_file = self._get_preview_file(campaign_id)
        with open(preview_file, "w") as f:
            f.write(preview)

        # Update campaign status to preview
        campaign.status = "preview"
        self._save_campaign(campaign)

        return preview

    def strategic_review(self, campaign_id: str, by: str = None, reviewed_by: str = None) -> Campaign:
        """
        Mark campaign as strategically reviewed (by Lacie).

        Args:
            campaign_id: Campaign ID
            by: Who reviewed (should be "lacie")
            reviewed_by: Alias for 'by' parameter

        Returns:
            Updated Campaign object
        """
        reviewer = reviewed_by or by or "lacie"
        campaign = self.load(campaign_id)

        if campaign.status not in ("draft", "preview"):
            raise ValueError(
                f"Can only review campaigns in draft/preview status, not {campaign.status}"
            )

        campaign.strategic_reviewed_by = reviewer
        campaign.strategic_reviewed_at = datetime.utcnow().isoformat() + "Z"
        campaign.status = "strategic_review"

        self._save_campaign(campaign)
        return campaign

    def approve(self, campaign_id: str, by: str = None, approved_by: str = None) -> Campaign:
        """
        Mark campaign as approved for sending (by toli).

        Args:
            campaign_id: Campaign ID
            by: Who approved (should be "toli")
            approved_by: Alias for 'by' parameter

        Returns:
            Updated Campaign object
        """
        approver = approved_by or by or "toli"
        campaign = self.load(campaign_id)

        if campaign.status != "strategic_review":
            raise ValueError(
                f"Can only approve campaigns in strategic_review status, not {campaign.status}"
            )

        if not campaign.strategic_reviewed_by:
            raise ValueError("Campaign must be strategically reviewed first")

        campaign.approved_by = approver
        campaign.approved_at = datetime.utcnow().isoformat() + "Z"
        campaign.status = "approved"

        self._save_campaign(campaign)
        return campaign

    def run(self, campaign_id: str) -> Campaign:
        """
        Start sending a campaign.

        Args:
            campaign_id: Campaign ID

        Returns:
            Updated Campaign object
        """
        campaign = self.load(campaign_id)

        if campaign.status != "approved":
            raise ValueError(
                f"Can only run campaigns in approved status, not {campaign.status}"
            )

        campaign.status = "running"
        campaign.started_at = datetime.utcnow().isoformat() + "Z"
        self._save_campaign(campaign)
        return campaign

    def pause(self, campaign_id: str) -> Campaign:
        """
        Pause an active campaign.

        Args:
            campaign_id: Campaign ID

        Returns:
            Updated Campaign object
        """
        campaign = self.load(campaign_id)

        if campaign.status not in ("running", "approved"):
            raise ValueError(
                f"Can only pause campaigns in running/approved status, not {campaign.status}"
            )

        campaign.status = "paused"
        self._save_campaign(campaign)
        return campaign

    def resume(self, campaign_id: str) -> Campaign:
        """
        Resume a paused campaign.

        Args:
            campaign_id: Campaign ID

        Returns:
            Updated Campaign object
        """
        campaign = self.load(campaign_id)

        if campaign.status != "paused":
            raise ValueError(
                f"Can only resume campaigns in paused status, not {campaign.status}"
            )

        campaign.status = "running"
        self._save_campaign(campaign)
        return campaign

    def cancel(self, campaign_id: str) -> Campaign:
        """
        Cancel a campaign.

        Args:
            campaign_id: Campaign ID

        Returns:
            Updated Campaign object
        """
        campaign = self.load(campaign_id)

        if campaign.status not in ("draft", "preview", "strategic_review", "approved", "paused"):
            raise ValueError(
                f"Cannot cancel campaign in {campaign.status} status"
            )

        campaign.status = "cancelled"
        self._save_campaign(campaign)
        return campaign

    def complete(self, campaign_id: str) -> Campaign:
        """
        Mark a campaign as completed.

        Args:
            campaign_id: Campaign ID

        Returns:
            Updated Campaign object
        """
        campaign = self.load(campaign_id)

        if campaign.status != "running":
            raise ValueError(
                f"Can only complete campaigns in running status, not {campaign.status}"
            )

        campaign.status = "completed"
        campaign.completed_at = datetime.utcnow().isoformat() + "Z"
        self._save_campaign(campaign)
        return campaign

    def get(self, campaign_id: str) -> Campaign:
        """
        Get a campaign by ID.

        Args:
            campaign_id: Campaign ID

        Returns:
            Campaign object
        """
        return self.load(campaign_id)

    def list(self, status: Optional[str] = None) -> list[Campaign]:
        """
        List all campaigns, optionally filtered by status.

        Args:
            status: Optional status filter

        Returns:
            List of Campaign objects
        """
        return self.list_campaigns(status)

    def list_by_status(self, status: str) -> list[Campaign]:
        """
        List campaigns by status.

        Args:
            status: Campaign status to filter by

        Returns:
            List of Campaign objects with given status
        """
        return self.list_campaigns(status)

    def list_campaigns(self, status: Optional[str] = None) -> list[Campaign]:
        """List all campaigns, optionally filtered by status."""
        campaigns = []

        for campaign_dir in self.campaigns_dir.iterdir():
            if campaign_dir.is_dir():
                try:
                    campaign = self.load(campaign_dir.name)
                    if status is None or campaign.status == status:
                        campaigns.append(campaign)
                except (CampaignNotFound, Exception):
                    pass

        return sorted(campaigns, key=lambda c: c.created_at, reverse=True)

    def get_status(self, campaign_id: str) -> dict:
        """Get campaign status summary."""
        campaign = self.load(campaign_id)

        return {
            "id": campaign.id,
            "status": campaign.status,
            "created_at": campaign.created_at,
            "recipients": len(campaign.recipients),
            "strategic_reviewed_by": campaign.strategic_reviewed_by,
            "approved_by": campaign.approved_by,
            "started_at": campaign.started_at,
            "completed_at": campaign.completed_at,
        }
