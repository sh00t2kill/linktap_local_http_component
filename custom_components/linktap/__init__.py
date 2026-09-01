import asyncio
import logging
import random
from datetime import timedelta
from json.decoder import JSONDecodeError

import async_timeout
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from h11 import Data
from homeassistant import core
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.exceptions import HomeAssistantError, IntegrationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, GW_ID, GW_IP, NAME, PLATFORMS, TAP_ID
from .linktap_local import LinktapLocal

_LOGGER = logging.getLogger(__name__)

async def async_setup(_hass, _config):
    return True

async def async_setup_entry(hass: core.HomeAssistant, entry: ConfigEntry)-> bool:
    """Set up the platform."""

    gw_ip = entry.data.get(GW_IP)

    linker = LinktapLocal()
    linker.set_ip(gw_ip)
    try:
        gw_id = await linker.get_gw_id()
    except JSONDecodeError:
        try:
            await asyncio.sleep(random.randint(1,3))
            gw_id = await linker.get_gw_id()
        except JSONDecodeError:
            await asyncio.sleep(random.randint(1,3))
            gw_id = await linker.get_gw_id()

    _LOGGER.debug(f"Found GW_ID: {gw_id}")

    gateway_config = await linker.get_gw_config(gw_id)
    if "end_dev" not in gateway_config:
        raise IntegrationError("Linktap Gateway needs to be updated")

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
        coordinator = LinktapCoordinator(hass, linker, coordinator_conf, tap_id)
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

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"conf": conf}
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
    def __init__(self, hass, linker, conf, tap_id):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
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

    def get_gw_id(self):
        return self.conf[GW_ID]

    async def async_set_water_plan_pause(self, hours):
        """Safely set or clear this tap's watering-plan pause.

        LinkTap issue #88 is destructive: a second positive cmd 18 while the
        watering plan is already paused can deactivate the plan, even though
        the gateway returns ret=0. Refresh immediately before the decision and
        refuse repeated positive pause requests rather than risking plan loss.
        """
        hours = int(hours)
        if hours < 0:
            raise HomeAssistantError("Water plan pause duration cannot be negative")

        async with self._pause_lock:
            # Bypass the coordinator refresh debouncer: the safety decision must
            # use a fresh gateway state, not a recently cached is_paused value.
            await self.async_refresh()
            if not self.last_update_success:
                raise HomeAssistantError(
                    "Unable to verify the current LinkTap water plan pause state; "
                    "no pause command was sent."
                )

            is_paused = bool((self.data or {}).get("is_paused", False))

            if hours > 0 and is_paused:
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

            if hours == 0 and not is_paused:
                _LOGGER.debug(
                    "Water plan for LinkTap %s is already unpaused; no command sent",
                    self.tap_id,
                )
                return

            gw_id = self.get_gw_id()
            success = await self.tap_api.pause_tap(gw_id, self.tap_id, hours)
            if not success:
                raise HomeAssistantError(
                    f"LinkTap gateway rejected water plan pause request for {self.tap_id}"
                )

            await self.async_refresh()
            if not self.last_update_success:
                raise HomeAssistantError(
                    "LinkTap gateway accepted the water plan pause request, but "
                    "Home Assistant could not verify the resulting gateway state."
                )

            expected_paused = hours > 0
            actual_paused = bool((self.data or {}).get("is_paused", False))
            if actual_paused != expected_paused:
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

        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(10):
                return await self.tap_api.fetch_data(gw_id, self.tap_id)
        except:# ApiAuthError as err:
            await asyncio.sleep(random.randint(1,3))
            async with async_timeout.timeout(10):
                return await self.tap_api.fetch_data(gw_id, self.tap_id)
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
        #    raise ConfigEntryAuthFailed from err
        #except ApiError as err:
        #    raise UpdateFailed(f"Error communicating with API: {err}")

async def async_reload_entry(hass: core.HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when it changed."""
    await hass.config_entries.async_reload(entry.entry_id)
