import asyncio
import json
import logging

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity import *
from homeassistant.helpers.update_coordinator import (CoordinatorEntity,
                                                      DataUpdateCoordinator)
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN, TAP_ID, GW_ID, NAME

async def async_setup_platform(
    hass, config, async_add_entities, discovery_info=None
):
    """Setup the sensor platform."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    binary_sensors = []
    binary_sensors.append(LinktapBinarySensor(coordinator, hass, "Is Linked", "is_rf_linked"))
    binary_sensors.append(LinktapBinarySensor(coordinator, hass, "Is Fall", "is_fall"))
    binary_sensors.append(LinktapBinarySensor(coordinator, hass, "Is CutOff", "is_cutoff"))
    binary_sensors.append(LinktapBinarySensor(coordinator, hass, "Is Leaking", "is_leak"))
    binary_sensors.append(LinktapBinarySensor(coordinator, hass, "Is Clogged", "is_clog"))
    binary_sensors.append(LinktapBinarySensor(coordinator, hass, "Is Broken", "is_broken"))
    async_add_entities(binary_sensors, True)

class LinktapBinarySensor(CoordinatorEntity, BinarySensorEntity):

    def __init__(self, coordinator: DataUpdateCoordinator, hass, name, data_attribute):
        super().__init__(coordinator)
        self._state = None
        self._name = hass.data[DOMAIN]["conf"][NAME] + " " + name
        self._id = self._name
        self._data_check_attribute = data_attribute
        self.tap_id = hass.data[DOMAIN]["conf"][TAP_ID]
        self.tap_name = hass.data[DOMAIN]["conf"][NAME]
        #self._name = name
        self._attrs = {}
        self.platform = "binary_sensor"

        self._attr_unique_id = slugify(f"{DOMAIN}_{self.platform}_{data_attribute}_{self.tap_id}")
        self._attr_device_info = self.coordinator.get_device()

    @property
    def unique_id(self):
        """Return the unique ID of the sensor."""
        return self._attr_unique_id

    @property
    def name(self):
        return f"Linktap {self._name}"

    @property
    def state(self):
        attributes = self.coordinator.data
        data_attr = attributes[self._data_check_attribute]
        state = "on" if data_attr else "off"
        return state

    @property
    def device_info(self) -> DeviceInfo:
        return self._attr_device_info