import asyncio
import json
import logging

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity import *
from homeassistant.helpers.update_coordinator import (CoordinatorEntity,
                                                      DataUpdateCoordinator)
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN, TAP_ID, GW_ID, NAME, DEFAULT_TIME

async def async_setup_platform(
    hass, config, async_add_entities, discovery_info=None
):
    """Setup the switch platform."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([LinktapSwitch(coordinator, hass)], True)

class LinktapSwitch(CoordinatorEntity, SwitchEntity):
    def __init__(self, coordinator: DataUpdateCoordinator, hass):
        super().__init__(coordinator)
        self._state = None
        self._name = hass.data[DOMAIN]["conf"][NAME]
        #self._id = hass.data[DOMAIN]["conf"][TAP_ID]
        self._id = self._name
        self._gw_id = hass.data[DOMAIN]["conf"][GW_ID]
        self.tap_id = hass.data[DOMAIN]["conf"][TAP_ID]
        self.entity_id = DOMAIN + "." + self._id
        self.tap_api = coordinator.tap_api
        self.platform = "switch"
        self.hass = hass
        self._attr_unique_id = slugify(f"{DOMAIN}_{self.platform}_{self.tap_id}")
        self._attr_device_info = self.coordinator.get_device()
        self._attrs = {
            "data": self.coordinator.data,
            "duration_entity": self.duration_entity
        }

        #self.duration_entity = f"number.{DOMAIN}_{self._name}_watering_duration"

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def name(self):
        return f"Linktap {self._name}"

    @property
    def duration_entity(self):
        name = self._name.replace(" ", "_")
        return f"number.{DOMAIN}_{name}_watering_duration".lower()

    async def async_turn_on(self, **kwargs):
        duration = self.get_watering_duration()
        seconds = int(float(duration)) * 60
        attributes = await self.tap_api.turn_on(self._gw_id, self.tap_id, seconds)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        attributes = await self.tap_api.turn_off(self._gw_id, self.tap_id)
        await self.coordinator.async_request_refresh()

    def get_watering_duration(self):
        entity = self.hass.states.get(self.duration_entity)
        if not entity:
            _LOGGER.debug(f"Entity {self.duration_entity} not found -- setting default")
            duration = DEFAULT_TIME
            self._attrs['Default Time'] = True
        elif entity.state == STATE_UNKNOWN:
            _LOGGER.debug(f"Entity {self.duration_entity} state unknown -- setting default")
            duration = DEFAULT_TIME
            self._attrs['Default Time'] = True
        else:
            duration = entity.state
            self._attrs['Default Time'] = False
        self._attrs['Watering Duration'] = duration
        return duration

    @property
    def extra_state_attributes(self):
        return self._attrs

    @property
    def state(self):
        status = self.coordinator.data
        duration = self.get_watering_duration()
        _LOGGER.debug(f"Set duration:{duration}")
        self._attrs["is_watering"] = status["is_watering"]
        state = "unknown"
        if status["is_watering"]:
            state = "on"
        elif not status["is_watering"]:
            state = "off"
        return state

    @property
    def is_on(self):
        return self.state()

    @property
    def device_info(self) -> DeviceInfo:
        return self._attr_device_info
