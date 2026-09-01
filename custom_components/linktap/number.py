import asyncio
import logging
import random

from homeassistant.components.number import RestoreNumber
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.entity import *
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

from .const import (
    CONF_MAX_WATERING_DURATION,
    CONF_MAX_WATERING_VOLUME,
    CONF_WATERING_SAFETY_LIMITS,
    DEFAULT_TIME,
    DEFAULT_VOL,
    DOMAIN,
    GW_ID,
    GW_IP,
    MANUFACTURER,
    NAME,
    NATIVE_MAX_WATERING_DURATION,
    NATIVE_MAX_WATERING_VOLUME,
    TAP_ID,
)


def _safety_limits(config, tap_id):
    return config.options.get(CONF_WATERING_SAFETY_LIMITS, {}).get(tap_id, {})


async def async_setup_entry(hass, config, async_add_entities, discovery_info=None):
    """Setup the number platform."""
    taps = hass.data[DOMAIN][config.entry_id]["conf"]["taps"]
    numbers = []
    for tap in taps:
        coordinator = tap["coordinator"]
        limits = _safety_limits(config, tap[TAP_ID])
        numbers.append(
            LinktapNumber(
                coordinator, hass, tap, "Watering duration", "mdi:clock", "m",
                safety_max=limits.get(CONF_MAX_WATERING_DURATION),
            )
        )
        numbers.append(
            LinktapNumber(
                coordinator, hass, tap, "Watering volume", "mdi:water",
                hass.data[DOMAIN][config.entry_id]["conf"]["vol_unit"],
                safety_max=limits.get(CONF_MAX_WATERING_VOLUME),
            )
        )
        numbers.append(
            LinktapPauseDurationNumber(
                coordinator, hass, tap, "Pause Duration Water Plan",
                "mdi:timer-pause", "h"
            )
        )
    async_add_entities(numbers, True)


class LinktapNumber(CoordinatorEntity, RestoreNumber):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: DataUpdateCoordinator, hass, tap, number_suffix,
        icon, unit_of_measurement, safety_max=None
    ):
        super().__init__(coordinator)
        self._state = None
        self._name = tap[NAME]
        self._id = self._name
        self.tap_id = tap[TAP_ID]
        self.platform = "number"
        self._attr_unique_id = slugify(
            f"{DOMAIN}_{self.platform}_{self.tap_id}_{number_suffix.replace(' ', '_')}"
        )
        self._attr_name = number_suffix
        self._attr_native_min_value = 0
        self._attr_native_max_value = NATIVE_MAX_WATERING_DURATION
        self._attr_native_step = 5

        if number_suffix == "Watering volume":
            self._attr_native_max_value = NATIVE_MAX_WATERING_VOLUME
            self._attr_native_step = 10

        if safety_max is not None:
            self._attr_native_max_value = min(
                float(safety_max), self._attr_native_max_value
            )

        self._attr_native_unit_of_measurement = unit_of_measurement
        self._attr_icon = icon
        self.number_suffix = number_suffix
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tap[TAP_ID])},
            name=tap[NAME],
            manufacturer=MANUFACTURER,
            model=tap[TAP_ID],
            configuration_url="http://" + tap[GW_IP] + "/",
        )
        self._attrs = {}
        if safety_max is not None:
            self._attrs["safety_maximum"] = self._attr_native_max_value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        restored_number = await self.async_get_last_number_data()
        if restored_number is not None and restored_number.native_value != STATE_UNKNOWN:
            restored = float(restored_number.native_value)
            restored = max(
                self._attr_native_min_value,
                min(restored, self._attr_native_max_value),
            )
            _LOGGER.debug(f"Restoring value to {restored}")
            self._attr_native_value = restored
        else:
            _LOGGER.debug("No value found to restore -- setting default")
            default_value = DEFAULT_VOL if self.number_suffix == "Watering volume" else DEFAULT_TIME
            self._attr_native_value = min(default_value, self._attr_native_max_value)
        self.async_write_ha_state()

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def extra_state_attributes(self):
        return self._attrs

    @property
    def device_info(self) -> DeviceInfo:
        return self._attr_device_info

    async def async_set_native_value(self, value: float) -> None:
        value = max(
            self._attr_native_min_value,
            min(float(value), self._attr_native_max_value),
        )
        self._attr_native_value = value
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class LinktapPauseDurationNumber(CoordinatorEntity, RestoreNumber):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, hass, tap, number_suffix, icon, unit_of_measurement):
        super().__init__(coordinator)
        self._state = None
        self._name = tap[NAME]
        self.tap_id = tap[TAP_ID]
        self.platform = "number"
        self._attr_unique_id = slugify(
            f"{DOMAIN}_{self.platform}_{self.tap_id}_pause_duration"
        )
        self._attr_name = number_suffix
        self._attr_native_min_value = 1
        self._attr_native_max_value = 240
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = unit_of_measurement
        self._attr_icon = icon
        self.number_suffix = number_suffix
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tap[TAP_ID])},
            name=tap[NAME],
            manufacturer=MANUFACTURER,
            model=tap[TAP_ID],
            configuration_url="http://" + tap[GW_IP] + "/",
        )
        self._attrs = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        restored_number = await self.async_get_last_number_data()
        if restored_number is not None and restored_number.native_value != STATE_UNKNOWN:
            _LOGGER.debug(f"Restoring pause duration value to {restored_number.native_value}")
            self._attr_native_value = restored_number.native_value
        else:
            _LOGGER.debug("No pause duration value found to restore -- setting default to 24")
            self._attr_native_value = 24
        self.async_write_ha_state()

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def extra_state_attributes(self):
        return self._attrs

    @property
    def device_info(self) -> DeviceInfo:
        return self._attr_device_info

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
