from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, TAP_ID, GW_ID, GW_IP, NAME


class LinktapFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Revogi."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> LinktapOptionFlowHandler:
        """Get the options flow for this handler."""
        return LinktapOptionFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initiated by the user."""
        if user_input is not None:
            return self.async_create_entry(
                title= "Linktap Local API",
                data = {},
                options={
                    GW_IP: user_input[GW_IP],
                    TAP_ID: user_input[TAP_ID],
                    #GW_ID: user_input[GW_ID],
                    NAME: user_input[NAME],
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(GW_IP, default="IP of Gateway"): str,
                    vol.Required(TAP_ID, default="ID OF Tap"): str,
                    #vol.Required(GW_ID, default="ID of Gateway"): str,
                    vol.Required(NAME, default="My Tap Name"): str,
                }
            ),
        )


class LinktapOptionFlowHandler(OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="Linktap Local API", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        GW_IP,
                        default=self.config_entry.options.get(GW_IP),
                    ): str,
                    vol.Required(
                        TAP_ID,
                        default=self.config_entry.options.get(TAP_ID),
                    ): str,
                    #vol.Required(
                    #    GW_ID,
                    #    default=self.config_entry.options.get(GW_ID),
                    #): str,
                    vol.Required(
                        NAME,
                        default=self.config_entry.options.get(NAME),
                    ): str,
                }
            ),
        )
