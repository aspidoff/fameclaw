"""
Warm-up state and engagement-gated ramp management.
"""

from datetime import datetime
from typing import Optional

from .state import StateManager
from .models import WarmupState, InboxWarmup


class WarmupManager:
    """Manage warm-up state and engagement gating."""

    WARMUP_FILE = "warmup.json"
    MIN_SENDS_FOR_JUDGMENT = 10  # Need this many sends before judging engagement

    def __init__(self, state_dir: str = "~/.openclaw/outreach"):
        """Initialize warmup manager."""
        self.state_manager = StateManager(state_dir)

    def load(self) -> WarmupState:
        """Load warm-up state."""
        warmup_data = self.state_manager.read(self.WARMUP_FILE)

        if not warmup_data:
            return WarmupState(version=1, inboxes={})

        inboxes = {}
        for domain, inbox_data in warmup_data.get("inboxes", {}).items():
            inboxes[domain] = InboxWarmup(
                domain=domain,
                first_send_date=inbox_data.get("first_send_date"),
                sends_today=inbox_data.get("sends_today", 0),
                sends_today_date=inbox_data.get("sends_today_date", ""),
                stage_sends=inbox_data.get("stage_sends", 0),
                stage_opens=inbox_data.get("stage_opens", 0),
                stage_bounces=inbox_data.get("stage_bounces", 0),
                paused=inbox_data.get("paused", False),
                pause_reason=inbox_data.get("pause_reason"),
            )

        return WarmupState(version=warmup_data.get("version", 1), inboxes=inboxes)

    def save(self, warmup: WarmupState) -> None:
        """Save warm-up state."""
        warmup_data = {
            "version": warmup.version,
            "inboxes": {
                domain: {
                    "domain": inbox.domain,
                    "first_send_date": inbox.first_send_date,
                    "sends_today": inbox.sends_today,
                    "sends_today_date": inbox.sends_today_date,
                    "stage_sends": inbox.stage_sends,
                    "stage_opens": inbox.stage_opens,
                    "stage_bounces": inbox.stage_bounces,
                    "paused": inbox.paused,
                    "pause_reason": inbox.pause_reason,
                }
                for domain, inbox in warmup.inboxes.items()
            },
        }
        self.state_manager.write(self.WARMUP_FILE, warmup_data)

    def get_or_create(self, domain: str, first_send_date: Optional[str] = None) -> InboxWarmup:
        """
        Get or create warm-up state for a domain.

        Args:
            domain: Domain (e.g. "souls.zip")
            first_send_date: ISO date string (YYYY-MM-DD), defaults to None

        Returns:
            InboxWarmup object
        """
        warmup = self.load()

        if domain in warmup.inboxes:
            return warmup.inboxes[domain]

        today = datetime.utcnow().date().isoformat()
        inbox = InboxWarmup(
            domain=domain,
            first_send_date=first_send_date,
            sends_today=0,
            sends_today_date=today,
        )

        warmup.inboxes[domain] = inbox
        self.save(warmup)
        return inbox

    def initialize_inbox(self, domain: str, first_send_date: Optional[str] = None) -> InboxWarmup:
        """
        Initialize an inbox (alias for get_or_create).

        Args:
            domain: Domain (e.g. "souls.zip")
            first_send_date: ISO date string (YYYY-MM-DD), defaults to None

        Returns:
            InboxWarmup object
        """
        return self.get_or_create(domain, first_send_date)

    def _set_first_send_date(self, domain: str, date: Optional[str] = None) -> None:
        """
        Set the first send date for an inbox (used for stage calculation).

        Args:
            domain: Domain to update
            date: ISO date string (YYYY-MM-DD), defaults to today
        """
        warmup = self.load()
        if domain not in warmup.inboxes:
            self.get_or_create(domain)

        inbox = warmup.inboxes[domain]
        if date is None:
            date = datetime.utcnow().date().isoformat()
        inbox.first_send_date = date
        self.save(warmup)

    def reset_daily_count(self, domain: str) -> None:
        """Reset daily send count (called at start of each day)."""
        warmup = self.load()
        today = datetime.utcnow().date().isoformat()

        if domain in warmup.inboxes:
            inbox = warmup.inboxes[domain]
            if inbox.sends_today_date != today:
                inbox.sends_today = 0
                inbox.sends_today_date = today
                self.save(warmup)

    def increment_sends_today(self, domain: str, count: int = 1) -> None:
        """Increment sends for today."""
        warmup = self.load()
        if domain not in warmup.inboxes:
            self.get_or_create(domain)

        inbox = warmup.inboxes[domain]
        self.reset_daily_count(domain)  # Reset if new day
        inbox.sends_today += count
        self.save(warmup)

    def increment_stage_sends(self, domain: str, count: int = 1) -> None:
        """Increment sends in current stage (for engagement tracking)."""
        warmup = self.load()
        if domain not in warmup.inboxes:
            self.get_or_create(domain)

        inbox = warmup.inboxes[domain]
        inbox.stage_sends += count
        self.save(warmup)

    def record_opens(self, domain: str, count: int = 1) -> None:
        """Record opens in current stage (called from bounce checker)."""
        warmup = self.load()
        if domain not in warmup.inboxes:
            self.get_or_create(domain)

        inbox = warmup.inboxes[domain]
        inbox.stage_opens += count
        self.save(warmup)

    def record_bounces(self, domain: str, count: int = 1) -> None:
        """Record bounces in current stage (called from bounce checker)."""
        warmup = self.load()
        if domain not in warmup.inboxes:
            self.get_or_create(domain)

        inbox = warmup.inboxes[domain]
        inbox.stage_bounces += count
        self.save(warmup)

    def should_advance_stage(self, domain: str) -> bool:
        """
        Check if engagement allows advancing to next stage.

        Args:
            domain: Domain to check

        Returns:
            True if can advance, False if should stay/regress
        """
        healthy, _ = self.check_engagement_health(domain)
        return healthy

    def pause_engagement(self, domain: str, reason: str) -> None:
        """
        Pause warm-up due to poor engagement.

        Args:
            domain: Domain to pause
            reason: Reason for pause (shown to user)
        """
        warmup = self.load()
        if domain not in warmup.inboxes:
            self.get_or_create(domain)

        inbox = warmup.inboxes[domain]
        inbox.paused = True
        inbox.pause_reason = reason
        self.save(warmup)

    def resume(self, domain: str) -> None:
        """Resume paused warm-up."""
        warmup = self.load()
        if domain not in warmup.inboxes:
            return

        inbox = warmup.inboxes[domain]
        inbox.paused = False
        inbox.pause_reason = None
        self.save(warmup)

    def is_paused(self, domain: str) -> tuple[bool, Optional[str]]:
        """
        Check if warm-up is paused.

        Args:
            domain: Domain to check

        Returns:
            (paused: bool, reason: str | None)
        """
        warmup = self.load()
        if domain not in warmup.inboxes:
            return False, None

        inbox = warmup.inboxes[domain]
        return inbox.paused, inbox.pause_reason

    def set_engagement_metrics(
        self,
        domain: str,
        open_rate: Optional[float] = None,
        bounce_rate: Optional[float] = None,
        stage_sends: int = 100,
    ) -> None:
        """
        Set engagement metrics (open_rate and bounce_rate) for a domain.

        This is used for manual metric updates and CLI configuration.

        Args:
            domain: Domain to update
            open_rate: Open rate as decimal (0.0 to 1.0)
            bounce_rate: Bounce rate as decimal (0.0 to 1.0)
            stage_sends: Number of sends to use for calculation (default 100)
        """
        warmup = self.load()
        if domain not in warmup.inboxes:
            self.get_or_create(domain)

        inbox = warmup.inboxes[domain]
        inbox.stage_sends = stage_sends

        if open_rate is not None:
            inbox.stage_opens = int(open_rate * stage_sends)

        if bounce_rate is not None:
            inbox.stage_bounces = int(bounce_rate * stage_sends)

        self.save(warmup)

    def check_engagement_health(self, domain: str) -> tuple[bool, Optional[str]]:
        """
        Check if engagement metrics are healthy for a domain.

        Args:
            domain: Domain to check

        Returns:
            (healthy: bool, reason_if_unhealthy: str | None)
        """
        inbox = self.get_inbox(domain)
        if not inbox:
            return True, None

        # Use the existing check_engagement_health method logic
        if inbox.stage_sends < self.MIN_SENDS_FOR_JUDGMENT:
            return True, None

        if inbox.open_rate < 0.20:
            return False, f"Open rate {inbox.open_rate:.0%} < 20% threshold"

        if inbox.bounce_rate > 0.03:
            return False, f"Bounce rate {inbox.bounce_rate:.0%} > 3% threshold"

        return True, None

    def reset_stage_metrics(self, domain: str) -> None:
        """Reset stage metrics when advancing to new stage."""
        warmup = self.load()
        if domain not in warmup.inboxes:
            return

        inbox = warmup.inboxes[domain]
        inbox.stage_sends = 0
        inbox.stage_opens = 0
        inbox.stage_bounces = 0
        self.save(warmup)

    def get_inbox(self, domain: str) -> Optional[InboxWarmup]:
        """Get warm-up state for a domain."""
        warmup = self.load()
        return warmup.inboxes.get(domain)

    def increment_daily_sends(self, domain: str, count: int = 1) -> None:
        """
        Increment daily sends (alias for increment_sends_today).

        Args:
            domain: Domain to update
            count: Number of sends to increment
        """
        self.increment_sends_today(domain, count)

    def get_daily_cap(self, domain: str) -> int:
        """
        Get daily send cap for a domain's current stage.

        Args:
            domain: Domain to check

        Returns:
            Daily cap for current stage
        """
        inbox = self.get_inbox(domain)
        if not inbox:
            return 0
        return inbox.daily_cap_for_stage

    def list_all(self) -> list[InboxWarmup]:
        """Get all warm-up states."""
        warmup = self.load()
        return sorted(warmup.inboxes.values(), key=lambda i: i.domain)

    def reset_daily_sends(self, domain: str) -> None:
        """Reset daily send count to 0."""
        warmup = self.load()
        if domain in warmup.inboxes:
            inbox = warmup.inboxes[domain]
            inbox.sends_today = 0
            self.save(warmup)
