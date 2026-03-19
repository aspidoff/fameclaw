"""Shared test fixtures and configuration."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from datetime import datetime

import pytest

from fameclaw.models import (
    Campaign,
    CampaignConfig,
    Recipient,
    OutreachConfig,
    LedgerEntry,
    Ledger,
    SuppressionEntry,
    SuppressionList,
    BounceTracker,
    BounceState,
    WarmupState,
    InboxWarmup,
)
from fameclaw.ledger import LedgerManager
from fameclaw.suppressor import SuppressionManager
from fameclaw.warmup import WarmupManager
from fameclaw.bouncer import BounceManager
from fameclaw.templates import TemplateRenderer


@pytest.fixture
def temp_state_dir():
    """Create temporary state directory for tests."""
    tmpdir = tempfile.mkdtemp(prefix="fameclaw_test_")
    yield tmpdir
    # Cleanup
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def temp_templates_dir():
    """Create temporary templates directory."""
    tmpdir = tempfile.mkdtemp(prefix="fameclaw_templates_")
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def sample_config(temp_templates_dir):
    """Create a sample outreach config."""
    return OutreachConfig(
        version=1,
        global_daily_cap=50,
        default_hourly_cap=10,
        default_send_spacing_seconds=30,
        cross_campaign_cooldown_days=30,
        default_from_inbox="hello@souls.zip",
        physical_address="souls.zip | Brooklyn, NY",
    )


@pytest.fixture
def sample_campaign_config(temp_templates_dir):
    """Create a sample campaign config."""
    template_path = Path(temp_templates_dir) / "body.txt"
    template_path.write_text(
        """Hello {{ name }},

This is a test message with unsubscribe link.

If you wish to unsubscribe, reply STOP.

Best regards,
souls.zip | Brooklyn, NY
"""
    )

    return CampaignConfig(
        from_inbox="hello@souls.zip",
        subject_template="Hello {{ name }} from souls.zip",
        body_template_path=str(template_path),
    )


@pytest.fixture
def sample_recipients():
    """Create sample recipients."""
    return [
        Recipient(email="alice@example.com", display_name="Alice", personalization={"name": "Alice"}),
        Recipient(email="bob@example.com", display_name="Bob", personalization={"name": "Bob"}),
        Recipient(email="charlie@example.com", display_name="Charlie", personalization={"name": "Charlie"}),
    ]


@pytest.fixture
def sample_campaign(sample_campaign_config, sample_recipients):
    """Create a sample campaign."""
    campaign = Campaign(
        id="test-campaign-001",
        created_at=datetime.utcnow().isoformat(),
        status="draft",
        from_inbox="hello@souls.zip",
        subject_template="Hello {{ name }}",
        body_template_path=sample_campaign_config.body_template_path,
        config=sample_campaign_config,
    )

    for recipient in sample_recipients:
        campaign.recipients[recipient.email] = {
            "email": recipient.email,
            "display_name": recipient.display_name,
            "personalization": recipient.personalization,
            "status": "pending",
        }

    return campaign


@pytest.fixture
def ledger_manager(temp_state_dir):
    """Create a ledger manager with temp state dir."""
    return LedgerManager(temp_state_dir)


@pytest.fixture
def suppression_manager(temp_state_dir):
    """Create a suppression manager with temp state dir."""
    return SuppressionManager(temp_state_dir)


@pytest.fixture
def warmup_manager(temp_state_dir):
    """Create a warmup manager with temp state dir."""
    return WarmupManager(temp_state_dir)


@pytest.fixture
def bounce_manager(temp_state_dir):
    """Create a bounce manager with temp state dir."""
    return BounceManager(temp_state_dir)


@pytest.fixture
def template_renderer(temp_templates_dir):
    """Create a template renderer."""
    return TemplateRenderer(temp_templates_dir)


@pytest.fixture
def sample_ledger_entry():
    """Create a sample ledger entry."""
    return LedgerEntry(
        campaign_id="test-campaign-001",
        recipient_email="alice@example.com",
        message_id="msg_12345",
        sent_at=datetime.utcnow().isoformat(),
        status="sent",
    )


@pytest.fixture
def sample_suppression_entry():
    """Create a sample suppression entry."""
    return SuppressionEntry(
        email="suppressed@example.com",
        reason="hard_bounce",
        added_at=datetime.utcnow().isoformat(),
    )
