import asyncio
import json
import logging

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity import *
from homeassistant.helpers.update_coordinator import (CoordinatorEntity,
                                                      DataUpdateCoordinator)
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN, TAP_ID, GW_ID, NAME

_LOGGER = logging.getLogger(__name__)

#async def async_setup_platform(
async def async_setup_entry(
    hass, config, async_add_entities, discovery_info=None
):
    """Setup the sensor platform."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    sensors = []
    sensors.append(LinktapSensor(coordinator, hass, data_attribute="signal", unit="%", icon="mdi:percent-circle"))
    sensors.append(LinktapSensor(coordinator, hass, data_attribute="battery", unit="%", device_class="battery"))
    sensors.append(LinktapSensor(coordinator, hass, data_attribute="total_duration", unit="s", icon="mdi:clock"))
    sensors.append(LinktapSensor(coordinator, hass, data_attribute="remain_duration", unit="s", icon="mdi:clock"))
    sensors.append(LinktapSensor(coordinator, hass, data_attribute="speed", unit="lpm", icon="mdi:speedometer"))
    sensors.append(LinktapSensor(coordinator, hass, data_attribute="volume", unit="lpm", icon="mdi:water-percent"))
    sensors.append(LinktapSensor(coordinator, hass, data_attribute="volume_limit", unit="lpm", icon="mdi:water-percent"))
    sensors.append(LinktapSensor(coordinator, hass, data_attribute="failsafe_duration", unit="s", icon="mdi:clock"))
    sensors.append(LinktapSensor(coordinator, hass, data_attribute="plan_mode", unit="mode", icon="mdi:note"))
    sensors.append(LinktapSensor(coordinator, hass, data_attribute="plan_sn", unit="sn", icon="mdi:note"))
    async_add_entities(sensors, True)

class LinktapSensor(CoordinatorEntity, SensorEntity):

    def __init__(self, coordinator: DataUpdateCoordinator, hass, data_attribute, unit, device_class=False, icon=False):
        super().__init__(coordinator)
        name = data_attribute.replace("_", " ").title()
        self._state = None
        self._name = hass.data[DOMAIN]["conf"][NAME] + " " + name
        self._id = self._name
        self.attribute = data_attribute
        self.tap_id = hass.data[DOMAIN]["conf"][TAP_ID]
        self.tap_name = hass.data[DOMAIN]["conf"][NAME]

        self.platform = "sensor"
        self._attr_unique_id = slugify(f"{DOMAIN}_{self.platform}_{data_attribute}_{self.tap_id}")
        self._attr_device_info = self.coordinator.get_device()
        self._attrs = {
            "unit_of_measurement": unit
        }
        if icon:
            self._attr_icon = icon
        if device_class:
            self._attr_device_class = device_class

    @property
    def unique_id(self):
        """Return the unique ID of the sensor."""
        return self._attr_unique_id

    @property
    def name(self):
        return f"Linktap {self._id}"

    @property
    def extra_state_attributes(self):
        return self._attrs

    @property
    def state(self):

        attributes = self.coordinator.data
        _LOGGER.debug(f"Sensor state: {attributes}")

        if not attributes:
            self._state = "unknown"
        else:
            self._state = attributes[self.attribute]

        return self._state

    @property
    def device_info(self) -> DeviceInfo:
        return self._attr_device_info
