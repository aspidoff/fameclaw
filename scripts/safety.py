#!/usr/bin/env python3
"""FameClaw Safety Gates — Bounce monitoring, cooldown, suppression, atomic state.

Zero external dependencies. Uses stdlib fcntl for file locking.

Usage (from outreach.py):
    from safety import SafetyGates
    gates = SafetyGates()

    # Before sending:
    blocked, reason = gates.check(email, domain)
    if blocked:
        print(f"Blocked: {reason}")

    # After sending:
    gates.record_send(email, domain, campaign="my-campaign")

    # On bounce:
    gates.record_bounce(email, domain, hard=True)

    # Manual suppression:
    gates.suppress(email, reason="unsubscribed")
    gates.unsuppress(email)
"""

import fcntl
import json
import os
import random
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# Warm-up stages: (days_from_first_send, (min_cap, max_cap))
# Day 1-3: 30-40/day, Day 4-7: 40-50/day, Day 8-11: 55-70/day, Day 12+: 85-100/day
# Actual daily cap is randomized within range each day for natural sending patterns
WARMUP_STAGES = [
    (3, (30, 40)),
    (7, (40, 50)),
    (11, (55, 70)),
    (None, (85, 100)),
]

STATE_DIR = Path.home() / ".config" / "fameclaw"
STATE_FILE = "safety_state.json"
COOLDOWN_DAYS = 30
BOUNCE_HALT_RATE = 0.03  # 3%
BOUNCE_MIN_SENDS = 10     # Need at least this many sends before checking rate


def _now():
    return datetime.utcnow().isoformat() + "Z"


def _today():
    return datetime.utcnow().date().isoformat()


class _LockedFile:
    """Context manager for locked JSON file read/write using fcntl."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = None

    def __enter__(self):
        # Open or create the file
        if not self.path.exists():
            self.path.write_text("{}")
            self.path.chmod(0o600)

        self._fd = open(self.path, "r+")
        fcntl.flock(self._fd, fcntl.LOCK_EX)

        content = self._fd.read()
        try:
            self.data = json.loads(content) if content.strip() else {}
        except json.JSONDecodeError:
            self.data = {}

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            # Atomic write: write to temp file, then replace
            dir_path = self.path.parent
            fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as tmp:
                    json.dump(self.data, tmp, indent=2)
                os.replace(tmp_path, str(self.path))
            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

        fcntl.flock(self._fd, fcntl.LOCK_UN)
        self._fd.close()
        return False


class SafetyGates:
    """Pre-send safety checks: bounce rate, cooldown, suppression, warm-up."""

    def __init__(self, state_dir=None):
        self.state_dir = Path(state_dir) if state_dir else STATE_DIR
        self.state_path = self.state_dir / STATE_FILE

    def _open(self):
        """Returns a locked file context manager."""
        return _LockedFile(self.state_path)

    def _ensure_schema(self, data):
        """Ensure all required keys exist."""
        data.setdefault("suppressed", {})
        data.setdefault("send_log", [])
        data.setdefault("domains", {})
        return data

    # ── Main gate check ──────────────────────────────────────

    def check(self, email, domain=None, campaign=None):
        """Check all safety gates before sending.

        Args:
            email: recipient email
            domain: sending domain (for bounce/warm-up checks)
            campaign: current campaign name. If provided, cooldown only blocks
                      if the email was contacted by a DIFFERENT campaign.
                      Follow-ups within the same campaign are always allowed.

        Returns (blocked: bool, reason: str).
        blocked=False means clear to send.
        """
        email = email.lower().strip()
        if domain is None:
            domain = email.split("@")[-1] if "@" in email else "unknown"

        with self._open() as f:
            data = self._ensure_schema(f.data)

            # 1. Suppression
            if email in data["suppressed"]:
                reason = data["suppressed"][email].get("reason", "suppressed")
                return True, f"Suppressed ({reason})"

            # 2. Cooldown — contacted within last N days by OTHER campaigns
            #    Same-campaign follow-ups are not blocked.
            cutoff = (datetime.utcnow() - timedelta(days=COOLDOWN_DAYS)).isoformat() + "Z"
            recent_campaigns = [
                s["campaign"] for s in data["send_log"]
                if s["email"] == email and s["sent_at"] >= cutoff
                and (campaign is None or s["campaign"] != campaign)
            ]
            if recent_campaigns:
                return True, f"Contacted by other campaign(s) in last {COOLDOWN_DAYS} days ({', '.join(set(recent_campaigns))})"

            # 3. Bounce rate
            dom = data["domains"].get(domain, {})
            total = dom.get("total_sends", 0)
            hard_bounces = dom.get("hard_bounces", 0)
            if total >= BOUNCE_MIN_SENDS and hard_bounces / total >= BOUNCE_HALT_RATE:
                rate = hard_bounces / total
                return True, f"Domain {domain} bounce rate {rate:.1%} >= {BOUNCE_HALT_RATE:.0%} ({hard_bounces}/{total}) — sending halted"

            # 4. Domain paused manually
            if dom.get("paused"):
                return True, f"Domain {domain} paused: {dom.get('pause_reason', 'unknown')}"

            # 5. Warm-up cap
            dom = self._ensure_domain(data, domain)
            stage, cap = self._get_stage(dom)
            today_sends = dom.get("sends_today", 0) if dom.get("sends_today_date") == _today() else 0
            if today_sends >= cap:
                return True, f"Daily warm-up cap reached ({today_sends}/{cap}, stage {stage})"

        return False, ""

    # ── Recording ────────────────────────────────────────────

    def record_send(self, email, domain=None, campaign="default"):
        """Record a successful send."""
        email = email.lower().strip()
        if domain is None:
            domain = email.split("@")[-1] if "@" in email else "unknown"

        with self._open() as f:
            data = self._ensure_schema(f.data)

            # Send log
            data["send_log"].append({
                "email": email,
                "domain": domain,
                "campaign": campaign,
                "sent_at": _now(),
            })

            # Domain tracking
            dom = self._ensure_domain(data, domain)
            if dom.get("sends_today_date") != _today():
                dom["sends_today"] = 0
                dom["sends_today_date"] = _today()
            dom["sends_today"] += 1
            dom["total_sends"] += 1

    def record_bounce(self, email, domain=None, hard=True):
        """Record a bounce. Hard bounces count toward halt rate."""
        email = email.lower().strip()
        if domain is None:
            domain = email.split("@")[-1] if "@" in email else "unknown"

        with self._open() as f:
            data = self._ensure_schema(f.data)
            dom = self._ensure_domain(data, domain)

            if hard:
                dom["hard_bounces"] = dom.get("hard_bounces", 0) + 1
                # Auto-suppress hard bounced emails
                data["suppressed"][email] = {
                    "reason": "hard_bounce",
                    "added_at": _now(),
                }

    # ── Suppression ──────────────────────────────────────────

    def suppress(self, email, reason="manual"):
        """Add email to global suppression list."""
        email = email.lower().strip()
        with self._open() as f:
            data = self._ensure_schema(f.data)
            data["suppressed"][email] = {
                "reason": reason,
                "added_at": _now(),
            }

    def unsuppress(self, email):
        """Remove email from suppression list. Returns True if was suppressed."""
        email = email.lower().strip()
        with self._open() as f:
            data = self._ensure_schema(f.data)
            if email in data["suppressed"]:
                del data["suppressed"][email]
                return True
        return False

    def suppressed_list(self):
        """Return dict of suppressed emails."""
        with self._open() as f:
            data = self._ensure_schema(f.data)
            return dict(data["suppressed"])

    # ── Domain management ────────────────────────────────────

    def pause_domain(self, domain, reason="manual"):
        """Pause all sending for a domain."""
        with self._open() as f:
            data = self._ensure_schema(f.data)
            dom = self._ensure_domain(data, domain)
            dom["paused"] = True
            dom["pause_reason"] = reason

    def unpause_domain(self, domain):
        """Resume sending for a domain."""
        with self._open() as f:
            data = self._ensure_schema(f.data)
            dom = self._ensure_domain(data, domain)
            dom["paused"] = False
            dom["pause_reason"] = None

    def domain_status(self):
        """Return status of all tracked domains."""
        with self._open() as f:
            data = self._ensure_schema(f.data)
            result = []
            for domain, dom in data.get("domains", {}).items():
                stage, cap = self._get_stage(dom)
                total = dom.get("total_sends", 0)
                bounces = dom.get("hard_bounces", 0)
                rate = bounces / total if total > 0 else 0
                today = dom.get("sends_today", 0) if dom.get("sends_today_date") == _today() else 0
                result.append({
                    "domain": domain,
                    "stage": stage,
                    "cap": cap,
                    "today": today,
                    "total": total,
                    "bounces": bounces,
                    "bounce_rate": f"{rate:.1%}",
                    "paused": dom.get("paused", False),
                    "ok": not dom.get("paused") and (total < BOUNCE_MIN_SENDS or rate < BOUNCE_HALT_RATE),
                })
            return result

    # ── Stats ────────────────────────────────────────────────

    def stats(self):
        """Quick stats summary."""
        with self._open() as f:
            data = self._ensure_schema(f.data)
            return {
                "total_sends": len(data["send_log"]),
                "suppressed": len(data["suppressed"]),
                "domains_tracked": len(data["domains"]),
            }

    # ── Internal ─────────────────────────────────────────────

    def _ensure_domain(self, data, domain):
        """Ensure domain tracking entry exists."""
        if domain not in data["domains"]:
            data["domains"][domain] = {
                "first_send": _today(),
                "sends_today": 0,
                "sends_today_date": _today(),
                "total_sends": 0,
                "hard_bounces": 0,
                "paused": False,
                "pause_reason": None,
            }
        dom = data["domains"][domain]
        # Reset daily counter on new day
        if dom.get("sends_today_date") != _today():
            dom["sends_today"] = 0
            dom["sends_today_date"] = _today()
        return dom

    def _get_stage(self, dom):
        """Get warm-up stage and daily cap for a domain.

        Cap is randomized within the stage's range, seeded by domain + date
        so it's consistent within a single day but varies day to day.
        """
        first = dom.get("first_send", _today())
        try:
            days = (datetime.utcnow().date() - datetime.fromisoformat(first).date()).days
        except (ValueError, TypeError):
            days = 0

        for i, (max_day, cap_range) in enumerate(WARMUP_STAGES, 1):
            if max_day is None or days <= max_day:
                # Seed with domain + date for deterministic daily cap
                domain = dom.get("first_send", "default")
                seed = hash(f"{domain}:{_today()}")
                rng = random.Random(seed)
                cap = rng.randint(cap_range[0], cap_range[1])
                return i, cap
        last_range = WARMUP_STAGES[-1][1]
        seed = hash(f"fallback:{_today()}")
        rng = random.Random(seed)
        return len(WARMUP_STAGES), rng.randint(last_range[0], last_range[1])


# ── CLI for manual operations ────────────────────────────────

if __name__ == "__main__":
    import sys

    gates = SafetyGates()

    if len(sys.argv) < 2:
        print("Usage: python3 safety.py <command> [args]")
        print("Commands: check, suppress, unsuppress, suppressed, domains, stats, pause, unpause")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "check" and len(sys.argv) >= 3:
        email = sys.argv[2]
        blocked, reason = gates.check(email)
        if blocked:
            print(f"❌ BLOCKED: {reason}")
        else:
            print(f"✅ Clear to send to {email}")

    elif cmd == "suppress" and len(sys.argv) >= 3:
        email = sys.argv[2]
        reason = sys.argv[3] if len(sys.argv) > 3 else "manual"
        gates.suppress(email, reason)
        print(f"✅ Suppressed {email} ({reason})")

    elif cmd == "unsuppress" and len(sys.argv) >= 3:
        email = sys.argv[2]
        if gates.unsuppress(email):
            print(f"✅ Unsuppressed {email}")
        else:
            print(f"  {email} was not suppressed")

    elif cmd == "suppressed":
        entries = gates.suppressed_list()
        if not entries:
            print("No suppressed emails.")
        else:
            print(f"Suppressed ({len(entries)}):")
            for email, e in sorted(entries.items()):
                print(f"  {email} — {e['reason']} ({e.get('added_at', '?')[:10]})")

    elif cmd == "domains":
        domains = gates.domain_status()
        if not domains:
            print("No domains tracked yet.")
        else:
            print(f"{'Domain':<30} {'Stage':<6} {'Today':<10} {'Total':<6} {'Bounces':<8} {'Status'}")
            print("-" * 85)
            for d in domains:
                status = "OK" if d["ok"] else ("PAUSED" if d["paused"] else f"BOUNCE {d['bounce_rate']}")
                today_cap = f"{d['today']}/{d['cap']}"
                print(f"{d['domain']:<30} {d['stage']:<6} {today_cap:<10} {d['total']:<6} {d['bounces']:<8} {status}")

    elif cmd == "pause" and len(sys.argv) >= 3:
        domain = sys.argv[2]
        reason = sys.argv[3] if len(sys.argv) > 3 else "manual"
        gates.pause_domain(domain, reason)
        print(f"✅ Paused {domain} ({reason})")

    elif cmd == "unpause" and len(sys.argv) >= 3:
        domain = sys.argv[2]
        gates.unpause_domain(domain)
        print(f"✅ Unpaused {domain}")

    elif cmd == "stats":
        s = gates.stats()
        print(f"Total sends: {s['total_sends']} | Suppressed: {s['suppressed']} | Domains: {s['domains_tracked']}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
