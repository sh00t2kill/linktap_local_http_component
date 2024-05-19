import asyncio
import json
import logging
import random

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.valve import ValveEntity, ValveEntityFeature
from homeassistant.const import (ATTR_ENTITY_ID, CONF_ENTITY_ID,
                                 SERVICE_TURN_OFF, SERVICE_TURN_ON, STATE_OFF,
                                 STATE_ON)
from homeassistant.core import callback, Event, EventStateChangedData
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import *
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (CoordinatorEntity,
                                                      DataUpdateCoordinator)
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

from .const import ATTR_STATE, DOMAIN, GW_IP, MANUFACTURER, NAME, TAP_ID


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
            "switch": self.switch_entity,
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
    def name(self):
        return f"{MANUFACTURER} {self._name}"

    @property
    def switch_entity(self):
        name = self._name.replace(" ", "_")
        name = name.replace("-", "_")
        return f"switch.{DOMAIN}_{name}".lower()

    async def async_open_valve(self, **kwargs):
        """Open the valve."""
        await self.hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: self.switch_entity},
            blocking=True,
            context=self._context,
        )
        await self.coordinator.async_request_refresh()

    async def async_close_valve(self, **kwargs):
        """Close valve."""
        await self.hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: self.switch_entity},
            blocking=True,
            context=self._context,
        )
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self):
        return self._attrs

    @callback
    def async_state_changed_listener(
        self, event: Event[EventStateChangedData] | None = None
    ) -> None:
        """Handle child updates."""
        super().async_state_changed_listener(event)
        if (
            not self.available
            or (state := self.hass.states.get(self.switch_entity)) is None
        ):
            return

        self._attr_is_closed = self._attrs[ATTR_STATE] != STATE_ON

    @property
    def state(self):
        status = self.coordinator.data
        self._attrs[ATTR_STATE] = status[ATTR_STATE]
        state = "unknown"
        if status[ATTR_STATE]:
            state = "open"
        elif not status[ATTR_STATE]:
            state = "closed"
            _LOGGER.debug(f"Valve {self.name} state {state}")
        self._attr_is_closed = state != "open"
        return state

    @property
    def device_info(self) -> DeviceInfo:
        return self._attr_device_info

    async def _pause_tap(self, hours=False):
        if not hours:
            hours = 1
        _LOGGER.debug(f"Pausing {self.entity_id} for {hours} hours")
        gw_id = self.coordinator.get_gw_id()
        await self.coordinator.tap_api.pause_tap(gw_id, self.tap_id, hours)
        await self.coordinator.async_request_refresh()

    async def _start_watering(self, seconds=False):
        if not seconds or seconds == 0:
            seconds = 1439 * 60
        _LOGGER.debug(f"Starting watering via service call for {seconds} seconds")
        gw_id = self.coordinator.get_gw_id()
        await self.coordinator.tap_api.turn_on(gw_id, self.tap_id, seconds)
        await self.coordinator.async_request_refresh()
