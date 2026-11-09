import asyncio
import json
import logging
import random

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.valve import ValveEntity, ValveEntityFeature
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import *
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

from .const import ATTR_STATE, DOMAIN, GW_IP, MANUFACTURER, NAME, TAP_ID

ENHANCED_PAUSE_MIN_HOURS = 0.01
ENHANCED_PAUSE_MAX_HOURS = 240.0
PAUSE_MODE_OPTIONS = {
    "keep_end_time": 0,
    "complete_duration": 1,
}


def _switch_entity_id(hass, tap_id):
    """Resolve the LinkTap switch by stable unique ID, not generated entity ID."""
    unique_id = slugify(f"{DOMAIN}_switch_{tap_id}")
    return er.async_get(hass).async_get_entity_id(
        SWITCH_DOMAIN, DOMAIN, unique_id
    )


async def async_setup_entry(
    hass, config, async_add_entities, discovery_info=None
):
    """Initialize Valve """
    taps = hass.data[DOMAIN][config.entry_id]["conf"]["taps"]
    valves = []
    for tap in taps:
        coordinator = tap["coordinator"]
        _LOGGER.debug(f"Configuring valve for tap {tap}")
        valves.append(LinktapValve(coordinator, hass, tap))
    async_add_entities(valves, True)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service("pause_valve",
        {vol.Required("hours", default=1): vol.Coerce(int)},
        "_pause_tap"
        )
    platform.async_register_entity_service("start_watering",
        {vol.Required("seconds", default=9000): vol.Coerce(int)},
        "_start_watering"
        )
    platform.async_register_entity_service(
        "pause_current_watering",
        {
            vol.Required("hours", default=1): vol.All(
                vol.Coerce(float),
                vol.Range(min=ENHANCED_PAUSE_MIN_HOURS, max=ENHANCED_PAUSE_MAX_HOURS),
            ),
            vol.Required("mode", default="keep_end_time"): vol.In(PAUSE_MODE_OPTIONS),
        },
        "_pause_current_watering",
    )
    platform.async_register_entity_service(
        "resume_current_watering",
        {},
        "_resume_current_watering",
    )


class LinktapValve(CoordinatorEntity, ValveEntity):
    # Modern HA naming: this is a main feature of the device.
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: DataUpdateCoordinator, hass, tap):
        super().__init__(coordinator)
        self._state = None
        self._name = tap[NAME]
        self.tap_id = tap[TAP_ID]
        self.platform = "valve"
        self.hass = hass
        self._attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
        self._attr_reports_position = False
        self._attr_unique_id = slugify(f"{DOMAIN}_{self.platform}_{self.tap_id}")
        self._attrs = {
            "data": self.coordinator.data,
        }
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, tap[TAP_ID])
            },
            name=tap[NAME],
            manufacturer=MANUFACTURER,
            configuration_url="http://" + tap[GW_IP] + "/"
        )

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def switch_entity(self):
        return _switch_entity_id(self.hass, self.tap_id)

    def _require_switch_entity(self):
        entity_id = self.switch_entity
        if entity_id is None:
            raise HomeAssistantError(
                f"Unable to resolve LinkTap switch entity for tap {self.tap_id}"
            )
        return entity_id

    async def async_open_valve(self, **kwargs):
        """Open the valve."""
        switch_entity = self._require_switch_entity()
        await self.hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: switch_entity},
            blocking=True,
            context=self._context,
        )
        await self.coordinator.async_request_refresh()

    async def async_close_valve(self, **kwargs):
        """Close valve."""
        await self.coordinator.async_safe_stop_watering()
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self):
        # Resolve dynamically so HA/user entity-id renames are followed.
        self._attrs["switch"] = self.switch_entity
        return self._attrs

    @property
    def is_closed(self):
        watering = self.coordinator.watering_state
        return None if watering is None else not watering

    @property
    def state(self):
        status = self.coordinator.data
        self._attrs["data"] = status
        watering = self.coordinator.watering_state
        self._attrs[ATTR_STATE] = watering
        return "unknown" if watering is None else ("open" if watering else "closed")

    @property
    def device_info(self) -> DeviceInfo:
        return self._attr_device_info

    async def _pause_tap(self, hours=None):
        if hours is None:
            hours = 1
        _LOGGER.debug(f"Pausing {self.entity_id} for {hours} hours")
        await self.coordinator.async_set_water_plan_pause(hours)

    async def _pause_current_watering(self, hours=1, mode="keep_end_time"):
        """Pause the current session through the shared CMD19 operation."""
        if mode not in PAUSE_MODE_OPTIONS:
            raise HomeAssistantError(f"Unknown LinkTap pause mode: {mode}")
        await self.coordinator.async_pause_current_watering(hours, PAUSE_MODE_OPTIONS[mode])

    async def _resume_current_watering(self):
        """Resume the current session through the shared CMD19 operation."""
        await self.coordinator.async_resume_current_watering()

    async def _start_watering(self, seconds=9000):
        if not 3 <= seconds <= 86340:
            raise HomeAssistantError("Watering duration must be from 3 to 86340 seconds")
        _LOGGER.debug(f"Starting watering via service call for {seconds} seconds")
        await self.coordinator.async_start_watering(seconds)
        await self.coordinator.async_request_refresh()
