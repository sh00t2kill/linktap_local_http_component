"""Config flow to configure."""
from __future__ import annotations

import ipaddress
import logging
import secrets
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector

from .const import (
    CONF_MAX_WATERING_DURATION,
    CONF_MAX_WATERING_VOLUME,
    CONF_WATERING_SAFETY_LIMITS,
    DEFAULT_NAME,
    DOMAIN,
    GW_IP,
    NAME,
    NATIVE_MAX_WATERING_DURATION,
    NATIVE_MAX_WATERING_VOLUME,
    TAP_ID,
)

_LOGGER = logging.getLogger(__name__)


def _validated_gateway_ip(value: str) -> str | None:
    """Return a normalized IPv4 gateway address, or None if invalid."""
    candidate = value.strip()
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None

    if address.version != 4:
        return None
    return str(address)


@config_entries.HANDLERS.register(DOMAIN)
class LinktapFlowHandler(config_entries.ConfigFlow):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Create the LinkTap options flow."""
        return LinktapOptionsFlowHandler()

    async def async_step_user(self, user_input=None):
        """Handle a flow start."""
        _LOGGER.debug(f"Starting async_step_user of {DEFAULT_NAME}")
        errors = {}

        if user_input is not None:
            gateway_ip = _validated_gateway_ip(user_input[GW_IP])
            if gateway_ip is None:
                errors[GW_IP] = "invalid_gateway_ip"
            else:
                normalized_input = dict(user_input)
                normalized_input[GW_IP] = gateway_ip
                await self.async_set_unique_id(secrets.token_hex(8))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=DEFAULT_NAME, data=normalized_input
                )

        schema = vol.Schema({vol.Required(GW_IP, default=GW_IP): str})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class LinktapOptionsFlowHandler(OptionsFlow):
    """Configure optional per-device instant-watering safety ceilings.

    The integration already registers a ConfigEntry update listener in __init__.py
    which reloads the entry after options change. Use plain OptionsFlow here so
    the same change is not also reloaded by OptionsFlowWithReload.
    """

    def __init__(self) -> None:
        self._tap_id: str | None = None
        self._tap_name: str | None = None

    def _entry_conf(self) -> dict[str, Any]:
        """Return the loaded runtime configuration for this config entry."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(
            self.config_entry.entry_id, {}
        )
        return entry_data.get("conf", {})

    def _taps(self) -> list[dict[str, Any]]:
        """Return taps currently loaded for this config entry."""
        return self._entry_conf().get("taps", [])

    def _volume_unit(self) -> str:
        """Return the gateway's configured native volume unit."""
        return self._entry_conf().get("vol_unit", "L")

    def _ha_device_name(self, tap: dict[str, Any]) -> str:
        """Return the Home Assistant device name, falling back to gateway name."""
        device = dr.async_get(self.hass).async_get_device(
            identifiers={(DOMAIN, tap[TAP_ID])}
        )
        if device is not None:
            return device.name_by_user or device.name or tap[NAME]
        return tap[NAME]

    async def async_step_init(self, user_input=None):
        """Choose a tap when needed, then configure its limits."""
        taps = self._taps()
        if not taps:
            return self.async_abort(reason="integration_not_loaded")

        if len(taps) == 1:
            self._tap_id = taps[0][TAP_ID]
            self._tap_name = self._ha_device_name(taps[0])
            return await self.async_step_limits()

        if user_input is not None:
            self._tap_id = user_input["tap_id"]
            selected = next(
                (tap for tap in taps if tap[TAP_ID] == self._tap_id),
                None,
            )
            if selected is None:
                return self.async_abort(reason="tap_not_found")
            self._tap_name = self._ha_device_name(selected)
            return await self.async_step_limits()

        options = [
            selector.SelectOptionDict(
                value=tap[TAP_ID],
                label=self._ha_device_name(tap),
            )
            for tap in taps
        ]
        schema = vol.Schema(
            {
                vol.Required("tap_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_limits(self, user_input=None):
        """Configure independent optional safety ceilings for one tap."""
        if self._tap_id is None:
            return await self.async_step_init()

        all_limits = dict(
            self.config_entry.options.get(CONF_WATERING_SAFETY_LIMITS, {})
        )
        current = dict(all_limits.get(self._tap_id, {}))

        if user_input is not None:
            updated = {}
            if CONF_MAX_WATERING_DURATION in user_input:
                updated[CONF_MAX_WATERING_DURATION] = int(
                    user_input[CONF_MAX_WATERING_DURATION]
                )
            if CONF_MAX_WATERING_VOLUME in user_input:
                updated[CONF_MAX_WATERING_VOLUME] = int(
                    user_input[CONF_MAX_WATERING_VOLUME]
                )

            if updated:
                all_limits[self._tap_id] = updated
            else:
                all_limits.pop(self._tap_id, None)

            new_options = dict(self.config_entry.options)
            if all_limits:
                new_options[CONF_WATERING_SAFETY_LIMITS] = all_limits
            else:
                new_options.pop(CONF_WATERING_SAFETY_LIMITS, None)

            # Existing integration update listener reloads the entry.
            return self.async_create_entry(data=new_options)

        schema = vol.Schema(
            {
                vol.Optional(CONF_MAX_WATERING_DURATION): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5,
                        max=NATIVE_MAX_WATERING_DURATION,
                        step=5,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Optional(CONF_MAX_WATERING_VOLUME): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10,
                        max=NATIVE_MAX_WATERING_VOLUME,
                        step=10,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement=self._volume_unit(),
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="limits",
            data_schema=self.add_suggested_values_to_schema(schema, current),
            description_placeholders={
                "tap_name": self._tap_name or self._tap_id,
            },
        )
