import asyncio
import json
import logging

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity import *
from homeassistant.helpers.update_coordinator import (CoordinatorEntity,
                                                      DataUpdateCoordinator)

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN, TAP_ID, GW_ID, NAME

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

        ha_name = self._name.lower().replace(" ", "_")
        self._attr_unique_id = f"linktap_local_switch_{ha_name}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifers={
                (DOMAIN, hass.data[DOMAIN]["conf"][TAP_ID])
            },
            name=hass.data[DOMAIN]["conf"][NAME],
            manufacturer="Linktap"
        )
        _LOGGER.debug(self._attr_device_info)

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def name(self):
        return f"Linktap {self._name}"

    async def async_turn_on(self, **kwargs):
        attributes = await self.tap_api.turn_on(self._id, self._gw_id)
        await self.coordinator.async_request_refresh()


    async def async_turn_off(self, **kwargs):
        attributes = await self.tap_api.turn_off(self._id, self._gw_id)
        await self.coordinator.async_request_refresh()

    @property
    def state(self):
        status = self.coordinator.data
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
