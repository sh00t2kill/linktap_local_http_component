"""Config flow to configure."""
from __future__ import annotations

import logging
import secrets

import voluptuous as vol
from homeassistant import config_entries

from .const import DEFAULT_NAME, DOMAIN, GW_ID, GW_IP, NAME, TAP_ID

_LOGGER = logging.getLogger(__name__)

@config_entries.HANDLERS.register(DOMAIN)
class LinktapFlowHandler(config_entries.ConfigFlow):

    VERSION = 1
    def __init__(self):
        super().__init__()

    async def async_step_user(self, user_input=None):
        """Handle a flow start."""
        _LOGGER.debug(f"Starting async_step_user of {DEFAULT_NAME}")

        errors = None

        if user_input is not None:
            await self.async_set_unique_id(secrets.token_hex(8))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=DEFAULT_NAME, data=user_input)

        new_user_input = {
            vol.Required(GW_IP, default=GW_IP): str,
        }

        schema = vol.Schema(new_user_input)

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
