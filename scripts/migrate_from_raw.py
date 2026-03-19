#!/usr/bin/env python3
"""
Migration script: Import March 19 history from outreach_state.json into fameclaw ledger.

Usage:
  python scripts/migrate_from_raw.py
"""

import json
from pathlib import Path
from datetime import datetime
import sys

def migrate():
    """Migrate outreach_state.json to fameclaw ledger format."""
    
    # Read source data
    source_file = Path("~/Projects/fameclaw-souls-zip/outreach_state.json").expanduser()
    if not source_file.exists():
        print(f"Error: {source_file} not found")
        sys.exit(1)

    with open(source_file, "r") as f:
        source_data = json.load(f)

    contacts = source_data.get("contacts", {})
    print(f"Loaded {len(contacts)} contacts from {source_file}")

    # Add sys.path for imports
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from fameclaw.ledger import LedgerManager
    from fameclaw.suppressor import SuppressionManager
    from fameclaw.warmup import WarmupManager
    from fameclaw.validation import normalize_email

    ledger_mgr = LedgerManager()
    suppressor = SuppressionManager()
    warmup_mgr = WarmupManager()

    # Track stats
    imported = 0
    skipped = 0

    # Campaign ID for this batch
    campaign_id = "fameclaw-youtube-2026-03-19"
    first_send_date = "2026-03-19"

    # Initialize warm-up for souls.zip domain
    warmup_mgr.get_or_create("souls.zip", first_send_date=first_send_date)

    # Process each contact - contacts is a dict keyed by email
    for email_key, contact in contacts.items():
        email = normalize_email(email_key)
        message_id = contact.get("message_id")

        if not email:
            skipped += 1
            continue

        # Create ledger entry
        try:
            # Assume all were sent successfully (based on message_id presence)
            status = "sent" if message_id else "sending"

            ledger_mgr.add_entry(
                campaign_id=campaign_id,
                recipient_email=email,
                message_id=message_id or f"migrated-{email}",
                status=status,
            )
            imported += 1

        except Exception as e:
            print(f"Warning: Failed to import {email}: {e}")
            skipped += 1

    # Seed suppression list
    suppressor.add(
        email="davidfortincpa@davidpba.com",
        reason="explicit_opt_out",
        added_by="migration",
    )

    # Set physical address in config
    from fameclaw.config import ConfigManager

    config_mgr = ConfigManager()
    config_mgr.set_value("physical_address", "souls.zip | Brooklyn, NY")

    print(f"\n✓ Migration complete:")
    print(f"  Imported: {imported} contacts")
    print(f"  Skipped: {skipped}")
    print(f"  Campaign: {campaign_id}")
    print(f"  Warm-up initialized for: souls.zip (first send: {first_send_date})")
    print(f"  Suppression seeded: davidfortincpa@davidpba.com (explicit opt-out)")
    print(f"  Physical address set: souls.zip | Brooklyn, NY")


if __name__ == "__main__":
    migrate()
