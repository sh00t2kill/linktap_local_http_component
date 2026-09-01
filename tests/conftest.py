"""Shared fixtures and test data for the linktap integration tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.linktap.const import DOMAIN, GW_IP

MOCK_GW_IP = "192.168.1.100"
MOCK_GW_ID = "abc123gateway"
MOCK_TAP_ID = "deadbeef001"
MOCK_TAP_NAME = "Garden Tap"

# Represents a typical status payload returned by the LinkTap gateway.
MOCK_TAP_STATUS = {
    "gw_id": MOCK_GW_ID,
    "ret": 0,
    "is_rf_linked": True,
    "is_fall": False,
    "is_cutoff": False,
    "is_leak": False,
    "is_clog": False,
    "is_broken": False,
    "is_manual_mode": False,
    "is_watering": False,
    "is_paused": False,
    "signal": 80,
    "battery": 95,
    "total_duration": 0,
    "remain_duration": 0,
    "speed": 0.0,
    "volume": 0.0,
    "volume_limit": 0,
    "failsafe_duration": 3600,
    "plan_mode": 0,
    "plan_sn": 0,
    "plan_mode_string": "None",
}

# Represents a typical gateway config payload returned by cmd 16.
MOCK_GW_CONFIG = {
    "gw_id": MOCK_GW_ID,
    "ret": 0,
    "end_dev": [MOCK_TAP_ID],
    "dev_name": [MOCK_TAP_NAME],
    "vol_unit": "L",
    "ver": "4.38",
}


@pytest.fixture
def mock_config_entry():
    """Return a MockConfigEntry pre-loaded with the test gateway IP."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={GW_IP: MOCK_GW_IP},
        options={},
    )


@pytest.fixture
def mock_linktap_api():
    """Return a pre-configured AsyncMock for LinktapLocal."""
    mock = AsyncMock()
    mock.get_gw_id.return_value = MOCK_GW_ID
    mock.get_gw_config.return_value = dict(MOCK_GW_CONFIG)
    mock.fetch_data.return_value = dict(MOCK_TAP_STATUS)
    mock.turn_on.return_value = True
    mock.turn_off.return_value = True
    mock.pause_tap.return_value = True
    mock.dismiss_alert.return_value = True
    return mock
