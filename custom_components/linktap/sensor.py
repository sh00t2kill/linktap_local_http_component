import asyncio
import json
import logging
import math
import random

import aiohttp
import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util
import voluptuous as vol
from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolumeFlowRate
from homeassistant.helpers.entity import *
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN, GW_ID, GW_IP, MANUFACTURER, NAME, TAP_ID

# Volume Total is persistent, so a corrupt raw session-volume sample must not be
# allowed to enter its accumulator. This is deliberately a very generous
# catastrophic fallback, not a claimed hardware flow/volume specification.
#
# The integration's existing HA instant-watering volume control tops out at
# 2,000 configured volume units; 10,000 leaves substantial headroom for
# schedules or watering started outside Home Assistant while still rejecting
# the extreme values reported in issue #94.
MAX_PLAUSIBLE_SESSION_VOLUME = 10000.0

# When LinkTap reports a non-zero volume_limit, use it as a stronger contextual
# bound, but allow generous overshoot/tolerance to avoid false positives from
# valve-close latency, stale rounding, or reporting differences.
VOLUME_LIMIT_MULTIPLIER = 2.0
VOLUME_LIMIT_ABSOLUTE_TOLERANCE = 20.0


async def async_setup_entry(
    hass, config, async_add_entities, discovery_info=None
):
    """Setup the sensor platform."""
    taps = hass.data[DOMAIN][config.entry_id]["conf"]["taps"]
    vol_unit = hass.data[DOMAIN][config.entry_id]["conf"]["vol_unit"]

    # Home Assistant requires canonical volume-flow units for the
    # VOLUME_FLOW_RATE device class and long-term statistics.
    # LinkTap reports the configured volume unit as L or Gal.
    flow_unit = (
        UnitOfVolumeFlowRate.LITERS_PER_MINUTE
        if str(vol_unit).lower() == "l"
        else UnitOfVolumeFlowRate.GALLONS_PER_MINUTE
    )
    sensors = []
    for tap in taps:
        _LOGGER.debug(f"Configuring sensors for tap {tap}")
        coordinator = tap["coordinator"]
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="signal", unit="%", icon="mdi:percent-circle"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="battery", unit="%", device_class="battery"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="total_duration", unit="s", icon="mdi:clock"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="remain_duration", unit="s", icon="mdi:clock"))
        sensors.append(LinktapWateringTimeTotalSensor(coordinator, hass, tap))
        sensors.append(
            LinktapSensor(
                coordinator,
                hass,
                tap,
                data_attribute="speed",
                unit=flow_unit,
                device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
                icon="mdi:speedometer",
            )
        )
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="volume", unit=vol_unit, device_class="water", icon="mdi:water-percent"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="volume_limit", unit=vol_unit, icon="mdi:water-percent"))
        sensors.append(LinktapVolumeTotalSensor(coordinator, hass, tap, unit=vol_unit))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="failsafe_duration", unit="s", icon="mdi:clock"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="plan_mode", unit="mode", icon="mdi:note"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="plan_sn", unit="sn", icon="mdi:note"))
        sensors.append(LinktapSensor(coordinator, hass, tap, data_attribute="plan_mode_string", unit="mode", icon="mdi:note"))
        if getattr(coordinator.tap_api, "session_pause_supported", False) is True:
            sensors.append(LinktapCurrentPauseRemainingSensor(coordinator, tap))
    async_add_entities(sensors, True)


class LinktapSensor(CoordinatorEntity, SensorEntity):
    # Modern HA naming: entity name is relative to the device name.
    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, hass, tap, data_attribute, unit, device_class=False, icon=False):
        super().__init__(coordinator)
        name = data_attribute.replace("_", " ").title()
        self._state = None
        self.attribute = data_attribute
        self.tap_id = tap[TAP_ID]
        self.tap_name = tap[NAME]
        self.platform = "sensor"
        # IMPORTANT: keep unique_id formula unchanged for registry/history stability.
        self._attr_unique_id = slugify(f"{DOMAIN}_{self.platform}_{data_attribute}_{self.tap_id}")
        self._attr_name = name
        self._attrs = {
            "unit_of_measurement": unit
        }
        if icon:
            self._attr_icon = icon
        if device_class:
            self._attr_device_class = device_class
            if device_class in (
                "water",
                SensorDeviceClass.VOLUME_FLOW_RATE,
            ):
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

    # Plan mode enum values reported by LinkTap. The gateway can also expose
    # modes outside the currently known set, so map known values explicitly and
    # retain the raw value in the fallback string for diagnostics.
    def translate_plan_mode(self, mode):
        modes = {
            0: "NA",
            1: "Instant",
            2: "Calendar",
            3: "7-Day",
            4: "Odd-Even",
            5: "Interval",
            6: "Month",
            7: "Master Valve",
        }
        if mode in modes:
            return modes[mode]
        return f"Unknown ({mode})"

    @property
    def unique_id(self):
        """Return the unique ID of the sensor."""
        return self._attr_unique_id

    @property
    def extra_state_attributes(self):
        return self._attrs

    @property
    def state(self):
        attributes = self.coordinator.data
        _LOGGER.debug(f"Sensor state: {attributes}")
        if not attributes or (
            self.attribute in {"remain_duration", "total_duration", "speed", "volume", "volume_limit"}
            and self.coordinator.runtime_status is None
        ):
            self._state = "unknown"
        else:
            if self.attribute == "plan_mode_string":
                self._state = self.translate_plan_mode(attributes["plan_mode"])
            elif self.attribute == "remain_duration":
                # LinkTap can retain the final remaining-duration value after a
                # watering session is stopped. In Home Assistant, a remaining
                # duration is semantically zero when watering is no longer active.
                #
                # Preserve the reported remaining duration while paused so a
                # paused watering session can still show how much time remains.
                is_watering = self.coordinator.watering_state
                session_paused = self.coordinator.confirmed_session_paused
                if is_watering is True or session_paused is True:
                    self._state = attributes.get(self.attribute, "unknown")
                elif is_watering is False and (
                    session_paused is False or not self.coordinator.supports_session_pause
                ):
                    self._state = 0
                else:
                    self._state = "unknown"
            else:
                self._state = attributes.get(self.attribute, "unknown")

        return self._state

    @property
    def device_info(self) -> DeviceInfo:
        return self._attr_device_info


async def _restore_cumulative_value(entity):
    """Restore numeric data saved during an outage, or a v0.8.9 state."""
    data = await entity.async_get_last_sensor_data()
    state = await entity.async_get_last_state()
    try:
        value = float(data.native_value if data is not None else (state.state if state else None))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


class LinktapVolumeTotalSensor(CoordinatorEntity, RestoreSensor):
    # Modern HA naming: entity name is relative to the device name.
    _attr_has_entity_name = True

    def __init__(self, coordinator, hass, tap, unit):
        super().__init__(coordinator)
        self.tap_id = tap[TAP_ID]
        self._attr_name = "Volume Total"
        # IMPORTANT: keep unique_id formula unchanged for registry/history stability.
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
        self._restored = False

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        restored_total = await _restore_cumulative_value(self)
        if restored_total is not None:
            self._total = restored_total
            self._restored = True

    def _validated_current_volume(self):
        """Return a safe raw session-volume sample, or None if rejected.

        A rejected sample must not update _previous_volume. Otherwise a later
        normal lower reading would be interpreted as a new-session boundary and
        permanently commit the corrupt sample into Volume Total.
        """
        data = self.coordinator.data
        raw_volume = data.get("volume")

        try:
            current = float(raw_volume)
        except (TypeError, ValueError):
            _LOGGER.warning(
                "Ignoring non-numeric volume reading %r for LinkTap %s",
                raw_volume,
                self.tap_id,
            )
            return None

        if not math.isfinite(current) or current < 0:
            _LOGGER.warning(
                "Ignoring invalid volume reading %r for LinkTap %s",
                raw_volume,
                self.tap_id,
            )
            return None

        ceiling = MAX_PLAUSIBLE_SESSION_VOLUME
        raw_volume_limit = data.get("volume_limit", 0)

        try:
            volume_limit = float(raw_volume_limit)
        except (TypeError, ValueError):
            volume_limit = 0.0

        # When idle, volume is the previous session's result and volume_limit
        # is a persistent setting, not that session's target (CMD3 contract).
        if (
            (self.coordinator.watering_state is True
             or self.coordinator.confirmed_session_paused is True)
            and math.isfinite(volume_limit) and volume_limit > 0
        ):
            contextual_ceiling = max(
                volume_limit * VOLUME_LIMIT_MULTIPLIER,
                volume_limit + VOLUME_LIMIT_ABSOLUTE_TOLERANCE,
            )
            ceiling = min(ceiling, contextual_ceiling)

        if current > ceiling:
            _LOGGER.warning(
                "Ignoring implausible volume reading %s for LinkTap %s "
                "(volume_limit=%r, accepted ceiling=%s)",
                current,
                self.tap_id,
                raw_volume_limit,
                ceiling,
            )
            return None

        return current

    def _handle_coordinator_update(self) -> None:
        if self.coordinator.runtime_status is None:
            # Publish CoordinatorEntity availability even with no usable volume.
            super()._handle_coordinator_update()
            return

        current = self._validated_current_volume()
        if current is None:
            # Critical for #94: leave both _previous_volume and _total untouched.
            # The next sane sample therefore cannot latch the rejected value.
            super()._handle_coordinator_update()
            return

        if self._restored:
            # API retains last session's volume after completion; offset _total so
            # native_value == restored state and the volume isn't counted twice.
            self._total -= current
            self._restored = False
        elif current < self._previous_volume:
            # volume drop means a new session started; commit the completed session
            self._total += self._previous_volume

        self._previous_volume = current
        self.async_write_ha_state()

    @property
    def native_value(self):
        return round(self._total + self._previous_volume, 1)


class LinktapWateringTimeTotalSensor(CoordinatorEntity, RestoreSensor):
    # Modern HA naming: entity name is relative to the device name.
    _attr_has_entity_name = True

    def __init__(self, coordinator, hass, tap):
        super().__init__(coordinator)
        self.tap_id = tap[TAP_ID]
        self._attr_name = "Watering Time Total"
        # IMPORTANT: keep unique_id formula unchanged for registry/history stability.
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
        self._session_start = None
        self._last_confirmed_at = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        restored_total = await _restore_cumulative_value(self)
        if restored_total is not None:
            self._total = restored_total

    def _handle_coordinator_update(self) -> None:
        is_watering = self.coordinator.watering_state
        now = dt_util.utcnow()
        if is_watering is True:
            if self._session_start is None:
                self._session_start = now
            self._last_confirmed_at = now
        elif self._session_start is not None:
            # Do not count an RF outage as watering. End at the last confirmed
            # sample if the physical transition time cannot be observed.
            end = now if is_watering is False else self._last_confirmed_at
            self._total += max(0, (end - self._session_start).total_seconds())
            self._session_start = None
        self.async_write_ha_state()

    @property
    def native_value(self):
        if self._session_start is not None:
            end = (dt_util.utcnow() if self.coordinator.watering_state is True
                   else self._last_confirmed_at)
            elapsed = max(0, (end - self._session_start).total_seconds())
            return round(self._total + elapsed, 1)
        return round(self._total, 1)


class LinktapCurrentPauseRemainingSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Pause Remaining"
    _attr_icon = "mdi:timer-sand"
    _attr_native_unit_of_measurement = "s"

    def __init__(self, coordinator, tap):
        super().__init__(coordinator)
        self._attr_unique_id = slugify(f"{DOMAIN}_sensor_current_pause_remaining_{tap[TAP_ID]}")
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, tap[TAP_ID])}, name=tap[NAME], manufacturer=MANUFACTURER, model=tap[TAP_ID], configuration_url="http://" + tap[GW_IP] + "/")

    @property
    def native_value(self):
        paused = self.coordinator.confirmed_session_paused
        if paused is None:
            return None
        if paused is False:
            return 0
        until = getattr(self.coordinator, "current_pause_until", None)
        if until is None:
            return None
        return max(0, int((until - dt_util.utcnow()).total_seconds()))

    @property
    def extra_state_attributes(self):
        paused = self.coordinator.confirmed_session_paused is True
        mode = self.coordinator.current_pause_mode if paused else None
        return {
            "expiry_known": paused and self.coordinator.current_pause_until is not None,
            "resume_behaviour": {0: "Keep Original End Time", 1: "Complete Full Watering Duration"}.get(mode),
        }
