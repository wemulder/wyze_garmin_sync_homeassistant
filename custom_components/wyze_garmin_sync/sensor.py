"""Sensor platform for latest Wyze scale readings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_MANUFACTURER, DOMAIN
from .coordinator import WyzeGarminCoordinator


@dataclass(frozen=True)
class Metric:
    """Metadata for a Wyze body-composition sensor."""

    key: str
    label: str
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None


METRICS = (
    Metric(
        "weight",
        "Weight",
        UnitOfMass.POUNDS,
        SensorDeviceClass.WEIGHT,
        SensorStateClass.MEASUREMENT,
    ),
    Metric(
        "body_fat",
        "Body Fat",
        PERCENTAGE,
        None,
        SensorStateClass.MEASUREMENT,
    ),
    Metric(
        "body_water",
        "Body Water",
        PERCENTAGE,
        None,
        SensorStateClass.MEASUREMENT,
    ),
    Metric(
        "bone_mineral",
        "Bone Mass",
        UnitOfMass.KILOGRAMS,
        SensorDeviceClass.WEIGHT,
        SensorStateClass.MEASUREMENT,
    ),
    Metric(
        "muscle",
        "Muscle Mass",
        UnitOfMass.KILOGRAMS,
        SensorDeviceClass.WEIGHT,
        SensorStateClass.MEASUREMENT,
    ),
    Metric("bmr", "Basal Metabolic Rate", "kcal/d", None, SensorStateClass.MEASUREMENT),
    Metric("metabolic_age", "Metabolic Age", "y", None, SensorStateClass.MEASUREMENT),
    Metric("body_vfr", "Visceral Fat Rating", None, None, SensorStateClass.MEASUREMENT),
    Metric("bmi", "BMI", "kg/m²", None, SensorStateClass.MEASUREMENT),
    Metric("body_type", "Physique Rating", None, None, SensorStateClass.MEASUREMENT),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up profile sensors and add newly discovered profiles."""
    coordinator: WyzeGarminCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def add_new_profiles() -> None:
        profiles = coordinator.data.get("profiles", {}) if coordinator.data else {}
        entities = []
        for profile_id, profile in profiles.items():
            if profile_id in known:
                continue
            known.add(profile_id)
            entities.extend(
                WyzeProfileSensor(coordinator, entry.entry_id, profile_id, metric)
                for metric in METRICS
            )
        if entities:
            async_add_entities(entities)

    add_new_profiles()
    entry.async_on_unload(coordinator.async_add_listener(add_new_profiles))


class WyzeProfileSensor(SensorEntity):
    """Latest measurement sensor for one Wyze profile."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WyzeGarminCoordinator,
        entry_id: str,
        profile_id: str,
        metric: Metric,
    ) -> None:
        self.coordinator = coordinator
        self.entry_id = entry_id
        self.profile_id = profile_id
        self.metric = metric
        self._attr_unique_id = f"{entry_id}_{profile_id}_{metric.key}"
        self._attr_name = metric.label
        self._attr_native_unit_of_measurement = metric.unit
        self._attr_device_class = metric.device_class
        self._attr_state_class = metric.state_class

    @property
    def device_info(self) -> DeviceInfo:
        profile = self.coordinator.data["profiles"][self.profile_id]
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_{self.profile_id}")},
            manufacturer=DEFAULT_MANUFACTURER,
            name=profile["name"],
            model="Scale profile",
        )

    @property
    def native_value(self) -> float | None:
        profile = self.coordinator.data.get("profiles", {}).get(self.profile_id, {})
        return profile.get(self.metric.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        profile = self.coordinator.data.get("profiles", {}).get(self.profile_id, {})
        attributes = {
            "profile_id": self.profile_id,
            "measurement_id": profile.get("measurement_id"),
            "last_measurement": profile.get("timestamp"),
        }
        sync_error = self.coordinator.data.get("sync_errors", {}).get(self.profile_id)
        if sync_error:
            attributes["sync_error"] = sync_error
        return attributes

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.profile_id in self.coordinator.data.get("profiles", {})
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
