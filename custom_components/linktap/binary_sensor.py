import asyncio
import json
import logging
import random

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers import entity_platform, service
from homeassistant.helpers.entity import *
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (CoordinatorEntity,
                                                      DataUpdateCoordinator)
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN, GW_ID, GW_IP, MANUFACTURER, NAME, TAP_ID


async def async_setup_entry(
    hass, config, async_add_entities, discovery_info=None
):
    """Setup the sensor platform."""
    #config_id = config.unique_id
    #_LOGGER.debug(f"Configuring binary sensor entities for config {config_id}")
    #if config_id not in hass.data[DOMAIN]:
    #    await asyncio.sleep(random.randint(1,3))
    #taps = hass.data[DOMAIN][config_id]["conf"]["taps"]
    taps = hass.data[DOMAIN][config.entry_id]["conf"]["taps"]
    binary_sensors = []
    for tap in taps:
        coordinator = tap["coordinator"]
        _LOGGER.debug(f"Configuring binary sensors for tap {tap}")
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, name="Is Linked", data_attribute="is_rf_linked"))
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, data_attribute="is_fall", icon="mdi:meter-electric-outline"))
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, data_attribute="is_cutoff", icon="mdi:scissors-cutting"))
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, name="Is Leaking", data_attribute="is_leak", icon="mdi:leak"))
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, name="Is Clogged", data_attribute="is_clog",  icon="mdi:leak-off"))
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, data_attribute="is_broken", icon="mdi:scissors-cutting"))
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, data_attribute="is_manual_mode", icon="mdi:account-switch"))
        binary_sensors.append(LinktapBinarySensor(coordinator, hass, tap=tap, data_attribute="is_watering", icon="mdi:water"))
    async_add_entities(binary_sensors, True)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service("dismiss_alerts", {}, "_dismiss_alerts")
    platform.async_register_entity_service("dismiss_alert", {}, "_dismiss_alert")

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
        self.tap_api = coordinator.tap_api
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
        return f"{MANUFACTURER} {self._name}"

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

    async def _dismiss_alerts(self):
        _LOGGER.debug(f"Dismissing all alerts for {self.entity_id}")
        await self.tap_api.dismiss_alert(self.coordinator.get_gw_id(), self.tap_id)

    """alert: type of alert
    0: all types of alert.
    1: device fall alert.
    2: valve shut-down failure alert.
    3: water cut-off alert.
    4: unusually high flow alert.
    5: unusually low flow alert.
    """
    async def _dismiss_alert(self):
        split_name = self._data_check_attribute.split("_")
        alert_type = split_name[len(split_name)-1]
        alert_id = self.alert_lookup(alert_type)
        if alert_id is not None:
            _LOGGER.debug(f"Dismissing {alert_type} alert for {self.entity_id}")
            await self.tap_api.dismiss_alert(self.coordinator.get_gw_id(), self.tap_id)
        else:
            _LOGGER.debug("No matching alert found. Do nothing")

    def alert_lookup(self, alert_name):
        alerts = {
            "all" :0,
            "fall": 1,
            "shutdown" :2,
            "cutoff": 3,
            "high_flow": 4,
            "low_flow": 5
        }
        if alert_name in alerts:
            return alerts[alert_name]
        else:
            return None
