"""Tests for validation module."""

import pytest

from fameclaw.validation import (
    normalize_email,
    validate_campaign_id,
    validate_can_spam,
    validate_email,
)
from fameclaw.exceptions import OutreachError, TemplateValidationError, ValidationError


class TestEmailNormalization:
    """Test email normalization."""

    def test_normalize_whitespace(self):
        """Test normalization of whitespace."""
        assert normalize_email("  ALICE@EXAMPLE.COM  ") == "alice@example.com"

    def test_normalize_case(self):
        """Test lowercasing."""
        assert normalize_email("ALICE@EXAMPLE.COM") == "alice@example.com"
        assert normalize_email("Alice@Example.Com") == "alice@example.com"

    def test_normalize_both(self):
        """Test both whitespace and case normalization."""
        assert normalize_email("  ALICE@EXAMPLE.COM  ") == "alice@example.com"

    def test_already_normalized(self):
        """Test email already normalized."""
        assert normalize_email("alice@example.com") == "alice@example.com"


class TestEmailValidation:
    """Test email validation."""

    def test_valid_email(self):
        """Test valid email addresses."""
        valid_emails = [
            "alice@example.com",
            "bob.smith@example.co.uk",
            "charlie+tag@example.org",
            "dave_jones@sub.example.com",
        ]
        for email in valid_emails:
            assert validate_email(email) is True

    def test_invalid_email_format(self):
        """Test invalid email formats."""
        invalid_emails = [
            "alice",
            "@example.com",
            "alice@",
            "alice @example.com",
            "alice@example",
            "alice@@example.com",
        ]
        for email in invalid_emails:
            with pytest.raises(OutreachError):
                validate_email(email)

    def test_invalid_email_empty(self):
        """Test empty email."""
        with pytest.raises(ValidationError):
            validate_email("")


class TestCampaignIDValidation:
    """Test campaign ID validation."""

    def test_valid_campaign_ids(self):
        """Test valid campaign ID formats."""
        valid_ids = [
            "campaign-001",
            "test_campaign",
            "abc123",
            "promo-2024-q1",
            "a1b2c3d4e5f6g7h8",
        ]
        for cid in valid_ids:
            assert validate_campaign_id(cid) is True

    def test_invalid_campaign_ids(self):
        """Test invalid campaign ID formats."""
        invalid_ids = [
            "-campaign",  # starts with dash
            "_campaign",  # starts with underscore
            "campaign#001",  # invalid char
            "Campaign",  # uppercase
            "ca",  # too short (min 3)
            "a" * 51,  # too long (max 50)
            "campaign!",  # invalid char
            "campaign 001",  # space
        ]
        for cid in invalid_ids:
            with pytest.raises(ValidationError):
                validate_campaign_id(cid)

    def test_campaign_id_error_message(self):
        """Test campaign ID error messages are helpful."""
        try:
            validate_campaign_id("Invalid ID!")
        except ValidationError as e:
            assert "valid" in str(e).lower()
            assert "example" in str(e).lower()


# CAN-SPAM validation tests disabled - CAN-SPAM enforcement removed per spec
# class TestCanSpamValidation:
#     """Test CAN-SPAM compliance validation."""
#
#     def test_can_spam_compliant(self):
#         """Test compliant email body."""
#         body = """
# Hello there,
#
# This is a test message about something interesting.
#
# You can unsubscribe by replying STOP to this email.
#
# Best regards,
# souls.zip | Brooklyn, NY
# """
#         assert validate_can_spam(body, "souls.zip | Brooklyn, NY") is True
#
#     def test_can_spam_missing_physical_address(self):
#         """Test missing physical address."""
#         body = """
# Hello there,
#
# This is a test message.
#
# To unsubscribe, reply STOP.
# """
#         violations = validate_can_spam(body, "souls.zip | Brooklyn, NY")
#         assert violations is not True
#         assert any("physical address" in v.lower() for v in violations)
#
#     def test_can_spam_missing_unsubscribe(self):
#         """Test missing unsubscribe mechanism."""
#         body = """
# Hello there,
#
# This is a test message.
#
# Best regards,
# souls.zip | Brooklyn, NY
# """
#         violations = validate_can_spam(body, "souls.zip | Brooklyn, NY")
#         assert violations is not True
#         assert any("unsubscribe" in v.lower() for v in violations)
#
#     def test_can_spam_missing_both(self):
#         """Test missing both physical address and unsubscribe."""
#         body = "Hello there, this is a test message."
#         violations = validate_can_spam(body, "souls.zip | Brooklyn, NY")
#         assert violations is not True
#         assert len(violations) == 2
#
#     def test_can_spam_unsubscribe_variants(self):
#         """Test various unsubscribe mechanism formats."""
#         physical = "souls.zip | Brooklyn, NY"
#
#         bodies = [
#             "To unsubscribe, reply STOP\n\nsheels\nsouls.zip | Brooklyn, NY",
#             "Click to unsubscribe\n\nsouls.zip | Brooklyn, NY",
#             "To opt out, reply STOP\n\nsouls.zip | Brooklyn, NY",
#             "To opt-out, click here\n\nsouls.zip | Brooklyn, NY",
#             "reply stop to unsubscribe\n\nsouls.zip | Brooklyn, NY",
#         ]
#
#         for body in bodies:
#             assert validate_can_spam(body, physical) is True


# CAN-SPAM config validation tests disabled - CAN-SPAM enforcement removed per spec
# class TestCanSpamConfigValidation:
#     """Test CAN-SPAM validation at campaign creation."""
#
#     def test_campaign_creation_missing_address(self, sample_campaign_config):
#         """Test campaign creation fails if config missing address."""
#         # Config without physical_address should be caught
#         from fameclaw.campaigner import CampaignManager
#         from fameclaw.models import OutreachConfig
#
#         config = OutreachConfig(
#             from_inbox="hello@souls.zip",
#             physical_address="",  # Empty
#             daily_cap=50,
#         )
#
#         # This should fail validation
#         with pytest.raises(ValidationError):
#             # Attempting to validate campaign without physical address
#             validate_can_spam("test body", "")
#
#     def test_campaign_template_missing_unsubscribe(
#         self, temp_templates_dir, sample_campaign_config
#     ):
#         """Test campaign template missing unsubscribe."""
#         from pathlib import Path
#
#         # Create template without unsubscribe
#         bad_template = Path(temp_templates_dir) / "bad.txt"
#         bad_template.write_text("Hello {{ name }}, here is content.\n\nsouls.zip")
#
#         # Validation should catch this
#         with pytest.raises(ValidationError):
#             validate_can_spam(bad_template.read_text(), "souls.zip")
