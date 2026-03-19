"""
Custom exception hierarchy for fameclaw.
"""


class OutreachError(Exception):
    """Base exception for all fameclaw errors."""

    pass


class ValidationError(OutreachError):
    """Validation failed (email format, campaign ID, etc.)."""

    pass


class CampaignError(OutreachError):
    """Campaign operation failed."""

    pass


class CampaignNotFound(OutreachError):
    """Campaign with given ID does not exist."""

    pass


class TemplateError(OutreachError):
    """Template error (loading, rendering, etc.)."""

    pass


class TemplateValidationError(OutreachError):
    """Template validation failed (missing variables, invalid syntax, etc.)."""

    pass


class SuppressedRecipientError(OutreachError):
    """Recipient is in suppression list."""

    pass


class RateLimitedError(OutreachError):
    """Hit rate limit (hourly, daily, or per-tier)."""

    pass


class LockedError(OutreachError):
    """Failed to acquire file lock (timeout or stale lock)."""

    pass


class DomainAtRiskError(OutreachError):
    """Domain health at risk (hard bounce rate >= 5%)."""

    pass


class CanSpamViolationError(OutreachError):
    """Campaign violates CAN-SPAM requirements."""

    pass


class EngagementPausedError(OutreachError):
    """Warm-up is paused due to poor engagement metrics."""

    pass


class CampaignDuplicateError(OutreachError):
    """Campaign already exists or recipient is already in another active campaign."""

    pass


class CooldownViolationError(OutreachError):
    """Cross-campaign cooldown period not met."""

    pass


class ApprovalRequiredError(OutreachError):
    """Campaign not approved for sending."""

    pass
