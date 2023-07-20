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

async def async_setup_platform(
    hass, config, async_add_entities, discovery_info=None
):
    """Setup the sensor platform."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    sensors = []
    sensors.append(LinktapSensor(coordinator, hass, "Signal", "signal", "%"))
    sensors.append(LinktapSensor(coordinator, hass, "Battery", "battery", "%"))
    sensors.append(LinktapSensor(coordinator, hass, "Total Duration", "total_duration", "s"))
    sensors.append(LinktapSensor(coordinator, hass, "Remaining Duration", "remain_duration", "s"))
    sensors.append(LinktapSensor(coordinator, hass, "Speed", "speed", "lpm"))
    sensors.append(LinktapSensor(coordinator, hass, "Volume", "volume", "lpm"))
    sensors.append(LinktapSensor(coordinator, hass, "Volume Limit", "volume_limit", "lpm"))
    sensors.append(LinktapSensor(coordinator, hass, "Failsafe Duration", "failsafe_duration", "s"))
    sensors.append(LinktapSensor(coordinator, hass, "Plan Mode", "plan_mode", "mode"))
    sensors.append(LinktapSensor(coordinator, hass, "Plan SN", "plan_sn", "sn"))
    async_add_entities(sensors, True)

class LinktapSensor(CoordinatorEntity, SensorEntity):

    def __init__(self, coordinator: DataUpdateCoordinator, hass, name, data_attribute, unit):
        super().__init__(coordinator)
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
