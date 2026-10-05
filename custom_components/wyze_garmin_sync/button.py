"""Manual synchronization button."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WyzeGarminCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the integration-wide manual sync button."""
    coordinator: WyzeGarminCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WyzeGarminSyncButton(coordinator, entry.entry_id)])


class WyzeGarminSyncButton(ButtonEntity):
    """Trigger an immediate latest-reading sync for all profiles."""

    _attr_name = "Sync now"
    _attr_icon = "mdi:sync"

    def __init__(
        self,
        coordinator: WyzeGarminCoordinator,
        entry_id: str,
    ) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry_id}_sync_now"

    async def async_press(self) -> None:
        """Request a fresh latest-reading sync."""
        try:
            await self.coordinator.async_sync_now()
        except Exception as err:
            _LOGGER.exception("Manual Wyze/Garmin synchronization failed")
            raise HomeAssistantError(
                f"Unable to synchronize Wyze with Garmin: {err}"
            ) from err
