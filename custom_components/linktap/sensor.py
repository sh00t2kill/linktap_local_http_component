import asyncio
import json
import logging
import random

import aiohttp
import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util
import voluptuous as vol
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.entity import *
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
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
    taps = hass.data[DOMAIN][config.entry_id]["conf"]["taps"]
    vol_unit = hass.data[DOMAIN][config.entry_id]["conf"]["vol_unit"]
    sensors = []
    for tap in taps:
        _LOGGER.debug(f"Configuring sensors for tap {tap}")
        coordinator = tap["coordinator"]
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="signal", unit="%", icon="mdi:percent-circle"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="battery", unit="%", device_class="battery"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="total_duration", unit="s", icon="mdi:clock"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="remain_duration", unit="s", icon="mdi:clock"))
        sensors.append(LinktapWateringTimeTotalSensor(coordinator, hass, tap))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="speed", unit=f"{vol_unit}pm", icon="mdi:speedometer"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="volume", unit=vol_unit, device_class="water", icon="mdi:water-percent"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="volume_limit", unit=vol_unit, icon="mdi:water-percent"))
        sensors.append(LinktapVolumeTotalSensor(coordinator, hass, tap, unit=vol_unit))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="failsafe_duration", unit="s", icon="mdi:clock"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="plan_mode", unit="mode", icon="mdi:note"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="plan_sn", unit="sn", icon="mdi:note"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="plan_mode_string", unit="mode", icon="mdi:note"))
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
            if device_class == "water":
                self._attr_state_class = SensorStateClass.MEASUREMENT

        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, tap[TAP_ID])
            },
            name=tap[NAME],
            manufacturer=MANUFACTURER,
            model=tap[TAP_ID],
            configuration_url="http://" + tap[GW_IP] + "/"
        )
#Modemode: watering mode (1 - Instant Mode, 2 - Calendar mode, 3 - 7 day mode, 4 - Odd-even mode, 5 -Interval mode, 6 - Month mode).
    def translate_plan_mode(self, mode):
        modes = ['NA', 'Instant', 'Calendar', '7-Day', 'Odd-Even', 'Interval', 'Month']
        return modes[mode]


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
        previous_state = self._state
        if not attributes:
            self._state = "unknown"
        else:
            if self.attribute == "plan_mode_string":
                self._state = self.translate_plan_mode(attributes["plan_mode"])
            else:
                self._state = attributes[self.attribute]

        return self._state

    @property
    def device_info(self) -> DeviceInfo:
        return self._attr_device_info


class LinktapVolumeTotalSensor(CoordinatorEntity, RestoreEntity, SensorEntity):

    def __init__(self, coordinator, hass, tap, unit):
        super().__init__(coordinator)
        self.tap_id = tap[TAP_ID]
        self._attr_name = f"{MANUFACTURER} {tap[NAME]} Volume Total"
        self._attr_unique_id = slugify(f"{DOMAIN}_sensor_volume_total_{self.tap_id}")
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = "water"
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:water"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tap[TAP_ID])},
            name=tap[NAME],
            manufacturer=MANUFACTURER,
            model=tap[TAP_ID],
            configuration_url="http://" + tap[GW_IP] + "/"
        )
        self._total = 0.0
        self._previous_volume = 0.0

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state and state.state not in ("unknown", "unavailable"):
            try:
                self._total = float(state.state)
            except ValueError:
                self._total = 0.0

    def _handle_coordinator_update(self) -> None:
        if not self.coordinator.data:
            return
        current = float(self.coordinator.data.get("volume", 0))
        # volume drop means a new session started; commit the completed session
        if current < self._previous_volume:
            self._total += self._previous_volume
        self._previous_volume = current
        self.async_write_ha_state()

    @property
    def native_value(self):
        return round(self._total + self._previous_volume, 1)


class LinktapWateringTimeTotalSensor(CoordinatorEntity, RestoreEntity, SensorEntity):

    def __init__(self, coordinator, hass, tap):
        super().__init__(coordinator)
        self.tap_id = tap[TAP_ID]
        self._attr_name = f"{MANUFACTURER} {tap[NAME]} Watering Time Total"
        self._attr_unique_id = slugify(f"{DOMAIN}_sensor_watering_time_total_{self.tap_id}")
        self._attr_native_unit_of_measurement = "s"
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:clock"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tap[TAP_ID])},
            name=tap[NAME],
            manufacturer=MANUFACTURER,
            model=tap[TAP_ID],
            configuration_url="http://" + tap[GW_IP] + "/"
        )
        self._total = 0.0
        self._previous_watering = False
        self._session_start = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state and state.state not in ("unknown", "unavailable"):
            try:
                self._total = float(state.state)
            except ValueError:
                self._total = 0.0

    def _handle_coordinator_update(self) -> None:
        if not self.coordinator.data:
            return
        is_watering = self.coordinator.data.get("is_watering", False)
        now = dt_util.utcnow()
        if is_watering and not self._previous_watering:
            self._session_start = now
        elif not is_watering and self._previous_watering and self._session_start:
            self._total += (now - self._session_start).total_seconds()
            self._session_start = None
        self._previous_watering = is_watering
        self.async_write_ha_state()

    @property
    def native_value(self):
        if self._session_start is not None:
            elapsed = (dt_util.utcnow() - self._session_start).total_seconds()
            return round(self._total + elapsed, 1)
        return round(self._total, 1)
