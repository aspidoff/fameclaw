"""
Data models and dataclasses for fameclaw.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class Recipient:
    """Individual outreach recipient."""

    email: str
    display_name: str = ""
    personalization: dict = field(default_factory=dict)
    status: str = "pending"  # pending | sending | sent | skipped | blocked | failed
    sent_at: Optional[str] = None
    message_id: Optional[str] = None  # AgentMail message ID after send
    skip_reason: Optional[str] = None


@dataclass
class CampaignConfig:
    """Configuration for a specific campaign."""

    from_inbox: str
    subject_template: str
    body_template_path: str
    hourly_cap: Optional[int] = None  # Uses default if not set


@dataclass
class Campaign:
    """Campaign with two-step approval workflow."""

    id: str
    created_at: str  # ISO 8601
    status: str  # draft | preview | strategic_review | approved | running | paused | completed | cancelled
    from_inbox: str
    subject_template: str
    body_template_path: str
    # Two-step approval
    strategic_reviewed_by: Optional[str] = None  # Lacie
    strategic_reviewed_at: Optional[str] = None  # ISO 8601
    approved_by: Optional[str] = None  # toli
    approved_at: Optional[str] = None  # ISO 8601
    started_at: Optional[str] = None  # ISO 8601
    completed_at: Optional[str] = None  # ISO 8601
    config: CampaignConfig = field(default_factory=lambda: CampaignConfig("", "", ""))
    recipients: dict = field(default_factory=dict)  # keyed by email


@dataclass
class LedgerEntry:
    """Record of a sent message."""

    campaign_id: str
    recipient_email: str
    message_id: str  # AgentMail message ID
    sent_at: str  # ISO 8601
    status: str  # sending | sent | bounced_hard | bounced_soft | delivery_failed | opened | clicked | replied
    bounce_type: Optional[str] = None  # hard | soft
    error_message: Optional[str] = None


@dataclass
class Ledger:
    """Full ledger of all outreach activity."""

    version: int = 1
    entries: list[LedgerEntry] = field(default_factory=list)


@dataclass
class SuppressionEntry:
    """Suppression list entry."""

    email: str
    reason: str  # explicit_opt_out | hard_bounce | soft_bounce_repeated | domain_complaint | policy_violation | user_requested
    added_at: str  # ISO 8601
    added_by: str = "system"


@dataclass
class SuppressionList:
    """Suppression list state."""

    version: int = 1
    entries: dict = field(default_factory=dict)  # keyed by email


@dataclass
class BounceTracker:
    """Bounce tracking for a single domain."""

    domain: str
    total_sends: int = 0
    hard_bounces: int = 0
    soft_bounces: int = 0
    soft_bounce_counts: dict = field(default_factory=dict)  # email -> count (for 3x rule)
    last_checked: Optional[str] = None  # ISO 8601

    @property
    def hard_bounce_rate(self) -> float:
        """Hard bounce rate as decimal (0.0 to 1.0)."""
        if self.total_sends == 0:
            return 0.0
        return self.hard_bounces / self.total_sends

    @property
    def domain_at_risk(self) -> bool:
        """True if hard bounce rate >= 5% and min 10 sends."""
        return self.hard_bounce_rate >= 0.05 and self.total_sends >= 10


@dataclass
class BounceState:
    """Bounce tracking state for all domains."""

    version: int = 1
    trackers: dict = field(default_factory=dict)  # keyed by domain (e.g. "souls.zip")
    last_checked: Optional[str] = None  # ISO 8601


@dataclass
class InboxWarmup:
    """Warm-up state for a single inbox/domain."""

    domain: str
    first_send_date: Optional[str] = None  # ISO 8601 (YYYY-MM-DD)
    sends_today: int = 0
    sends_today_date: str = ""  # YYYY-MM-DD, tracks when last reset
    # Engagement tracking (required for engagement gating)
    stage_sends: int = 0  # sends in current stage
    stage_opens: int = 0  # opens in current stage
    stage_bounces: int = 0  # bounces in current stage
    paused: bool = False
    pause_reason: Optional[str] = None  # why paused (engagement, manual, etc.)

    @property
    def open_rate(self) -> float:
        """Open rate as decimal (0.0 to 1.0)."""
        if self.stage_sends == 0:
            return 1.0  # Assume good until we have data
        return self.stage_opens / self.stage_sends

    @property
    def bounce_rate(self) -> float:
        """Bounce rate as decimal."""
        if self.stage_sends == 0:
            return 0.0
        return self.stage_bounces / self.stage_sends

    def days_since_first_send(self) -> int:
        """Number of days since first_send_date."""
        from datetime import datetime

        if not self.first_send_date:
            return 0
        first = datetime.fromisoformat(self.first_send_date).date()
        today = datetime.utcnow().date()
        return (today - first).days

    @property
    def stage(self) -> int:
        """Current warm-up stage (1-4) based on days since first send."""
        days = self.days_since_first_send()
        if days <= 14:
            return 1
        elif days <= 28:
            return 2
        elif days <= 56:
            return 3
        else:
            return 4

    @property
    def daily_cap_for_stage(self) -> int:
        """Daily send cap for current stage."""
        stage_caps = {1: 15, 2: 30, 3: 50, 4: 100}
        return stage_caps.get(self.stage, 100)


@dataclass
class WarmupState:
    """Warm-up state for all domains."""

    version: int = 1
    inboxes: dict = field(default_factory=dict)  # keyed by domain (e.g. "souls.zip")


@dataclass
class OutreachConfig:
    """Global outreach configuration."""

    version: int = 1
    global_daily_cap: int = 50
    default_hourly_cap: int = 20
    default_send_spacing_seconds: int = 30
    cross_campaign_cooldown_days: int = 30
    default_from_inbox: str = "lacie@souls.zip"
    physical_address: str = ""  # CAN-SPAM (e.g. "souls.zip | Brooklyn, NY")
    require_unsubscribe: bool = False  # Enforce unsubscribe in body (off for personal outreach)
    all_times_utc: bool = True
