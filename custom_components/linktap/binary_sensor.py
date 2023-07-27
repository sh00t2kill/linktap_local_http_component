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

from .const import DOMAIN, TAP_ID, GW_ID, NAME, GW_IP

#async def async_setup_platform(
async def async_setup_entry(
    hass, config, async_add_entities, discovery_info=None
):
    """Setup the sensor platform."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    taps = hass.data[DOMAIN]["conf"]["taps"]
    binary_sensors = []
    for tap in taps:
        #binary_sensors = []
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, name="Is Linked", data_attribute="is_rf_linked"))
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, data_attribute="is_fall", icon="mdi:meter-electric-outline"))
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, data_attribute="is_cutoff", icon="mdi:scissors-cutting"))
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, name="Is Leaking", data_attribute="is_leak", icon="mdi:leak"))
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, name="Is Clogged", data_attribute="is_clog",  icon="mdi:leak-off"))
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, data_attribute="is_broken", icon="mdi:scissors-cutting"))
    async_add_entities(binary_sensors, True)

class LinktapBinarySensor(CoordinatorEntity, BinarySensorEntity):

    def __init__(self, coordinator: DataUpdateCoordinator, hass, tap, data_attribute, name=False, device_class=False, icon=False):
        super().__init__(coordinator)
        self._state = None
        if not name:
            name = data_attribute.replace("_", " ").title()
        self._name = tap[NAME] + " " + name
        self._id = self._name
        self._data_check_attribute = data_attribute
        self.tap_id = tap[TAP_ID]
        self.tap_name = tap[NAME]
        self.platform = "binary_sensor"
        self._attr_unique_id = slugify(f"{DOMAIN}_{self.platform}_{data_attribute}_{self.tap_id}")
        if device_class:
            self._attr_device_class = device_class
        if icon:
            self._attr_icon = icon
        self._attrs = {}
        self._attr_device_info = DeviceInfo(
            #entry_type=DeviceEntryType.SERVICE,
            identifiers={
                (DOMAIN, tap[TAP_ID])
            },
            name=tap[NAME],
            manufacturer="Linktap",
            model=tap[TAP_ID],
            configuration_url="http://" + hass.data[DOMAIN]["conf"][GW_IP] + "/"
        )

    @property
    def unique_id(self):
        """Return the unique ID of the sensor."""
        return self._attr_unique_id

    @property
    def name(self):
        return f"Linktap {self._name}"

    @property
    def extra_state_attributes(self):
        return self._attrs

    @property
    def state(self):
        attributes = self.coordinator.data
        data_attr = attributes[self._data_check_attribute]
        state = "on" if data_attr else "off"
        return state

    @property
    def device_info(self) -> DeviceInfo:
        return self._attr_device_info
