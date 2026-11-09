import asyncio
import json
import logging
import random
import re

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import service
from homeassistant.helpers.entity import *
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

from .const import (
    ATTR_DEFAULT_TIME,
    ATTR_DURATION,
    ATTR_STATE,
    ATTR_VOL,
    ATTR_VOLUME,
    CONF_MAX_WATERING_DURATION,
    CONF_MAX_WATERING_VOLUME,
    CONF_WATERING_SAFETY_LIMITS,
    DEFAULT_TIME,
    DEFAULT_VOL,
    DOMAIN,
    GW_ID,
    GW_IP,
    MANUFACTURER,
    NAME,
    TAP_ID,
)


def _number_entity_id(hass, tap_id, suffix):
    """Resolve a LinkTap number entity by its stable unique ID.

    Do not construct an entity_id from the tap name. Home Assistant entity IDs
    can include area/device components and can also be renamed by the user.
    The unique ID is stable and is the correct registry key for sibling lookup.
    """
    unique_id = slugify(f"{DOMAIN}_number_{tap_id}_{suffix}")
    return er.async_get(hass).async_get_entity_id(
        NUMBER_DOMAIN, DOMAIN, unique_id
    )


def _safety_limits(config, tap_id):
    return config.options.get(CONF_WATERING_SAFETY_LIMITS, {}).get(tap_id, {})


async def async_setup_entry(hass, config, async_add_entities, discovery_info=None):
    """Setup the switch platform."""
    taps = hass.data[DOMAIN][config.entry_id]["conf"]["taps"]
    switches = []
    for tap in taps:
        coordinator = tap["coordinator"]
        limits = _safety_limits(config, tap[TAP_ID])
        switches.append(
            LinktapSwitch(
                coordinator,
                hass,
                tap,
                max_watering_duration=limits.get(CONF_MAX_WATERING_DURATION),
                max_watering_volume=limits.get(CONF_MAX_WATERING_VOLUME),
            )
        )
        switches.append(LinktapPauseSwitch(coordinator, hass, tap))
        if getattr(coordinator.tap_api, "session_pause_supported", False) is True:
            switches.append(LinktapCurrentWateringPauseSwitch(coordinator, hass, tap))
    async_add_entities(switches, True)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "pause",
        {vol.Required("hours", default=1): vol.Coerce(int)},
        "_pause_tap",
    )



class LinktapSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        hass,
        tap,
        max_watering_duration=None,
        max_watering_volume=None,
    ):
        super().__init__(coordinator)
        self._state = None
        self._name = tap[NAME]
        self._id = tap[TAP_ID]
        self.tap_id = tap[TAP_ID]
        self.tap_api = coordinator.tap_api
        self.platform = "switch"
        self.hass = hass
        self.max_watering_duration = (
            float(max_watering_duration)
            if max_watering_duration is not None
            else None
        )
        self.max_watering_volume = (
            float(max_watering_volume)
            if max_watering_volume is not None
            else None
        )
        self._attr_unique_id = slugify(f"{DOMAIN}_{self.platform}_{self.tap_id}")
        self._attr_icon = "mdi:water-pump"
        self._attrs = {"data": self.coordinator.data}
        if self.max_watering_duration is not None:
            self._attrs["max_watering_duration_safety"] = self.max_watering_duration
        if self.max_watering_volume is not None:
            self._attrs["max_watering_volume_safety"] = self.max_watering_volume
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tap[TAP_ID])},
            name=tap[NAME],
            manufacturer=MANUFACTURER,
            configuration_url="http://" + tap[GW_IP] + "/",
        )

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def duration_entity(self):
        return _number_entity_id(self.hass, self.tap_id, "watering_duration")

    @property
    def volume_entity(self):
        return _number_entity_id(self.hass, self.tap_id, "watering_volume")

    async def async_turn_on(self, **kwargs):
        duration = self.get_watering_duration()
        seconds = int(float(duration)) * 60
        if seconds == 0 and self.max_watering_duration is not None:
            # Zero still selects the instant-watering default, but the fallback
            # must not bypass a configured ceiling.
            seconds = int(min(DEFAULT_TIME, self.max_watering_duration) * 60)
            if seconds < 3:
                raise HomeAssistantError("Configured watering duration limit is below 3 seconds")
        await self.coordinator.async_start_watering(seconds, self.get_watering_volume())
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_safe_stop_watering()
        await self.coordinator.async_request_refresh()

    def get_watering_duration(self):
        entity_id = self.duration_entity
        entity = self.hass.states.get(entity_id) if entity_id else None
        if not entity:
            duration = float(DEFAULT_TIME)
            self._attrs[ATTR_DEFAULT_TIME] = True
        elif entity.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            duration = float(DEFAULT_TIME)
            self._attrs[ATTR_DEFAULT_TIME] = True
        else:
            duration = float(entity.state)
            self._attrs[ATTR_DEFAULT_TIME] = False

        if self.max_watering_duration is not None:
            duration = min(duration, self.max_watering_duration)

        self._attrs[ATTR_DURATION] = duration
        return duration

    def get_watering_volume(self):
        entity_id = self.volume_entity
        entity = self.hass.states.get(entity_id) if entity_id else None
        if not entity:
            volume = float(DEFAULT_VOL)
            self._attrs[ATTR_VOL] = False
        elif entity.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            volume = float(DEFAULT_VOL)
            self._attrs[ATTR_VOL] = False
        else:
            volume = float(entity.state)
            self._attrs[ATTR_VOL] = volume != 0

        if volume > 0 and self.max_watering_volume is not None:
            volume = min(volume, self.max_watering_volume)

        self._attrs[ATTR_VOLUME] = volume
        return volume

    @property
    def extra_state_attributes(self):
        self._attrs["duration_entity"] = self.duration_entity
        self._attrs["volume_entity"] = self.volume_entity
        return self._attrs

    @property
    def state(self):
        status = self.coordinator.data
        self._attrs["data"] = status
        self.get_watering_duration()
        self.get_watering_volume()
        watering = self.is_on
        self._attrs[ATTR_STATE] = watering
        return STATE_UNKNOWN if watering is None else ("on" if watering else "off")

    @property
    def is_on(self):
        return self.coordinator.watering_state

    @property
    def device_info(self) -> DeviceInfo:
        return self._attr_device_info

    async def _pause_tap(self, hours=None):
        if hours is None:
            hours = 1
        await self.coordinator.async_set_water_plan_pause(hours)


class LinktapPauseSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = "Pause Water Plan"

    def __init__(self, coordinator: DataUpdateCoordinator, hass, tap):
        super().__init__(coordinator)
        self._name = f"Pause Water Plan {tap[NAME]}"
        self.tap_name = tap[NAME]
        self.tap_id = tap[TAP_ID]
        self.platform = "switch"
        self.hass = hass
        self._attr_unique_id = slugify(
            f"{DOMAIN}_{self.platform}_{self.tap_id}_pause"
        )
        self._attr_icon = "mdi:pause-circle"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tap[TAP_ID])},
            name=tap[NAME],
            manufacturer=MANUFACTURER,
            configuration_url="http://" + tap[GW_IP] + "/",
        )
        self.coordinator = coordinator
        self._attrs = {}

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def pause_duration_entity(self):
        return _number_entity_id(self.hass, self.tap_id, "pause_duration")

    @property
    def is_on(self):
        status = self.coordinator.data
        return self.coordinator.plan_paused

    @property
    def extra_state_attributes(self):
        self._attrs["pause_duration_entity"] = self.pause_duration_entity
        return self._attrs

    async def async_turn_on(self, **kwargs):
        hours = 24
        entity_id = self.pause_duration_entity
        entity = self.hass.states.get(entity_id) if entity_id else None
        if entity and entity.state not in (None, STATE_UNKNOWN, STATE_UNAVAILABLE):
            try:
                hours = int(float(entity.state))
            except (TypeError, ValueError, OverflowError):
                hours = 24
        await self._pause_tap(hours=hours)

    async def async_turn_off(self, **kwargs):
        await self._pause_tap(hours=0)

    async def _pause_tap(self, hours):
        await self.coordinator.async_set_water_plan_pause(hours)


class LinktapCurrentWateringPauseSwitch(CoordinatorEntity, SwitchEntity):
    """CMD19 control for the current watering session."""
    _attr_has_entity_name = True
    _attr_name = "Pause Current Watering"
    _attr_icon = "mdi:pause-circle-outline"

    def __init__(self, coordinator, hass, tap):
        super().__init__(coordinator)
        self.hass = hass
        self.tap_id = tap[TAP_ID]
        self._attr_unique_id = slugify(f"{DOMAIN}_switch_{self.tap_id}_pause_current_watering")
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, tap[TAP_ID])}, name=tap[NAME], manufacturer=MANUFACTURER, configuration_url="http://" + tap[GW_IP] + "/")

    @property
    def is_on(self):
        return self.coordinator.confirmed_session_paused

    async def async_turn_on(self, **kwargs):
        minutes_id = _number_entity_id(self.hass, self.tap_id, "current_watering_pause_duration")
        st = self.hass.states.get(minutes_id) if minutes_id else None
        minutes = float(st.state) if st and st.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE) else 10.0
        option = getattr(self.coordinator, "current_pause_selected_option", 0)
        await self.coordinator.async_pause_current_watering(minutes / 60.0, option=option)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_resume_current_watering()
