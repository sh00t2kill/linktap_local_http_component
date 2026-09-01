"""Tests for the LinktapFlowHandler config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.linktap.config_flow import _validated_gateway_ip
from custom_components.linktap.const import DOMAIN, GW_IP

# ---------------------------------------------------------------------------
# _validated_gateway_ip  (pure function, no HA needed)
# ---------------------------------------------------------------------------


class TestValidatedGatewayIp:
    def test_valid_ipv4_is_returned_unchanged(self):
        assert _validated_gateway_ip("192.168.1.100") == "192.168.1.100"

    def test_leading_and_trailing_whitespace_is_stripped(self):
        assert _validated_gateway_ip("  10.0.0.1  ") == "10.0.0.1"

    def test_invalid_string_returns_none(self):
        assert _validated_gateway_ip("not-an-ip") is None

    def test_ipv6_address_is_rejected(self):
        assert _validated_gateway_ip("::1") is None

    def test_empty_string_returns_none(self):
        assert _validated_gateway_ip("") is None

    def test_hostname_is_rejected(self):
        assert _validated_gateway_ip("myhub.local") is None


# ---------------------------------------------------------------------------
# Full config flow via hass.config_entries.flow
# ---------------------------------------------------------------------------


class TestLinktapFlowHandler:
    async def test_form_is_shown_on_initial_load(
        self, hass, enable_custom_integrations
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

    async def test_invalid_ip_shows_error_and_rerenders_form(
        self, hass, enable_custom_integrations
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={GW_IP: "not-a-valid-ip"},
        )
        assert result["type"] == FlowResultType.FORM
        assert result["errors"].get(GW_IP) == "invalid_gateway_ip"

    async def test_valid_ip_creates_config_entry(
        self, hass, enable_custom_integrations
    ):
        # Prevent async_setup_entry from running so no background threads are spawned.
        with patch(
            "custom_components.linktap.async_setup_entry", AsyncMock(return_value=True)
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={GW_IP: "192.168.1.100"},
            )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][GW_IP] == "192.168.1.100"

    async def test_ip_is_normalised_before_storage(
        self, hass, enable_custom_integrations
    ):
        """Whitespace around the IP must be stripped before the entry is created."""
        with patch(
            "custom_components.linktap.async_setup_entry", AsyncMock(return_value=True)
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={GW_IP: "  10.0.0.5  "},
            )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][GW_IP] == "10.0.0.5"
