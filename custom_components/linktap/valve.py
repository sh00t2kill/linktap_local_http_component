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
    STATE_ON,
)
from homeassistant.core import Event, EventStateChangedData, callback
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
        switch_entity = self._require_switch_entity()
        await self.hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: switch_entity},
            blocking=True,
            context=self._context,
        )
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self):
        # Resolve dynamically so HA/user entity-id renames are followed.
        self._attrs["switch"] = self.switch_entity
        return self._attrs

    @callback
    def async_state_changed_listener(
        self, event: Event[EventStateChangedData] | None = None
    ) -> None:
        """Handle child updates."""
        super().async_state_changed_listener(event)
        switch_entity = self.switch_entity
        if (
            not self.available
            or switch_entity is None
            or (state := self.hass.states.get(switch_entity)) is None
        ):
            return

        self._attr_is_closed = state.state != STATE_ON

    @property
    def state(self):
        status = self.coordinator.data
        self._attrs["data"] = status
        self._attrs[ATTR_STATE] = status[ATTR_STATE]
        state = "unknown"
        if status[ATTR_STATE]:
            state = "open"
        elif not status[ATTR_STATE]:
            state = "closed"
            _LOGGER.debug(f"Valve {self.entity_id} state {state}")
        self._attr_is_closed = state != "open"
        return state

    @property
    def device_info(self) -> DeviceInfo:
        return self._attr_device_info

    async def _pause_tap(self, hours=None):
        if hours is None:
            hours = 1
        _LOGGER.debug(f"Pausing {self.entity_id} for {hours} hours")
        await self.coordinator.async_set_water_plan_pause(hours)

    async def _start_watering(self, seconds=False):
        if not seconds or seconds == 0:
            seconds = 1439 * 60
        _LOGGER.debug(f"Starting watering via service call for {seconds} seconds")
        gw_id = self.coordinator.get_gw_id()
        await self.coordinator.tap_api.turn_on(gw_id, self.tap_id, seconds)
        await self.coordinator.async_request_refresh()
