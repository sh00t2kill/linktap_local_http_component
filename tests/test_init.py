"""Integration tests for async_setup_entry and async_unload_entry."""

from __future__ import annotations

import asyncio
from json.decoder import JSONDecodeError
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryNotReady, IntegrationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.linktap import async_setup_entry, async_unload_entry
from custom_components.linktap.const import DOMAIN, GW_ID, GW_IP
from tests.conftest import MOCK_GW_CONFIG, MOCK_GW_ID, MOCK_GW_IP


@pytest.fixture
def config_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={GW_IP: MOCK_GW_IP}, options={})
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def patched_setup(hass, mock_linktap_api):
    """Context manager that patches LinktapLocal and async_forward_entry_setups."""

    class _Ctx:
        def __enter__(self):
            self._p1 = patch(
                "custom_components.linktap.LinktapLocal",
                return_value=mock_linktap_api,
            )
            self._p2 = patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                AsyncMock(return_value=True),
            )
            self._p1.start()
            self._p2.start()
            return self

        def __exit__(self, *args):
            self._p1.stop()
            self._p2.stop()

    return _Ctx()


async def test_setup_entry_returns_true(
    hass, config_entry, patched_setup, mock_linktap_api
):
    with patched_setup:
        result = await async_setup_entry(hass, config_entry)
    assert result is True


async def test_setup_entry_stores_gw_id_and_taps(
    hass, config_entry, patched_setup, mock_linktap_api
):
    with patched_setup:
        await async_setup_entry(hass, config_entry)

    conf = hass.data[DOMAIN][config_entry.entry_id]["conf"]
    assert conf[GW_ID] == MOCK_GW_ID
    assert len(conf["taps"]) == 1
    tap = conf["taps"][0]
    assert tap["ID of Tap"] == MOCK_GW_CONFIG["end_dev"][0]
    assert tap["Friendly Name of Tap"] == MOCK_GW_CONFIG["dev_name"][0]


async def test_setup_entry_stores_volume_unit(
    hass, config_entry, patched_setup, mock_linktap_api
):
    with patched_setup:
        await async_setup_entry(hass, config_entry)

    conf = hass.data[DOMAIN][config_entry.entry_id]["conf"]
    assert conf["vol_unit"] == "L"


async def test_setup_entry_forwards_all_platforms(hass, config_entry, mock_linktap_api):
    forward_mock = AsyncMock(return_value=True)
    with (
        patch("custom_components.linktap.LinktapLocal", return_value=mock_linktap_api),
        patch.object(hass.config_entries, "async_forward_entry_setups", forward_mock),
    ):
        await async_setup_entry(hass, config_entry)

    from custom_components.linktap.const import PLATFORMS

    args = forward_mock.call_args
    assert set(args[0][1]) == set(PLATFORMS)


async def test_setup_entry_raises_when_gw_config_missing_end_dev(
    hass, config_entry, mock_linktap_api
):
    bad_config = {k: v for k, v in MOCK_GW_CONFIG.items() if k != "end_dev"}
    mock_linktap_api.get_gw_config.return_value = bad_config

    with (
        patch("custom_components.linktap.LinktapLocal", return_value=mock_linktap_api),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=True),
        ),
        pytest.raises(IntegrationError, match="needs to be updated"),
    ):
        await async_setup_entry(hass, config_entry)


@pytest.mark.parametrize(
    "error",
    [
        aiohttp.ClientConnectionError("gateway unavailable"),
        asyncio.TimeoutError(),
        JSONDecodeError("invalid response", "", 0),
    ],
)
async def test_setup_entry_retries_when_gateway_id_unavailable(
    hass, config_entry, mock_linktap_api, error
):
    mock_linktap_api.get_gw_id.side_effect = error

    with (
        patch("custom_components.linktap.LinktapLocal", return_value=mock_linktap_api),
        pytest.raises(
            ConfigEntryNotReady,
            match=f"Unable to communicate with LinkTap gateway at {MOCK_GW_IP}",
        ),
    ):
        await async_setup_entry(hass, config_entry)

    mock_linktap_api.get_gw_config.assert_not_awaited()
    assert config_entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_setup_entry_retries_when_gateway_config_unavailable(
    hass, config_entry, mock_linktap_api
):
    mock_linktap_api.get_gw_config.side_effect = aiohttp.ClientConnectionError(
        "gateway unavailable"
    )

    with (
        patch("custom_components.linktap.LinktapLocal", return_value=mock_linktap_api),
        pytest.raises(
            ConfigEntryNotReady,
            match=f"Unable to communicate with LinkTap gateway at {MOCK_GW_IP}",
        ),
    ):
        await async_setup_entry(hass, config_entry)

    mock_linktap_api.get_gw_id.assert_awaited_once()
    assert config_entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_unload_entry_removes_domain_data(hass, config_entry, mock_linktap_api):
    with (
        patch("custom_components.linktap.LinktapLocal", return_value=mock_linktap_api),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=True),
        ),
        patch.object(
            hass.config_entries,
            "async_unload_platforms",
            AsyncMock(return_value=True),
        ),
    ):
        await async_setup_entry(hass, config_entry)
        result = await async_unload_entry(hass, config_entry)

    assert result is True
    assert config_entry.entry_id not in hass.data.get(DOMAIN, {})
