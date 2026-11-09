import asyncio
import logging
import math
import random
from datetime import datetime, timedelta, timezone
from json.decoder import JSONDecodeError

import aiohttp
import async_timeout
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from h11 import Data
from homeassistant import core
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    IntegrationError,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from tenacity import RetryError

from .const import DOMAIN, GW_ID, GW_IP, NAME, PLATFORMS, TAP_ID
from .linktap_local import GatewayResponseError, LinktapLocal

_LOGGER = logging.getLogger(__name__)

MAX_PLAUSIBLE_SESSION_VOLUME = 10_000.0
COMMAND_VERIFY_TIMEOUT = 30
COMMAND_VERIFY_INTERVAL = 3
COMMAND_ERRORS = (aiohttp.ClientError, TimeoutError, ValueError, RetryError)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(_hass, _config):
    return True


async def async_setup_entry(hass: core.HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the platform."""

    gw_ip = entry.data.get(GW_IP)

    linker = LinktapLocal()
    linker.set_ip(gw_ip)

    # A LinkTap gateway can be temporarily unavailable while Home Assistant is
    # starting (for example, while the LAN or gateway itself is still coming up).
    # Let HA retry transport failures. A bad reply already exhausted any
    # bounded read retries, so report it without another HA retry cycle.
    try:
        gw_id = await linker.get_gw_id()
        gateway_config = await linker.get_gw_config(gw_id)
    except GatewayResponseError as err:
        raise IntegrationError(f"Unexpected LinkTap gateway response at {gw_ip}: {err}") from err
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise ConfigEntryNotReady(
            f"Unable to communicate with LinkTap gateway at {gw_ip}"
        ) from err

    _LOGGER.debug(f"Found GW_ID: {gw_id}")

    if gateway_config.get("ret", 0) != 0:
        raise IntegrationError(f"LinkTap gateway at {gw_ip} rejected CMD16 configuration")
    if (
        not isinstance(gateway_config.get("end_dev"), list)
        or not isinstance(gateway_config.get("dev_name"), list)
        or len(gateway_config["end_dev"]) != len(gateway_config["dev_name"])
        or not isinstance(gateway_config.get("vol_unit"), str)
    ):
        raise IntegrationError(f"Unexpected LinkTap CMD16 configuration response at {gw_ip}")

    devices = {
        "devs": gateway_config["end_dev"],
        "names": gateway_config["dev_name"],
    }
    _LOGGER.debug(f"Found devices: {devices}")

    coordinator_conf = {
        GW_IP: gw_ip,
        GW_ID: gw_id,
    }
    counter = 0
    tap_list = []
    for tap_id in devices["devs"]:
        coordinator = LinktapCoordinator(hass, linker, coordinator_conf, tap_id, config_entry=entry)
        device_name = devices["names"][counter]
        tap_list.append({
            NAME: device_name,
            TAP_ID: tap_id,
            GW_IP: gw_ip,
            "coordinator": coordinator
        })
        counter = counter + 1
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.debug(f"Coordinator has synced for {tap_id}")
    _LOGGER.debug(f"List of Taps: {tap_list}")

    vol_unit = gateway_config["vol_unit"]
    _LOGGER.debug(f"Setting volume unit to {vol_unit}")

    conf = {
        GW_IP: gw_ip,
        GW_ID: gw_id,
        "taps": tap_list,
        "vol_unit": vol_unit,
    }

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "conf": conf,
    }
    _LOGGER.debug(hass.data[DOMAIN])
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Reload entry when its updated.
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: core.HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a component config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_remove_config_entry_device(hass: core.HomeAssistant, entry: ConfigEntry, device) -> bool:
    device_registry(hass).async_remove_device(device.id)
    return True


class LinktapCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, linker, conf, tap_id, config_entry=None):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(seconds=random.randint(10,14), milliseconds=random.randint(0,1000))
            #update_interval=timedelta(seconds=13),
        )
        self.tap_api = linker
        self.conf = conf
        self.hass = hass
        self.tap_id = tap_id
        # Serialize all water-plan pause mutations for this tap. Without a lock,
        # two HA callers could both observe an unpaused state and both send cmd 18.
        self._pause_lock = asyncio.Lock()
        self._pending_stops = 0
        self._verification_task = None
        # HA-owned CMD19 expiry/mode metadata; the gateway only reports
        # is_paused_sess. Never infer session pause from the server plan pause.
        self.current_pause_until = None
        self.current_pause_mode = None
        self._status_rejected = False
        self._last_observed_status = None
        self.last_session_failure = None

    def get_gw_id(self):
        return self.conf[GW_ID]

    def _validated_status(self, data):
        """Return valid status data without allowing corrupt volume readings."""
        self._last_observed_status = data
        self._status_rejected = False
        raw_volume = data.get("volume")
        try:
            volume = float(raw_volume)
        except (TypeError, ValueError):
            volume = None

        if (
            volume is None
            or not math.isfinite(volume)
            or volume < 0
            or volume > MAX_PLAUSIBLE_SESSION_VOLUME
        ):
            _LOGGER.warning(
                "Rejecting invalid raw volume %r for LinkTap %s",
                raw_volume,
                self.tap_id,
            )
            self._status_rejected = True
            if self.data is not None:
                return self.data
            raise UpdateFailed("Invalid initial LinkTap volume reading")

        if (
            self._flag(data, "is_rf_linked") is True
            and self._flag(data, "is_paused_sess") is False
        ):
            # The gateway may resume or discard the pause without an HA action.
            self.current_pause_until = None
            self.current_pause_mode = None
        return data

    @property
    def supports_session_pause(self):
        return getattr(self.tap_api, "session_pause_supported", False) is True

    @staticmethod
    def _flag(status, key):
        """Parse JSON booleans/0/1; missing or malformed state stays unknown."""
        value = status.get(key)
        if type(value) in (bool, int) and value in (0, 1):
            return bool(value)
        return None

    @property
    def plan_paused(self):
        return self._flag(self.data or {}, "is_paused")

    @property
    def session_paused(self):
        return self._flag(self.data or {}, "is_paused_sess")

    @property
    def runtime_status(self):
        """Return device runtime data only from an accepted, RF-linked refresh."""
        data = self.data or {}
        if (
            self.last_update_success
            and not self._status_rejected
            and self._flag(data, "is_rf_linked") is True
        ):
            return data
        return None

    @property
    def watering_state(self):
        return self._flag(self.runtime_status or {}, "is_watering")

    @property
    def confirmed_session_paused(self):
        return self._flag(self.runtime_status or {}, "is_paused_sess")

    def _session_error(self, message, cause=None):
        """Keep diagnostic context without exporting raw network exceptions."""
        status = self._last_observed_status or self.data or {}
        fields = ("is_rf_linked", "signal", "is_watering", "is_paused",
                  "is_paused_sess", "remain_duration", "total_duration", "volume")
        self.last_session_failure = {
            "time": datetime.now(timezone.utc).isoformat(),
            "error": message,
            "state": {key: status.get(key) for key in fields},
        }
        if cause is not None:
            self.last_session_failure["error_type"] = type(cause).__name__
            message = f"{message}: {cause}"
        _LOGGER.warning("LinkTap %s: %s; final observed state=%s",
                        self.tap_id, message, self.last_session_failure["state"])
        return HomeAssistantError(
            f"{message}; final observed state={self.last_session_failure['state']}"
        )

    def _require_session_pause(self):
        if not self.supports_session_pause:
            raise HomeAssistantError("Gateway firmware does not support CMD19")

    def _require_no_pending_stop(self):
        if self._pending_stops:
            raise HomeAssistantError("Watering command interrupted by a pending stop")

    async def _async_verify_command(self, predicate, *, require_rf=True):
        """Let a pending Stop interrupt verification, never an in-flight write."""
        self._require_no_pending_stop()
        task = asyncio.create_task(self._async_poll_state(predicate, require_rf=require_rf))
        self._verification_task = task
        try:
            return await task
        except asyncio.CancelledError:
            if not self._pending_stops or asyncio.current_task().cancelling():
                raise
            raise HomeAssistantError("Command verification interrupted by Stop") from None
        finally:
            self._verification_task = None

    async def _async_poll_state(self, predicate, *, require_rf=True):
        """Bound the whole poll, including refresh I/O, to 30 seconds.

        Power Save reports may lag more than 15s (Performance more than 5s).
        Retry stale and failed samples; never confirm physical state without RF.
        """
        try:
            async with asyncio.timeout(COMMAND_VERIFY_TIMEOUT):
                while True:
                    await self.async_refresh()
                    status = self.data or {}
                    if (self.last_update_success and not self._status_rejected
                        and (not require_rf or self._flag(status, "is_rf_linked") is True)
                        and predicate(status)):
                        return True
                    await asyncio.sleep(COMMAND_VERIFY_INTERVAL)
        except TimeoutError:
            return False

    async def _async_verify_pause_state(self, expected_paused):
        """Verify server plan pause independently of CMD19/session state."""
        return await self._async_verify_command(
            lambda status: self._flag(status, "is_paused") is expected_paused,
            require_rf=False,
        )

    async def async_pause_current_watering(self, hours, option=0):
        """Pause the current session with CMD19 and retain HA expiry metadata."""
        self._require_session_pause()
        try:
            hours = float(hours)
        except (TypeError, ValueError) as err:
            raise HomeAssistantError("Current watering pause must be 0.01 to 240 hours") from err
        if not math.isfinite(hours) or not 0.01 <= hours <= 240:
            raise HomeAssistantError("Current watering pause must be 0.01 to 240 hours")
        if type(option) is not int or option not in (0, 1):
            raise HomeAssistantError("CMD19 option must be 0 or 1")
        async with self._pause_lock:
            await self.async_refresh()
            status = self.data or {}
            if (not self.last_update_success or self._status_rejected
                or self._flag(status, "is_rf_linked") is not True):
                raise self._session_error("Unable to verify RF-linked current watering state; no pause sent")
            if self.session_paused is True:
                raise self._session_error("Current watering is already paused")
            if self.session_paused is None:
                raise self._session_error("Gateway did not report a valid session pause flag; no pause sent")
            if self._flag(status, "is_watering") is not True:
                raise self._session_error("LinkTap is not currently watering; no pause sent")
            remaining = status.get("remain_duration")
            if (type(remaining) not in (int, float) or not math.isfinite(remaining)):
                raise self._session_error("Unable to verify remaining watering duration; no pause sent")
            if remaining <= 15:
                raise self._session_error("Current watering cannot be paused: remaining duration must exceed 15 seconds")
            self._require_no_pending_stop()
            requested_at = datetime.now(timezone.utc)
            try:
                response = await self.tap_api.cmd19(self.get_gw_id(), self.tap_id, hours, option=option)
            except COMMAND_ERRORS as err:
                raise self._session_error("Current-session pause result unknown", err) from err
            ret = response.get("ret")
            if ret == 10:
                raise self._session_error("Gateway rejected current-session pause (ret=10): session is not pausable")
            if ret != 0:
                raise self._session_error(f"Gateway rejected current-session pause (ret={ret})")
            if not await self._async_verify_command(
                lambda state: self._flag(state, "is_paused_sess") is True
                and self._flag(state, "is_watering") is False
            ):
                raise self._session_error("Gateway accepted pause but session-paused state was not verified within 30 seconds")
            # Use dispatch time, but publish metadata only for a verified pause.
            self.current_pause_until = requested_at + timedelta(hours=hours)
            self.current_pause_mode = option
            self.async_update_listeners()

    async def async_resume_current_watering(self):
        """Resume a CMD19-paused session without changing the server plan."""
        self._require_session_pause()
        async with self._pause_lock:
            await self.async_refresh()
            status = self.data or {}
            if (not self.last_update_success or self._status_rejected
                or self._flag(status, "is_rf_linked") is not True
                or self.session_paused is None):
                raise self._session_error("Unable to verify RF-linked session-paused state; no resume sent")
            if self.session_paused is False:
                self.current_pause_until = None
                self.current_pause_mode = None
                return
            self._require_no_pending_stop()
            try:
                response = await self.tap_api.cmd19(self.get_gw_id(), self.tap_id, 0)
            except COMMAND_ERRORS as err:
                raise self._session_error("Current-session resume result unknown", err) from err
            if response.get("ret") != 0:
                raise self._session_error(f"Gateway rejected current-session resume (ret={response.get('ret')})")
            if not await self._async_verify_command(
                lambda state: self._flag(state, "is_paused_sess") is False
            ):
                raise self._session_error("Gateway accepted resume but session-unpaused state was not verified within 30 seconds")
            self.current_pause_until = None
            self.current_pause_mode = None
            self.async_update_listeners()

    async def _async_verify_safe_idle(self):
        """Require confirmed RF idle, plus cleared session pause on revised firmware."""
        return await self._async_poll_state(
            lambda status: self._flag(status, "is_watering") is False
            and (self._flag(status, "is_paused_sess") is False
                 or (not self.supports_session_pause and "is_paused_sess" not in status))
        )

    async def async_start_watering(self, seconds, volume=None):
        """Start once; wait for delayed CMD3 confirmation on revised firmware."""
        async with self._pause_lock:
            self._require_no_pending_stop()
            try:
                accepted = await self.tap_api.turn_on(self.get_gw_id(), self.tap_id, seconds, volume)
            except COMMAND_ERRORS as err:
                raise self._session_error("Unable to confirm start request", err) from err
            if not accepted:
                raise self._session_error("LinkTap gateway rejected start request")
            if self.supports_session_pause:
                if not await self._async_verify_command(
                    lambda status: self._flag(status, "is_watering") is True
                    and self._flag(status, "is_paused_sess") is False
                ):
                    raise self._session_error("Start accepted but watering was not verified within 30 seconds")
            else:
                await self.async_refresh()

    async def async_safe_stop_watering(self):
        """Send CMD7 regardless of the last status; never resume a plan or session."""
        self._pending_stops += 1
        try:
            if self._verification_task is not None:
                self._verification_task.cancel()
            async with self._pause_lock:
                try:
                    accepted = await self.tap_api.turn_off(self.get_gw_id(), self.tap_id)
                except COMMAND_ERRORS as err:
                    raise self._session_error("Stop result unknown", err) from err
                if not accepted:
                    raise self._session_error("LinkTap gateway rejected stop request")
                if not await self._async_verify_safe_idle():
                    raise self._session_error("Stop accepted but gateway did not reach safe stopped state within 30 seconds")
                self.current_pause_until = None
                self.current_pause_mode = None
                self.async_update_listeners()
        finally:
            self._pending_stops -= 1

    async def async_set_water_plan_pause(self, hours):
        """Safely set or clear this tap's watering-plan pause.

        LinkTap issue #88 is destructive: a second positive cmd 18 while the
        watering plan is already paused can deactivate the plan, even though
        the gateway returns ret=0. Refresh immediately before the decision and
        refuse repeated positive pause requests rather than risking plan loss.
        """
        try:
            # v0.8.9 truncates numeric hours towards zero for CMD18 only.
            hours = int(hours)
        except (TypeError, ValueError, OverflowError) as err:
            raise HomeAssistantError("Water plan pause requires whole hours from 0 to 240") from err
        if hours < 0:
            raise HomeAssistantError("Water plan pause duration cannot be negative")
        if hours > 240:
            raise HomeAssistantError("Water plan pause requires whole hours from 0 to 240")

        async with self._pause_lock:
            # Bypass the coordinator refresh debouncer: the safety decision must
            # use a fresh gateway state, not a recently cached is_paused value.
            await self.async_refresh()
            if not self.last_update_success:
                raise HomeAssistantError(
                    "Unable to verify the current LinkTap water plan pause state; "
                    "no pause command was sent."
                )

            plan_paused = self.plan_paused
            if plan_paused is None or self._status_rejected:
                raise HomeAssistantError("Unable to verify the water plan pause state; no pause sent")

            if hours > 0 and plan_paused:
                _LOGGER.warning(
                    "Refusing repeated water plan pause for LinkTap %s: "
                    "the plan is already paused and another positive pause "
                    "request can deactivate the watering plan",
                    self.tap_id,
                )
                raise HomeAssistantError(
                    "Water plan is already paused. LinkTap cannot safely replace "
                    "an active pause using the local API; the existing pause has "
                    "been left unchanged."
                )

            if hours == 0 and not plan_paused:
                _LOGGER.debug(
                    "Water plan for LinkTap %s is already unpaused; no command sent",
                    self.tap_id,
                )
                return

            self._require_no_pending_stop()
            try:
                success = await self.tap_api.pause_tap(self.get_gw_id(), self.tap_id, hours)
            except COMMAND_ERRORS as err:
                raise self._session_error("Water plan pause/resume result unknown", err) from err
            if not success:
                raise HomeAssistantError(
                    f"LinkTap gateway rejected water plan pause request for {self.tap_id}"
                )

            expected_paused = hours > 0
            verified = await self._async_verify_pause_state(expected_paused)
            if not verified:
                if not self.last_update_success:
                    raise HomeAssistantError("LinkTap gateway accepted the water plan pause request, but Home Assistant could not verify the resulting gateway state.")
                action = "pause" if expected_paused else "unpause"
                raise HomeAssistantError(
                    f"LinkTap gateway accepted the {action} request but did not "
                    "report the expected water plan pause state"
                )

    #def get_vol_unit(self):
    #    return self.conf["vol_unit"]

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """

        #tap_id = self.conf["taps"][TAP_ID]
        gw_id = self.conf[GW_ID]

        retryable_errors = (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            JSONDecodeError,
            RetryError,
            ValueError,
        )

        try:
            async with async_timeout.timeout(10):
                data = await self.tap_api.fetch_data(gw_id, self.tap_id)
                return self._validated_status(data)
        except retryable_errors:
            await asyncio.sleep(random.randint(1, 3))

        try:
            async with async_timeout.timeout(10):
                data = await self.tap_api.fetch_data(gw_id, self.tap_id)
                return self._validated_status(data)
        except retryable_errors as err:
            raise UpdateFailed(
                f"Error communicating with LinkTap gateway: {err}"
            ) from err


async def async_reload_entry(hass: core.HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when it changed."""
    await hass.config_entries.async_reload(entry.entry_id)
