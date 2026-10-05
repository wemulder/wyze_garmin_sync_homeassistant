"""Wyze Scale to Garmin Connect Home Assistant integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from .const import CONF_SYNC_TIME, DEFAULT_SYNC_TIME, DOMAIN, parse_sync_time
from .coordinator import WyzeGarminCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML (not supported)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Wyze Garmin Sync from a config entry."""
    sync_time = parse_sync_time(
        entry.options.get(CONF_SYNC_TIME, DEFAULT_SYNC_TIME)
    )
    coordinator = WyzeGarminCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    @callback
    async def _async_daily_sync(_now: datetime) -> None:
        await coordinator.async_refresh()

    entry.async_on_unload(
        async_track_time_change(
            hass,
            _async_daily_sync,
            hour=sync_time.hour,
            minute=sync_time.minute,
            second=sync_time.second,
        )
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
