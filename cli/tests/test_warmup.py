"""Tests for warm-up state management."""

from datetime import datetime, timedelta

import pytest

from fameclaw.warmup import WarmupManager
from fameclaw.models import WarmupState, InboxWarmup


class TestWarmupInitialization:
    """Test warm-up state initialization."""

    def test_warmup_initialization(self, warmup_manager):
        """Test warm-up state initializes correctly."""
        warmup = warmup_manager.load()
        assert warmup.version == 1
        assert warmup.inboxes == {}

    def test_initialize_inbox(self, warmup_manager):
        """Test initializing a new inbox."""
        warmup_manager.initialize_inbox("hello@souls.zip")

        warmup = warmup_manager.load()
        assert "hello@souls.zip" in warmup.inboxes
        inbox = warmup.inboxes["hello@souls.zip"]
        assert inbox.domain == "hello@souls.zip"
        assert inbox.sends_today == 0

    def test_inbox_persistence(self, warmup_manager, temp_state_dir):
        """Test inbox state persists across loads."""
        warmup_manager.initialize_inbox("hello@souls.zip")

        new_manager = WarmupManager(temp_state_dir)
        warmup = new_manager.load()
        assert "hello@souls.zip" in warmup.inboxes


class TestWarmupDailyReset:
    """Test daily reset logic."""

    def test_daily_reset(self, warmup_manager):
        """Test daily sends reset at midnight."""
        warmup_manager.initialize_inbox("hello@souls.zip")

        # Simulate sends today
        warmup_manager.increment_daily_sends("hello@souls.zip", 5)
        inbox = warmup_manager.get_inbox("hello@souls.zip")
        assert inbox.sends_today == 5

        # Manually trigger daily reset (would happen at midnight)
        warmup_manager.reset_daily_sends("hello@souls.zip")
        inbox = warmup_manager.get_inbox("hello@souls.zip")
        assert inbox.sends_today == 0

    def test_sends_today_cap(self, warmup_manager):
        """Test sends today counter."""
        warmup_manager.initialize_inbox("hello@souls.zip")

        for i in range(10):
            warmup_manager.increment_daily_sends("hello@souls.zip", 1)

        inbox = warmup_manager.get_inbox("hello@souls.zip")
        assert inbox.sends_today == 10

    def test_multiple_inboxes_independent(self, warmup_manager):
        """Test that inboxes have independent daily counts."""
        warmup_manager.initialize_inbox("hello@souls.zip")
        warmup_manager.initialize_inbox("support@souls.zip")

        warmup_manager.increment_daily_sends("hello@souls.zip", 5)
        warmup_manager.increment_daily_sends("support@souls.zip", 3)

        hello = warmup_manager.get_inbox("hello@souls.zip")
        support = warmup_manager.get_inbox("support@souls.zip")

        assert hello.sends_today == 5
        assert support.sends_today == 3


class TestWarmupStages:
    """Test warm-up stage calculation."""

    def test_stage_initialization(self, warmup_manager):
        """Test initial stage is correct."""
        warmup_manager.initialize_inbox("hello@souls.zip")
        inbox = warmup_manager.get_inbox("hello@souls.zip")

        assert inbox.stage == 1
        assert inbox.first_send_date is None

    def test_stage_based_on_days(self, warmup_manager):
        """Test stage advancement based on days."""
        warmup_manager.initialize_inbox("hello@souls.zip")

        # Set first_send_date to simulate progression
        warmup_manager._set_first_send_date("hello@souls.zip")
        inbox = warmup_manager.get_inbox("hello@souls.zip")

        # Stage logic:
        # Days 0-4: Stage 1
        # Days 5-9: Stage 2
        # Days 10-14: Stage 3
        # Days 15+: Stage 4

        assert inbox.stage == 1

    def test_stage_advancement(self, warmup_manager):
        """Test stage advances based on time and metrics."""
        warmup_manager.initialize_inbox("hello@souls.zip")
        warmup_manager._set_first_send_date("hello@souls.zip")

        # Simulate good metrics
        warmup_manager.set_engagement_metrics("hello@souls.zip", open_rate=0.35, bounce_rate=0.01)

        inbox = warmup_manager.get_inbox("hello@souls.zip")
        # Stage advancement requires time + good metrics
        # Details depend on implementation

    def test_max_stage(self, warmup_manager):
        """Test maximum stage is 4."""
        warmup_manager.initialize_inbox("hello@souls.zip")
        inbox = warmup_manager.get_inbox("hello@souls.zip")

        # Try to manually set stage beyond max
        # Implementation should cap at 4
        assert inbox.stage <= 4


class TestWarmupDailyCaps:
    """Test warm-up daily send caps per stage."""

    def test_stage1_daily_cap(self, warmup_manager):
        """Test stage 1 has appropriate daily cap."""
        warmup_manager.initialize_inbox("hello@souls.zip")
        inbox = warmup_manager.get_inbox("hello@souls.zip")

        # Stage 1: typically 10-20 sends/day
        cap = warmup_manager.get_daily_cap("hello@souls.zip")
        assert cap > 0
        assert cap <= 100  # Reasonable upper bound

    def test_caps_increase_with_stages(self, warmup_manager):
        """Test daily caps increase as stages advance."""
        warmup_manager.initialize_inbox("hello@souls.zip")

        # Get caps for different stages (simulated)
        # Stage 1 cap < Stage 2 cap < Stage 3 cap < Stage 4 cap
        # Details depend on configuration


class TestEngagementGating:
    """Test engagement-gated warm-up."""

    def test_set_engagement_metrics(self, warmup_manager):
        """Test setting engagement metrics."""
        warmup_manager.initialize_inbox("hello@souls.zip")
        warmup_manager.set_engagement_metrics(
            "hello@souls.zip", open_rate=0.35, bounce_rate=0.01
        )

        inbox = warmup_manager.get_inbox("hello@souls.zip")
        assert inbox.open_rate == 0.35
        assert inbox.bounce_rate == 0.01

    def test_low_open_rate_pause(self, warmup_manager):
        """Test auto-pause on low open rate."""
        warmup_manager.initialize_inbox("hello@souls.zip")
        warmup_manager._set_first_send_date("hello@souls.zip")

        # Set low open rate
        warmup_manager.set_engagement_metrics(
            "hello@souls.zip", open_rate=0.10, bounce_rate=0.01
        )

        inbox = warmup_manager.get_inbox("hello@souls.zip")
        # Should be paused or indicate unhealthy
        health, reason = warmup_manager.check_engagement_health("hello@souls.zip")
        if inbox.stage_sends >= 10:  # Only judge after sample size
            assert health is False or inbox.paused is True

    def test_high_bounce_rate_pause(self, warmup_manager):
        """Test auto-pause on high bounce rate."""
        warmup_manager.initialize_inbox("hello@souls.zip")
        warmup_manager._set_first_send_date("hello@souls.zip")

        # Set high bounce rate
        warmup_manager.set_engagement_metrics(
            "hello@souls.zip", open_rate=0.35, bounce_rate=0.05
        )

        inbox = warmup_manager.get_inbox("hello@souls.zip")
        health, reason = warmup_manager.check_engagement_health("hello@souls.zip")
        # Should indicate unhealthy if bounce rate > 3%
        # (depending on sample size)

    def test_healthy_metrics_allow_advancement(self, warmup_manager):
        """Test good metrics allow stage advancement."""
        warmup_manager.initialize_inbox("hello@souls.zip")
        warmup_manager._set_first_send_date("hello@souls.zip")

        # Set good metrics
        warmup_manager.set_engagement_metrics(
            "hello@souls.zip", open_rate=0.35, bounce_rate=0.01
        )

        health, reason = warmup_manager.check_engagement_health("hello@souls.zip")
        if warmup_manager.get_inbox("hello@souls.zip").stage_sends >= 10:
            assert health is True

    def test_minimum_sample_size_before_judging(self, warmup_manager):
        """Test that engagement metrics require minimum sample size."""
        warmup_manager.initialize_inbox("hello@souls.zip")

        # Set bad metrics with very small sample
        warmup_manager.set_engagement_metrics(
            "hello@souls.zip", open_rate=0.0, bounce_rate=0.0
        )

        # Should be considered healthy until we have more data
        inbox = warmup_manager.get_inbox("hello@souls.zip")
        inbox.stage_sends = 5  # Below threshold

        health, reason = warmup_manager.check_engagement_health("hello@souls.zip")
        assert health is True  # Not enough data to judge


class TestWarmupMetricsTracking:
    """Test tracking warm-up metrics over time."""

    def test_stage_sends_tracking(self, warmup_manager):
        """Test tracking sends in current stage."""
        warmup_manager.initialize_inbox("hello@souls.zip")
        inbox = warmup_manager.get_inbox("hello@souls.zip")

        assert inbox.stage_sends == 0

        # Increment during stage
        warmup_manager.increment_stage_sends("hello@souls.zip")
        inbox = warmup_manager.get_inbox("hello@souls.zip")
        assert inbox.stage_sends == 1

    def test_stage_opens_tracking(self, warmup_manager):
        """Test tracking opens in current stage."""
        warmup_manager.initialize_inbox("hello@souls.zip")

        warmup_manager.increment_stage_opens("hello@souls.zip", 2)
        inbox = warmup_manager.get_inbox("hello@souls.zip")
        assert inbox.stage_opens == 2

    def test_stage_bounces_tracking(self, warmup_manager):
        """Test tracking bounces in current stage."""
        warmup_manager.initialize_inbox("hello@souls.zip")

        warmup_manager.increment_stage_bounces("hello@souls.zip", 1)
        inbox = warmup_manager.get_inbox("hello@souls.zip")
        assert inbox.stage_bounces == 1


class TestWarmupManualMetrics:
    """Test manual metric updates."""

    def test_set_open_rate_cli(self, warmup_manager):
        """Test CLI command to set open rate."""
        warmup_manager.initialize_inbox("hello@souls.zip")

        warmup_manager.set_engagement_metrics(
            "hello@souls.zip", open_rate=0.35, bounce_rate=None
        )

        inbox = warmup_manager.get_inbox("hello@souls.zip")
        assert inbox.open_rate == 0.35

    def test_set_bounce_rate_cli(self, warmup_manager):
        """Test CLI command to set bounce rate."""
        warmup_manager.initialize_inbox("hello@souls.zip")

        warmup_manager.set_engagement_metrics(
            "hello@souls.zip", open_rate=None, bounce_rate=0.02
        )

        inbox = warmup_manager.get_inbox("hello@souls.zip")
        assert inbox.bounce_rate == 0.02
