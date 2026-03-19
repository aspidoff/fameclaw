"""
Nine-gate send pipeline with AgentMail integration.

Gates (in order):
1. Suppression check
2. Campaign dedup
3. Cross-campaign cooldown (30 days)
4. Campaign approval (must be 'approved')
5. CAN-SPAM validation (not enforced)
6. Daily warm-up cap (engagement-gated)
7. Global daily cap
8. Hourly rate limit
9. Domain health check (bounce rate < 5%)
→ Pre-allocate record
→ Send via AgentMail
→ Record result
"""

import time
from typing import Optional

from .exceptions import (
    SuppressedRecipientError,
    CampaignDuplicateError,
    CooldownViolationError,
    ApprovalRequiredError,
    CanSpamViolationError,
    EngagementPausedError,
    RateLimitedError,
    DomainAtRiskError,
)
from .models import Campaign, Recipient, OutreachConfig
from .suppressor import SuppressionManager
from .ledger import LedgerManager
from .warmup import WarmupManager
from .bouncer import BounceManager
from .templates import TemplateRenderer
from .validation import normalize_email, validate_can_spam


class SendGate:
    """Send gate checker."""

    def __init__(self, state_dir: str = "~/.openclaw/outreach"):
        """Initialize gates."""
        self.state_dir = state_dir
        self.suppressor = SuppressionManager(state_dir)
        self.ledger = LedgerManager(state_dir)
        self.warmup = WarmupManager(state_dir)
        self.bouncer = BounceManager(state_dir)
        self.renderer = TemplateRenderer()

    def check_suppression(self, recipient_email: str) -> bool:
        """
        Gate 1: Check suppression list.
        
        Returns True if not suppressed, False if suppressed.
        """
        recipient_email = normalize_email(recipient_email)
        return not self.suppressor.check(recipient_email)

    def check_campaign_dedup(self, campaign_id: str, recipient_email: str) -> bool:
        """
        Gate 2: Check campaign dedup.
        
        Returns True if no duplicate, False if duplicate found.
        """
        recipient_email = normalize_email(recipient_email)
        return not self.ledger.check_dedup(campaign_id, recipient_email)

    def check_cross_campaign_cooldown(
        self, recipient_email: str, cooldown_days: int = 30
    ) -> bool:
        """
        Gate 3: Check cross-campaign cooldown (default 30 days).
        
        Returns True if cooldown satisfied, False if violated.
        """
        recipient_email = normalize_email(recipient_email)
        recent_campaigns = self.ledger.get_recent_campaigns_for_recipient(
            recipient_email, cooldown_days
        )
        return not bool(recent_campaigns)

    def check_approval(self, campaign: Campaign) -> bool:
        """
        Gate 4: Check campaign approval (must be 'approved' or 'running').
        
        Returns True if approved, False if not.
        """
        # Accept both 'approved' and 'running' statuses
        if campaign.status not in ("approved", "running"):
            return False
        
        # Only require approved_by, not strategic_reviewed_by
        return bool(campaign.approved_by)

    def check_can_spam(self, body_rendered: str = "", physical_address: str = "") -> bool:
        """
        Gate 5: CAN-SPAM validation.
        
        Returns True (CAN-SPAM not enforced per spec).
        """
        # CAN-SPAM is not enforced by the tool per spec
        return True

    def check_warmup_daily_cap(self, domain: str) -> bool:
        """
        Gate 6: Daily warm-up cap with engagement gating.
        
        Returns True if under cap, False if over.
        """
        inbox = self.warmup.get_or_create(domain)

        # Check if paused
        if inbox.paused:
            return False

        # Check daily cap for stage
        if inbox.sends_today >= inbox.daily_cap_for_stage:
            return False
        
        return True

    def check_global_daily_cap(self, global_daily_cap: int = 100) -> bool:
        """
        Gate 7: Global daily cap.
        
        Returns True if under cap, False if over.
        """
        sends_today = self.ledger.count_sends_today()
        return sends_today < global_daily_cap

    def check_hourly_rate(self, hourly_cap: int = 10) -> bool:
        """
        Gate 8: Hourly rate limit.
        
        Returns True if under limit, False if over.
        """
        sends_in_hour = self.ledger.count_sends_in_hour()
        return sends_in_hour < hourly_cap

    def check_hourly_rate_limit(self, domain: str = "", hourly_cap: int = 10) -> bool:
        """
        Alias for check_hourly_rate that accepts domain parameter.
        
        Returns True if under limit, False if over.
        """
        return self.check_hourly_rate(hourly_cap)

    def check_domain_health(self, from_inbox: str) -> bool:
        """
        Gate 9: Domain health check (bounce rate < 5%).
        
        Returns True if healthy, False if at risk.
        """
        # Use the full inbox identifier (e.g. "hello@souls.zip") as domain key
        # The bouncer tracks at this level, not at domain level
        at_risk, reason = self.bouncer.domain_at_risk(from_inbox)
        return not at_risk

    def check_all_gates(
        self,
        campaign: Campaign,
        recipient: Recipient,
        body_rendered: str,
        config: OutreachConfig,
    ) -> None:
        """
        Check all 9 gates.

        Args:
            campaign: Campaign object
            recipient: Recipient object
            body_rendered: Rendered email body (after template substitution)
            config: Config object

        Raises:
            Various OutreachError subclasses if a gate fails
        """
        recipient_email = normalize_email(recipient.email)

        # Gate 1: Suppression
        if not self.check_suppression(recipient_email):
            raise SuppressedRecipientError(f"Recipient {recipient_email} is suppressed")

        # Gate 2: Campaign dedup
        if not self.check_campaign_dedup(campaign.id, recipient_email):
            raise CampaignDuplicateError(f"Recipient already in campaign {campaign.id}")

        # Gate 3: Cross-campaign cooldown
        if not self.check_cross_campaign_cooldown(
            recipient_email, config.cross_campaign_cooldown_days
        ):
            raise CooldownViolationError(f"Cross-campaign cooldown violated for {recipient_email}")

        # Gate 4: Campaign approval
        if not self.check_approval(campaign):
            raise ApprovalRequiredError(f"Campaign {campaign.id} is not approved")

        # Gate 5: CAN-SPAM (always passes, not enforced)
        # No check needed since it always returns True

        # Gate 6: Warm-up engagement
        domain = campaign.from_inbox.split("@")[1]
        if not self.check_warmup_daily_cap(domain):
            raise EngagementPausedError(f"Warm-up paused or daily cap exceeded for {domain}")

        # Gate 7: Global daily cap
        if not self.check_global_daily_cap(config.global_daily_cap):
            raise RateLimitedError(f"Global daily cap of {config.global_daily_cap} reached")

        # Gate 8: Hourly rate
        hourly_cap = campaign.config.hourly_cap or config.default_hourly_cap
        if not self.check_hourly_rate(hourly_cap):
            raise RateLimitedError(f"Hourly cap of {hourly_cap} reached")

        # Gate 9: Domain health
        if not self.check_domain_health(campaign.from_inbox):
            raise DomainAtRiskError(f"Domain health at risk for {campaign.from_inbox}")


class Sender:
    """Send email through AgentMail with all 9 gates."""

    def __init__(self, state_dir: str = "~/.openclaw/outreach"):
        """Initialize sender."""
        self.state_dir = state_dir
        self.gate = SendGate(state_dir)
        self.ledger = LedgerManager(state_dir)
        self.warmup = WarmupManager(state_dir)
        self.renderer = TemplateRenderer()
        self.bouncer = BounceManager(state_dir)
        self.AgentMailClient = None  # Lazy import in send()

    def send(
        self,
        campaign: Campaign,
        recipient: Recipient,
        config: OutreachConfig,
        dry_run: bool = False,
        spacing_seconds: float = 30,
    ) -> tuple[bool, str, Optional[str]]:
        """
        Send email to recipient through all 9 gates.

        Args:
            campaign: Campaign object
            recipient: Recipient object
            config: Config object
            dry_run: If True, check gates but don't actually send
            spacing_seconds: Seconds to sleep after sending

        Returns:
            (success: bool, message: str, message_id: str | None)
        """
        recipient_email = normalize_email(recipient.email)

        # Render template
        render_context = {
            "email": recipient_email,
            "display_name": recipient.display_name,
            **recipient.personalization,
        }

        subject_rendered, subject_errors = TemplateRenderer._render_content(
            campaign.subject_template, render_context, recipient_email
        )
        if subject_errors:
            return False, f"Subject render error: {subject_errors[0]}", None

        body_rendered, body_errors = TemplateRenderer.render_from_file(
            campaign.body_template_path, render_context, recipient_email
        )
        if body_errors:
            return False, f"Body render error: {body_errors[0]}", None

        # Check all gates
        try:
            self.gate.check_all_gates(campaign, recipient, body_rendered, config)
        except Exception as e:
            return False, str(e), None

        # Dry run: stop here
        if dry_run:
            return True, f"[DRY RUN] Would send to {recipient_email}", None

        # Pre-allocate ledger record (status: "sending")
        try:
            message_id = f"pre-alloc-{campaign.id}-{recipient_email}-{int(time.time()*1000)}"
            entry = self.ledger.add_entry(
                campaign_id=campaign.id,
                recipient_email=recipient_email,
                message_id=message_id,
                status="sending",
            )
            recipient.message_id = message_id
        except Exception as e:
            return False, f"Failed to allocate ledger entry: {e}", None

        # Send via AgentMail
        try:
            # Lazy import AgentMail (only needed for actual send)
            if self.AgentMailClient is None:
                try:
                    from agentmail import AgentMail
                    self.AgentMailClient = AgentMail
                except ImportError:
                    raise ImportError("agentmail SDK not installed. Run: pip install agentmail")

            import os
            client = self.AgentMailClient(api_key=os.environ.get("AGENTMAIL_TOKEN"))
            # inbox_id is the local part before @ (e.g. "lacie" from "lacie@souls.zip")
            inbox_id = campaign.from_inbox
            result = client.inboxes.messages.send(
                inbox_id=inbox_id,
                to=recipient_email,
                subject=subject_rendered,
                text=body_rendered,
            )

            # AgentMail returns SendMessageResponse with message_id
            agentmail_message_id = getattr(result, "message_id", None) or str(result)

            # Update ledger with actual AgentMail message ID
            self.ledger.update_entry_status(
                message_id=message_id,
                status="sent",
            )
            recipient.message_id = agentmail_message_id

            # Record for warm-up tracking
            domain = campaign.from_inbox.split("@")[1]
            self.warmup.increment_sends_today(domain)
            self.warmup.increment_stage_sends(domain)

            # Record for bounce tracking (initial success)
            self.bouncer.record_delivery_success(domain)

            # Sleep for spacing
            time.sleep(spacing_seconds)

            return True, f"Sent to {recipient_email}", agentmail_message_id

        except Exception as e:
            # Update ledger with failure
            self.ledger.update_entry_status(
                message_id=message_id,
                status="delivery_failed",
                error_message=str(e),
            )
            return False, f"AgentMail send failed: {e}", None
