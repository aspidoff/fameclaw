"""
Bounce tracking and domain health monitoring.
"""

from datetime import datetime
from typing import Optional

from .state import StateManager
from .models import BounceState, BounceTracker
from .suppressor import SuppressionManager


class BounceManager:
    """Manage bounce tracking and domain health."""

    BOUNCE_FILE = "bounces.json"

    def __init__(self, state_dir: str = "~/.openclaw/outreach"):
        """Initialize bounce manager."""
        self.state_manager = StateManager(state_dir)
        self.suppressor = SuppressionManager(state_dir)

    def load(self) -> BounceState:
        """Load bounce state."""
        bounce_data = self.state_manager.read(self.BOUNCE_FILE)

        if not bounce_data:
            return BounceState(version=1, trackers={})

        trackers = {}
        for domain, tracker_data in bounce_data.get("trackers", {}).items():
            trackers[domain] = BounceTracker(
                domain=domain,
                total_sends=tracker_data.get("total_sends", 0),
                hard_bounces=tracker_data.get("hard_bounces", 0),
                soft_bounces=tracker_data.get("soft_bounces", 0),
                soft_bounce_counts=tracker_data.get("soft_bounce_counts", {}),
                last_checked=tracker_data.get("last_checked"),
            )

        return BounceState(
            version=bounce_data.get("version", 1),
            trackers=trackers,
            last_checked=bounce_data.get("last_checked"),
        )

    def save(self, bounce_state: BounceState) -> None:
        """Save bounce state."""
        bounce_data = {
            "version": bounce_state.version,
            "last_checked": bounce_state.last_checked,
            "trackers": {
                domain: {
                    "domain": tracker.domain,
                    "total_sends": tracker.total_sends,
                    "hard_bounces": tracker.hard_bounces,
                    "soft_bounces": tracker.soft_bounces,
                    "soft_bounce_counts": tracker.soft_bounce_counts,
                    "last_checked": tracker.last_checked,
                }
                for domain, tracker in bounce_state.trackers.items()
            },
        }
        self.state_manager.write(self.BOUNCE_FILE, bounce_data)

    def get_or_create_tracker(self, domain: str) -> BounceTracker:
        """Get or create tracker for a domain."""
        bounce_state = self.load()

        if domain in bounce_state.trackers:
            return bounce_state.trackers[domain]

        tracker = BounceTracker(domain=domain)
        bounce_state.trackers[domain] = tracker
        self.save(bounce_state)
        return tracker

    def initialize_tracker(self, domain: str) -> BounceTracker:
        """Alias for get_or_create_tracker."""
        return self.get_or_create_tracker(domain)

    def update_tracker(self, domain: str, tracker: BounceTracker) -> None:
        """Update and save a tracker."""
        bounce_state = self.load()
        bounce_state.trackers[domain] = tracker
        bounce_state.last_checked = datetime.utcnow().isoformat() + "Z"
        self.save(bounce_state)

    def record_hard_bounce(self, domain: str, email: str) -> None:
        """
        Record hard bounce and auto-suppress.

        Args:
            domain: Domain (e.g. "souls.zip")
            email: Email that hard-bounced
        """
        bounce_state = self.load()
        tracker = self.get_or_create_tracker(domain)

        tracker.total_sends += 1
        tracker.hard_bounces += 1
        tracker.last_checked = datetime.utcnow().isoformat() + "Z"

        bounce_state.trackers[domain] = tracker
        bounce_state.last_checked = datetime.utcnow().isoformat() + "Z"
        self.save(bounce_state)

        # Auto-suppress
        self.suppressor.add(
            email=email,
            reason="hard_bounce",
            added_by="bounce_system",
        )

    def record_soft_bounce(self, domain: str, email: str) -> None:
        """
        Record soft bounce. Auto-suppress after 3 soft bounces.

        Args:
            domain: Domain
            email: Email that soft-bounced
        """
        bounce_state = self.load()
        tracker = self.get_or_create_tracker(domain)

        tracker.total_sends += 1
        tracker.soft_bounces += 1

        # Track soft bounces per email
        if email not in tracker.soft_bounce_counts:
            tracker.soft_bounce_counts[email] = 0
        tracker.soft_bounce_counts[email] += 1

        # Auto-suppress after 3
        if tracker.soft_bounce_counts[email] >= 3:
            self.suppressor.add(
                email=email,
                reason="soft_bounce_repeated",
                added_by="bounce_system",
            )
            # Clear count after suppression
            del tracker.soft_bounce_counts[email]

        tracker.last_checked = datetime.utcnow().isoformat() + "Z"
        bounce_state.trackers[domain] = tracker
        bounce_state.last_checked = datetime.utcnow().isoformat() + "Z"
        self.save(bounce_state)

    def record_delivery_success(self, domain: str) -> None:
        """Record successful delivery (increments denominator)."""
        bounce_state = self.load()
        tracker = self.get_or_create_tracker(domain)

        tracker.total_sends += 1
        tracker.last_checked = datetime.utcnow().isoformat() + "Z"

        bounce_state.trackers[domain] = tracker
        bounce_state.last_checked = datetime.utcnow().isoformat() + "Z"
        self.save(bounce_state)

    def domain_at_risk(self, domain: str) -> tuple[bool, Optional[str]]:
        """
        Check if domain is at risk (hard bounce rate >= 5%).

        Args:
            domain: Domain to check

        Returns:
            (at_risk: bool, reason: str | None)
        """
        tracker = self.get_or_create_tracker(domain)

        if tracker.domain_at_risk:
            reason = (
                f"Domain at risk: {tracker.hard_bounce_rate:.1%} hard bounce rate "
                f"({tracker.hard_bounces}/{tracker.total_sends} sends). "
                f"Minimum threshold is 5% over 10 sends. All sending halted."
            )
            return True, reason

        return False, None

    def get_tracker(self, domain: str) -> Optional[BounceTracker]:
        """Get tracker for a domain."""
        bounce_state = self.load()
        return bounce_state.trackers.get(domain)

    def record_bounce(self, email_or_domain: str, email_or_type: str = "hard", bounce_type: str = None) -> None:
        """
        Record a bounce (hard or soft).
        
        Can be called as:
        - record_bounce(email, "hard") - domain inferred from email
        - record_bounce(domain, email, "hard") - explicit domain

        Args:
            email_or_domain: Email or domain
            email_or_type: Email or bounce type (default "hard")
            bounce_type: Type of bounce if using 3-arg form
        """
        # Detect calling convention
        if bounce_type is not None:
            # 3-arg form: record_bounce(domain, email, bounce_type)
            domain = email_or_domain
            email = email_or_type
            btype = bounce_type
        elif email_or_type in ("hard", "soft"):
            # 2-arg form: record_bounce(email, "hard"|"soft")
            # Extract domain from email
            email = email_or_domain
            btype = email_or_type
            domain = email.split("@")[1] if "@" in email else "unknown"
        else:
            # 2-arg form: record_bounce(email, email)... unclear, assume email then hard bounce
            email = email_or_type
            btype = "hard"
            domain = email_or_domain.split("@")[1] if "@" in email_or_domain else "unknown"
        
        if btype == "hard":
            self.record_hard_bounce(domain, email)
        else:
            self.record_soft_bounce(domain, email)

    def list_all(self) -> list[BounceTracker]:
        """Get all bounce trackers."""
        bounce_state = self.load()
        return sorted(bounce_state.trackers.values(), key=lambda t: t.domain)

    def get_summary(self, domain: str) -> dict:
        """Get summary statistics for a domain."""
        tracker = self.get_or_create_tracker(domain)

        return {
            "domain": domain,
            "total_sends": tracker.total_sends,
            "hard_bounces": tracker.hard_bounces,
            "soft_bounces": tracker.soft_bounces,
            "hard_bounce_rate": f"{tracker.hard_bounce_rate:.1%}",
            "at_risk": tracker.domain_at_risk,
            "last_checked": tracker.last_checked,
        }
