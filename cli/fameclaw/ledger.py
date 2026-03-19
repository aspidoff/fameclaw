"""
All outreach state in one place: send history, suppression, warm-up, bounces.
Single JSON file, single source of truth.
"""

from datetime import datetime, timedelta
from .state import StateManager

STATE_FILE = "outreach.json"

# Warm-up stages: (max_day, daily_cap)
WARMUP_STAGES = [(14, 15), (28, 30), (56, 50), (None, 100)]


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _today() -> str:
    return datetime.utcnow().date().isoformat()


class Ledger:
    """All outreach state: sends, suppression, warm-up, bounces."""

    def __init__(self, state_dir: str = "~/.openclaw/outreach"):
        self.sm = StateManager(state_dir)

    def _load(self) -> dict:
        data = self.sm.read(STATE_FILE)
        data.setdefault("sends", [])
        data.setdefault("suppressed", {})
        data.setdefault("domains", {})
        data.setdefault("config", {
            "cooldown_days": 30,
            "default_from": "lacie@souls.zip",
            "provider": "agentmail",
            "smtp_host": "",
            "smtp_port": 587,
            "smtp_user": "",
            "smtp_pass_env": "",
        })
        return data

    def _save(self, data: dict) -> None:
        self.sm.write(STATE_FILE, data)

    # ── Config ──────────────────────────────────────────────

    def get_config(self) -> dict:
        return self._load()["config"]

    def set_config(self, key: str, value) -> None:
        data = self._load()
        # Type coercion
        if key in ("cooldown_days", "smtp_port"):
            value = int(value)
        data["config"][key] = value
        self._save(data)

    # ── Sends ───────────────────────────────────────────────

    def record_send(self, to: str, tag: str, message_id: str = "", status: str = "sent") -> None:
        data = self._load()
        data["sends"].append({
            "to": to.lower().strip(),
            "tag": tag,
            "message_id": message_id,
            "status": status,
            "sent_at": _now(),
        })
        self._save(data)

    def is_duped(self, to: str, tag: str) -> bool:
        """Already sent to this person in this batch?"""
        to = to.lower().strip()
        data = self._load()
        return any(
            s["to"] == to and s["tag"] == tag and s["status"] in ("sent", "sending")
            for s in data["sends"]
        )

    def recently_contacted(self, to: str, days: int = None) -> list[str]:
        """Tags that contacted this person within cooldown window."""
        to = to.lower().strip()
        data = self._load()
        if days is None:
            days = data["config"].get("cooldown_days", 30)
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
        return list({
            s["tag"] for s in data["sends"]
            if s["to"] == to and s["sent_at"] >= cutoff and s["status"] in ("sent", "sending")
        })

    def history(self, to: str) -> list[dict]:
        to = to.lower().strip()
        data = self._load()
        return [s for s in data["sends"] if s["to"] == to]

    def sends_today(self) -> int:
        today = _today()
        data = self._load()
        return sum(1 for s in data["sends"] if s["sent_at"].startswith(today) and s["status"] == "sent")

    def total_sends(self) -> int:
        data = self._load()
        return len(data["sends"])

    # ── Suppression ─────────────────────────────────────────

    def suppress(self, email: str, reason: str = "manual") -> None:
        email = email.lower().strip()
        data = self._load()
        data["suppressed"][email] = {"reason": reason, "added_at": _now()}
        self._save(data)

    def unsuppress(self, email: str) -> bool:
        email = email.lower().strip()
        data = self._load()
        if email in data["suppressed"]:
            del data["suppressed"][email]
            self._save(data)
            return True
        return False

    def is_suppressed(self, email: str) -> tuple[bool, str]:
        """Returns (suppressed, reason)."""
        email = email.lower().strip()
        data = self._load()
        entry = data["suppressed"].get(email)
        if entry:
            return True, entry["reason"]
        return False, ""

    def suppressed_list(self) -> dict:
        return self._load()["suppressed"]

    def suppressed_count(self) -> int:
        return len(self._load()["suppressed"])

    # ── Domain warm-up + bounce tracking ────────────────────

    def _get_domain(self, domain: str) -> dict:
        data = self._load()
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
            self._save(data)
        d = data["domains"][domain]
        # Reset daily counter if new day
        if d.get("sends_today_date") != _today():
            d["sends_today"] = 0
            d["sends_today_date"] = _today()
            self._save(data)
        return d

    def domain_stage(self, domain: str) -> tuple[int, int]:
        """Returns (stage_number, daily_cap)."""
        d = self._get_domain(domain)
        first = datetime.fromisoformat(d["first_send"]).date()
        days = (datetime.utcnow().date() - first).days
        for i, (max_day, cap) in enumerate(WARMUP_STAGES, 1):
            if max_day is None or days <= max_day:
                return i, cap
        return 4, 100

    def check_domain_health(self, domain: str) -> tuple[bool, str]:
        """Returns (ok, reason). ok=False means halt sending."""
        d = self._get_domain(domain)
        if d.get("paused"):
            return False, d.get("pause_reason", "paused")
        total = d.get("total_sends", 0)
        hard = d.get("hard_bounces", 0)
        if total >= 10 and hard / total >= 0.05:
            return False, f"Hard bounce rate {hard}/{total} ({hard/total:.0%}) >= 5%"
        return True, ""

    def record_domain_send(self, domain: str) -> None:
        data = self._load()
        d = data.setdefault("domains", {}).setdefault(domain, {
            "first_send": _today(), "sends_today": 0, "sends_today_date": _today(),
            "total_sends": 0, "hard_bounces": 0, "paused": False, "pause_reason": None,
        })
        if d.get("sends_today_date") != _today():
            d["sends_today"] = 0
            d["sends_today_date"] = _today()
        d["sends_today"] += 1
        d["total_sends"] += 1
        self._save(data)

    def domain_sends_today(self, domain: str) -> int:
        d = self._get_domain(domain)
        return d.get("sends_today", 0)

    def domain_info(self) -> list[dict]:
        """All domains with stage info."""
        data = self._load()
        result = []
        for domain, d in data.get("domains", {}).items():
            stage, cap = self.domain_stage(domain)
            ok, reason = self.check_domain_health(domain)
            result.append({
                "domain": domain,
                "stage": stage,
                "cap": cap,
                "today": d.get("sends_today", 0),
                "total": d.get("total_sends", 0),
                "bounces": d.get("hard_bounces", 0),
                "ok": ok,
                "status": "OK" if ok else reason,
                "paused": d.get("paused", False),
            })
        return result
