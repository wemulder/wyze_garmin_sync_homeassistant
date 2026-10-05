"""Coordinator for scheduled and user-triggered Wyze/Garmin synchronization."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from . import api
from .const import (
    CONF_GARMIN_ACCOUNTS,
    CONF_WYZE_API_KEY,
    CONF_WYZE_EMAIL,
    CONF_WYZE_KEY_ID,
    CONF_WYZE_PASSWORD,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
_WYZE_API_KEY_URL = "https://developer-api-console.wyze.com/#/apikey/view"


def _async_notify_sync_failure(
    hass: HomeAssistant,
    notification_id: str,
    message: str,
) -> None:
    """Create or update one persistent notification for an integration failure."""
    persistent_notification.async_create(
        hass,
        message,
        title="Wyze Garmin Sync failed",
        notification_id=notification_id,
    )


def _async_clear_sync_failure(hass: HomeAssistant, notification_id: str) -> None:
    """Dismiss the integration failure notification after a successful sync."""
    persistent_notification.async_dismiss(hass, notification_id)


class WyzeGarminCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch latest Wyze readings and upload new ones to mapped Garmin accounts."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
        )
        self.entry = entry
        self._notification_id = f"{DOMAIN}_{entry.entry_id}_sync_failure"
        self.token_root = hass.config.path(".storage", DOMAIN)
        self._upload_store = Store(
            hass,
            1,
            f"{DOMAIN}_{entry.entry_id}_uploaded",
        )
        self._profile_store = Store(
            hass,
            1,
            f"{DOMAIN}_{entry.entry_id}_profiles",
        )
        self._uploaded: dict[str, str] | None = None
        self._cached_profiles: dict[str, dict[str, Any]] | None = None
        self._last_refresh_error: str | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh measurements and upload unseen latest records."""
        if self._uploaded is None:
            self._uploaded = await self._upload_store.async_load() or {}
        if self._cached_profiles is None:
            self._cached_profiles = await self._profile_store.async_load() or {}

        data = self.entry.data
        token_file = api.wyze_token_file(self.token_root)
        try:
            client, devices = await self.hass.async_add_executor_job(
                api.get_wyze_client,
                data[CONF_WYZE_EMAIL],
                data[CONF_WYZE_PASSWORD],
                data[CONF_WYZE_KEY_ID],
                data[CONF_WYZE_API_KEY],
                token_file,
            )
            profiles = await self.hass.async_add_executor_job(
                api.latest_measurements,
                client,
                devices,
            )
        except Exception as err:
            self._last_refresh_error = (
                f"{type(err).__name__}: {err}"
            )
            _LOGGER.exception("Unable to refresh Wyze scale data")
            _async_notify_sync_failure(
                self.hass,
                self._notification_id,
                "Unable to retrieve the latest Wyze readings. "
                f"Error: {type(err).__name__}: {err}\n\n"
                "Check the integration logs and confirm your Wyze credentials "
                "and API key are current. Wyze API keys expire after one year; "
                f"manage or renew the key at {_WYZE_API_KEY_URL}, then use "
                "the integration's Reconfigure option.",
            )
            raise UpdateFailed("Unable to retrieve the latest Wyze readings") from err
        self._last_refresh_error = None

        for profile_id, cached in self._cached_profiles.items():
            current = profiles.get(profile_id)
            if current is None or not current["measurement_id"]:
                profiles[profile_id] = {**cached, "_record": None}

        sync_errors: dict[str, str] = {}
        uploaded_count = 0
        accounts = self.entry.options.get(CONF_GARMIN_ACCOUNTS, {})
        for profile_id, measurement in profiles.items():
            if not measurement["measurement_id"]:
                continue
            account = accounts.get(profile_id)
            if not account:
                continue
            if self._uploaded.get(profile_id) == measurement["measurement_id"]:
                continue
            if measurement.get("_record") is None:
                sync_errors[profile_id] = (
                    "Wyze no longer provides this reading for upload; "
                    "a new measurement is required."
                )
                continue
            token_dir = api.profile_token_dir(self.token_root, profile_id)
            try:
                await self.hass.async_add_executor_job(
                    self._upload_measurement,
                    account,
                    token_dir,
                    measurement["_record"],
                )
            except Exception as err:
                _LOGGER.exception(
                    "Garmin synchronization failed for Wyze profile %s",
                    profile_id,
                )
                sync_errors[profile_id] = (
                    f"{type(err).__name__}: {err}"
                )
                continue
            self._uploaded[profile_id] = measurement["measurement_id"]
            await self._upload_store.async_save(self._uploaded)
            uploaded_count += 1

        public_profiles = {
            profile_id: {
                key: value
                for key, value in profile.items()
                if key != "_record"
            }
            for profile_id, profile in profiles.items()
        }
        self._cached_profiles = public_profiles
        await self._profile_store.async_save(public_profiles)
        _LOGGER.info(
            "Wyze Garmin sync completed: %d profile readings available, "
            "%d new Garmin uploads, %d profile errors",
            sum(bool(profile["measurement_id"]) for profile in public_profiles.values()),
            uploaded_count,
            len(sync_errors),
        )
        if sync_errors:
            errors = "\n".join(
                f"- Wyze profile {profile_id}: {error}"
                for profile_id, error in sync_errors.items()
            )
            _async_notify_sync_failure(
                self.hass,
                self._notification_id,
                "One or more Garmin uploads failed:\n"
                f"{errors}\n\n"
                "Check the integration logs and the Garmin account mapping.",
            )
        else:
            _async_clear_sync_failure(self.hass, self._notification_id)
        return {"profiles": public_profiles, "sync_errors": sync_errors}

    @staticmethod
    def _upload_measurement(
        account: dict[str, str],
        token_dir: str,
        record: Any,
    ) -> None:
        """Upload the latest record associated with a profile."""
        garmin = api.get_garmin_client(account, token_dir)
        api.upload_record_to_garmin(record, garmin)

    async def async_sync_now(self) -> None:
        """Run a manual synchronization and propagate errors to the caller."""
        await self.async_refresh()
        if self.last_update_success is False:
            detail = self._last_refresh_error or "See the integration log for details."
            raise UpdateFailed(f"Wyze refresh failed: {detail}")
        if self.data and self.data.get("sync_errors"):
            errors = self.data["sync_errors"]
            details = "; ".join(
                f"{profile_id}: {error}" for profile_id, error in errors.items()
            )
            raise UpdateFailed(f"Garmin sync failed: {details}")
