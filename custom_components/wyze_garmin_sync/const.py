"""Integration constants."""

from datetime import time

DOMAIN = "wyze_garmin_sync"

CONF_WYZE_EMAIL = "wyze_email"
CONF_WYZE_PASSWORD = "wyze_password"
CONF_WYZE_KEY_ID = "wyze_key_id"
CONF_WYZE_API_KEY = "wyze_api_key"
CONF_SYNC_TIME = "sync_time"
CONF_GARMIN_ACCOUNTS = "garmin_accounts"

DEFAULT_SYNC_TIME = "07:00:00"
DEFAULT_MANUFACTURER = "Wyze"


def parse_sync_time(value: str) -> time:
    """Parse the configured daily sync time."""
    return time.fromisoformat(value)
