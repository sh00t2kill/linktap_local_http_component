"""Integration tests against the mocked LinkTap local API server."""

from __future__ import annotations

import os

import pytest

from custom_components.linktap.linktap_local import LinktapLocal

MOCK_GW_ID = "BB54B60C004B12BB"
MOCK_TAP_ID = "1234567890"


pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


@pytest.fixture(autouse=True)
def enable_socket_for_mocked_api(socket_enabled):
    pass


@pytest.fixture
def linktap_mock_api_host():
    host = os.environ.get("LINKTAP_MOCK_API_HOST")
    if not host:
        pytest.skip("LINKTAP_MOCK_API_HOST is not set")
    return host


@pytest.fixture
def linktap(linktap_mock_api_host):
    client = LinktapLocal()
    client.set_ip(linktap_mock_api_host)
    return client


async def test_get_gw_id_from_mocked_local_api(linktap):
    assert await linktap.get_gw_id() == MOCK_GW_ID


async def test_watering_state_round_trips_through_mocked_local_api(linktap):
    assert await linktap.turn_off(MOCK_GW_ID, MOCK_TAP_ID) is True

    off_status = await linktap.get_tap_status(MOCK_GW_ID, MOCK_TAP_ID)
    assert off_status["ret"] == 0
    assert off_status["is_watering"] is False

    assert await linktap.turn_on(MOCK_GW_ID, MOCK_TAP_ID, seconds=120) is True

    on_status = await linktap.get_tap_status(MOCK_GW_ID, MOCK_TAP_ID)
    assert on_status["ret"] == 0
    assert on_status["is_watering"] is True
    assert on_status["remain_duration"] == 120


async def test_pause_state_round_trips_through_mocked_local_api(linktap):
    assert await linktap.pause_tap(MOCK_GW_ID, MOCK_TAP_ID, hours=2) is True

    paused_status = await linktap.get_tap_status(MOCK_GW_ID, MOCK_TAP_ID)
    assert paused_status["ret"] == 0
    assert paused_status["is_paused"] is True

    assert await linktap.pause_tap(MOCK_GW_ID, MOCK_TAP_ID, hours=0) is True

    unpaused_status = await linktap.get_tap_status(MOCK_GW_ID, MOCK_TAP_ID)
    assert unpaused_status["ret"] == 0
    assert unpaused_status["is_paused"] is False
