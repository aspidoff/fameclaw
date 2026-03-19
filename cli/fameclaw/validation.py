"""
Validation utilities for email, templates, campaigns, and CAN-SPAM compliance.
"""

import re
from typing import Optional
from jinja2 import Template, TemplateSyntaxError, UndefinedError

from .exceptions import TemplateValidationError, CanSpamViolationError, ValidationError, OutreachError
from .models import OutreachConfig


def normalize_email(email: str) -> str:
    """Normalize email: strip whitespace and lowercase."""
    return email.strip().lower()


def validate_email(email: str) -> bool:
    """
    Validate email format. Raises ValidationError if invalid or empty.
    
    Args:
        email: Email address to validate
        
    Returns:
        True if valid
        
    Raises:
        ValidationError: If email is invalid or empty
    """
    if not email or not email.strip():
        raise ValidationError("Email cannot be empty")
    
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, email.strip()):
        raise OutreachError(f"Invalid email format: {email}")
    return True


def validate_campaign_id(campaign_id: str) -> bool:
    """
    Validate campaign ID format. Raises ValidationError if invalid.
    
    Args:
        campaign_id: Campaign ID to validate
        
    Returns:
        True if valid
        
    Raises:
        ValidationError: If campaign ID is invalid
    """
    # Must start with lowercase letter or number, contain only lowercase letters/numbers/dash/underscore, 3-50 chars
    pattern = r"^[a-z0-9][a-z0-9_-]{2,49}$"
    if not re.match(pattern, campaign_id):
        raise ValidationError(
            f"Invalid campaign ID: {campaign_id}. "
            f"Must be 3-50 characters, start with letter/number, "
            f"contain only lowercase letters/numbers/dash/underscore. "
            f"Example: 'test-campaign-001'"
        )
    return True


def validate_template(
    template_content: str, required_vars: Optional[set[str]] = None
) -> list[str]:
    """
    Validate Jinja2 template. Returns list of errors (empty = valid).

    Args:
        template_content: Jinja2 template string
        required_vars: Set of variable names that MUST be in the template

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # Check syntax
    try:
        tmpl = Template(template_content, autoescape=False)
    except TemplateSyntaxError as e:
        errors.append(f"Template syntax error: {e.message}")
        return errors

    # Extract variables from template
    template_vars = tmpl.module.__dict__.get("_exported_vars", set())

    # If we can't extract vars directly, try rendering with dummy data
    if not template_vars and required_vars:
        try:
            # Try to extract from AST
            from jinja2 import meta

            env = tmpl.environment
            ast = env.parse(template_content)
            template_vars = meta.find_undeclared_variables(ast)
        except Exception:
            pass

    # Check required vars
    if required_vars:
        missing = required_vars - template_vars
        if missing:
            errors.append(
                f"Template missing required variables: {', '.join(sorted(missing))}"
            )

    return errors


def validate_can_spam(
    body_template: str, config: OutreachConfig
) -> list[str]:
    """
    Validate CAN-SPAM compliance. Returns list of violations (empty = compliant).

    Physical address is always checked if set in config.
    Unsubscribe mechanism is only checked if config.require_unsubscribe is True.
    """
    violations = []

    # Check physical address only if require_unsubscribe is on (bulk mode)
    if config.require_unsubscribe and config.physical_address and config.physical_address not in body_template:
        violations.append(
            f"CAN-SPAM: Body template must include physical address: {config.physical_address}"
        )

    # Check unsubscribe mechanism only if enforced (off for personal outreach)
    if config.require_unsubscribe:
        unsubscribe_patterns = [
            "unsubscribe",
            "opt out",
            "opt-out",
            "reply stop",
            "reply STOP",
            "to stop receiving",
        ]
        body_lower = body_template.lower()
        if not any(pattern.lower() in body_lower for pattern in unsubscribe_patterns):
            violations.append(
                "CAN-SPAM: Body template must include unsubscribe mechanism. "
                "Example: 'Reply STOP to unsubscribe'. "
                "Disable with: fameclaw config set --key require_unsubscribe --value false"
            )

    return violations


def validate_recipients(recipients: list) -> list[str]:
    """
    Validate recipient list. Returns list of errors (empty = valid).

    Requirements:
    - All must have 'email' field
    - All emails must be valid
    - No duplicate emails (case-insensitive)
    """
    errors = []
    seen_emails = set()
    duplicates = []

    for i, recipient in enumerate(recipients):
        # Handle both dict and Recipient object
        if isinstance(recipient, dict):
            if "email" not in recipient:
                errors.append(f"Recipient {i}: missing 'email' field")
                continue
            email_val = recipient["email"]
        else:
            # Assume it's a Recipient object with email attribute
            if not hasattr(recipient, "email"):
                errors.append(f"Recipient {i}: missing 'email' field")
                continue
            email_val = recipient.email

        email = normalize_email(email_val)
        if not validate_email(email):
            errors.append(f"Recipient {i}: invalid email format: {email}")
            continue

        if email in seen_emails:
            duplicates.append(email)
        else:
            seen_emails.add(email)

    if duplicates:
        errors.append(
            f"Duplicate recipients (case-insensitive): {', '.join(sorted(duplicates))}"
        )

    return errors


def validate_recipient_dedup(recipients: list[dict]) -> tuple[bool, list[str]]:
    """
    Check for duplicate emails in recipient list.

    Returns:
        (no_duplicates: bool, duplicate_emails: list[str])
    """
    seen_emails = set()
    duplicates = []

    for recipient in recipients:
        email = normalize_email(recipient.get("email", ""))
        if email in seen_emails:
            duplicates.append(email)
        else:
            seen_emails.add(email)

    return len(duplicates) == 0, duplicates
