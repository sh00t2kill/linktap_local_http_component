import asyncio
import logging
from datetime import timedelta

import async_timeout
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from h11 import Data
from homeassistant import core
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (DataUpdateCoordinator,
                                                      UpdateFailed)

from .const import DOMAIN, TAP_ID, GW_ID, GW_IP, NAME
from .linktap_local import LinktapLocal

PLATFORMS = ['switch', 'binary_sensor', 'sensor']

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: core.HomeAssistant, entry: ConfigEntry)-> bool:
    """Set up the platform.
    @NOTE: `config` is the full dict from `configuration.yaml`.
    :returns: A boolean to indicate that initialization was successful.
    """

    tap_id = entry.options[TAP_ID]
    #gw_id = entry.options[GW_ID]
    gw_ip = entry.options[GW_IP]
    name  = entry.options[NAME]

    linker = LinktapLocal()
    linker.set_ip(gw_ip)
    gw_id = await linker.get_gw_id()
    _LOGGER.debug(f"Found GW_ID: {gw_id}")

    conf = {
        GW_IP: gw_ip,
        TAP_ID: tap_id,
        GW_ID: gw_id,
        NAME: name
    }

    coordinator = LinktapCoordinator(hass, linker, conf)
    await coordinator.async_refresh()
    _LOGGER.debug("Coordinator has synced")

    hass.data[DOMAIN] = {
        "conf": conf,
        "coordinator": coordinator,
    }

    #_LOGGER.debug("Create Device")
    #device_registry = dr.async_get(hass)
    #device_info = coordinator.get_device()
    #device_registry.async_get_or_create(
    #    config_entry_id=entry.entry_id,
    #    identifiers=device_info['identifiers'],
    #    manufacturer=device_info['manufacturer'],
    #    name=device_info['name']
    #)

    _LOGGER.debug("Load Number")
    hass.async_create_task(async_load_platform(hass, "number", DOMAIN, {}, conf))
    _LOGGER.debug("Load Binary Sensors")
    hass.async_create_task(async_load_platform(hass, "binary_sensor", DOMAIN, {}, conf))
    _LOGGER.debug("Load Sensors")
    hass.async_create_task(async_load_platform(hass, "sensor", DOMAIN, {}, conf))
    _LOGGER.debug("Load Switch")
    hass.async_create_task(async_load_platform(hass, "switch", DOMAIN, {}, conf))

    return True

class LinktapCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, linker, conf):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=10),
        )
        self.tap_api = linker
        self.conf = conf
        self.hass = hass

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        tap_id = self.conf[TAP_ID]
        gw_id = self.conf[GW_ID]

        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(10):
                return await self.tap_api.fetch_data(gw_id, tap_id)
        except ApiAuthError as err:
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
            raise ConfigEntryAuthFailed from err
        except ApiError as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    def get_device(self):
        return DeviceInfo(
            #entry_type=DeviceEntryType.SERVICE,
            identifiers={
                (DOMAIN, self.hass.data[DOMAIN]["conf"][TAP_ID])
            },
            name=self.hass.data[DOMAIN]["conf"][NAME],
            manufacturer="Linktap",
            configuration_url="http://" + self.hass.data[DOMAIN]["conf"][GW_IP] + "/"
        )

