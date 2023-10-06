import asyncio
import json
import logging
import random

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import *
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (CoordinatorEntity,
                                                      DataUpdateCoordinator)
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN, GW_ID, GW_IP, MANUFACTURER, NAME, TAP_ID

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass, config, async_add_entities, discovery_info=None
):
    """Setup the sensor platform."""
    #config_id = config.unique_id
    #_LOGGER.debug(f"Configuring sensor entities for config {config_id}")
    #if config_id not in hass.data[DOMAIN]:
    #    await asyncio.sleep(random.randint(1,3))
    #taps = hass.data[DOMAIN][config_id]["conf"]["taps"]
    taps = hass.data[DOMAIN][config.entry_id]["conf"]["taps"]
    #vol_unit = hass.data[DOMAIN][config_id]["conf"]["vol_unit"]
    vol_unit = hass.data[DOMAIN][config.entry_id]["conf"]["vol_unit"]
    sensors = []
    for tap in taps:
        _LOGGER.debug(f"Configuring sensors for tap {tap}")
        coordinator = tap["coordinator"]
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="signal", unit="%", icon="mdi:percent-circle"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="battery", unit="%", device_class="battery"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="total_duration", unit="s", icon="mdi:clock"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="remain_duration", unit="s", icon="mdi:clock"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="speed", unit=f"{vol_unit}pm", icon="mdi:speedometer"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="volume", unit=vol_unit, icon="mdi:water-percent"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="volume_limit", unit=vol_unit, icon="mdi:water-percent"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="failsafe_duration", unit="s", icon="mdi:clock"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="plan_mode", unit="mode", icon="mdi:note"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="plan_sn", unit="sn", icon="mdi:note"))
    async_add_entities(sensors, True)

class LinktapSensor(CoordinatorEntity, SensorEntity):

    def __init__(self, coordinator: DataUpdateCoordinator, hass, tap, data_attribute, unit, device_class=False, icon=False):
        super().__init__(coordinator)
        name = data_attribute.replace("_", " ").title()
        self._state = None
        self._name = tap[NAME] + " " + name
        self._id = self._name
        self.attribute = data_attribute
        self.tap_id = tap[TAP_ID]
        self.tap_name = tap[NAME]

        self.platform = "sensor"
        self._attr_unique_id = slugify(f"{DOMAIN}_{self.platform}_{data_attribute}_{self.tap_id}")
        self._attrs = {
            "unit_of_measurement": unit
        }
        if icon:
            self._attr_icon = icon
        if device_class:
            self._attr_device_class = device_class

        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, tap[TAP_ID])
            },
            name=tap[NAME],
            manufacturer=MANUFACTURER,
            model=tap[TAP_ID],
            configuration_url="http://" + tap[GW_IP] + "/"
        )

    @property
    def unique_id(self):
        """Return the unique ID of the sensor."""
        return self._attr_unique_id

    @property
    def name(self):
        return f"{MANUFACTURER} {self._id}"

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
