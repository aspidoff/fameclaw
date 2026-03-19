"""
Configuration loading and validation for fameclaw.
"""

from pathlib import Path
from .state import StateManager
from .models import OutreachConfig
from .exceptions import OutreachError


class ConfigManager:
    """Load and manage fameclaw configuration."""

    CONFIG_FILE = "config.json"

    def __init__(self, state_dir: str = "~/.openclaw/outreach"):
        """Initialize config manager."""
        self.state_manager = StateManager(state_dir)
        self.state_dir = Path(state_dir).expanduser()

    def load(self) -> OutreachConfig:
        """
        Load configuration from state directory.

        Returns:
            OutreachConfig object

        Raises:
            OutreachError if config is invalid
        """
        config_data = self.state_manager.read(self.CONFIG_FILE)

        # Provide defaults
        if not config_data:
            return self._get_defaults()

        try:
            config = OutreachConfig(
                version=config_data.get("version", 1),
                global_daily_cap=config_data.get("global_daily_cap", 50),
                default_hourly_cap=config_data.get("default_hourly_cap", 20),
                default_send_spacing_seconds=config_data.get(
                    "default_send_spacing_seconds", 30
                ),
                cross_campaign_cooldown_days=config_data.get(
                    "cross_campaign_cooldown_days", 30
                ),
                default_from_inbox=config_data.get("default_from_inbox", "lacie@souls.zip"),
                physical_address=config_data.get("physical_address", ""),
                require_unsubscribe=config_data.get("require_unsubscribe", False),
                all_times_utc=config_data.get("all_times_utc", True),
            )
            return config
        except Exception as e:
            raise OutreachError(f"Invalid configuration: {e}")

    def save(self, config: OutreachConfig) -> None:
        """
        Save configuration to state directory.

        Args:
            config: OutreachConfig object
        """
        config_data = {
            "version": config.version,
            "global_daily_cap": config.global_daily_cap,
            "default_hourly_cap": config.default_hourly_cap,
            "default_send_spacing_seconds": config.default_send_spacing_seconds,
            "cross_campaign_cooldown_days": config.cross_campaign_cooldown_days,
            "default_from_inbox": config.default_from_inbox,
            "physical_address": config.physical_address,
            "require_unsubscribe": config.require_unsubscribe,
            "all_times_utc": config.all_times_utc,
        }
        self.state_manager.write(self.CONFIG_FILE, config_data)

    def _get_defaults(self) -> OutreachConfig:
        """Get default configuration."""
        return OutreachConfig(
            version=1,
            global_daily_cap=50,
            default_hourly_cap=20,
            default_send_spacing_seconds=30,
            cross_campaign_cooldown_days=30,
            default_from_inbox="lacie@souls.zip",
            physical_address="",  # Must be set by user
            all_times_utc=True,
        )

    def set_value(self, key: str, value: str) -> None:
        """
        Set a configuration value.

        Args:
            key: Configuration key
            value: Value (will be converted based on type)

        Raises:
            OutreachError if key is unknown
        """
        config = self.load()

        # Convert value based on expected type
        if key == "version":
            setattr(config, key, int(value))
        elif key in ("global_daily_cap", "default_hourly_cap", "default_send_spacing_seconds",
                     "cross_campaign_cooldown_days"):
            setattr(config, key, int(value))
        elif key == "all_times_utc":
            setattr(config, key, value.lower() in ("true", "yes", "1"))
        elif key == "require_unsubscribe":
            setattr(config, key, value.lower() in ("true", "yes", "1"))
        elif key in ("default_from_inbox", "physical_address"):
            setattr(config, key, value)
        else:
            raise OutreachError(f"Unknown configuration key: {key}")

        self.save(config)

    def validate(self, config: OutreachConfig) -> list[str]:
        """
        Validate configuration. Returns list of errors (empty = valid).

        Args:
            config: OutreachConfig object

        Returns:
            List of error messages
        """
        errors = []

        if config.global_daily_cap <= 0:
            errors.append("global_daily_cap must be > 0")

        if config.default_hourly_cap <= 0:
            errors.append("default_hourly_cap must be > 0")

        if config.default_hourly_cap > config.global_daily_cap:
            errors.append("default_hourly_cap cannot exceed global_daily_cap")

        if config.cross_campaign_cooldown_days < 0:
            errors.append("cross_campaign_cooldown_days cannot be negative")

        if not config.default_from_inbox or "@" not in config.default_from_inbox:
            errors.append("default_from_inbox must be a valid email address")

        # physical_address is optional but recommended
        if not config.physical_address:
            errors.append(
                "WARNING: physical_address is required for CAN-SPAM compliance. "
                "Set it with: fameclaw config set --key physical_address --value \"<address>\""
            )

        return errors
