"""Tests for LinktapCoordinator, focusing on async_set_water_plan_pause."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.linktap import LinktapCoordinator
from custom_components.linktap.const import GW_ID, GW_IP
from tests.conftest import MOCK_GW_ID, MOCK_GW_IP, MOCK_TAP_ID, MOCK_TAP_STATUS


@pytest.fixture
def coordinator(hass, mock_linktap_api):
    """Return a LinktapCoordinator with pre-populated data and a mocked API."""
    conf = {GW_IP: MOCK_GW_IP, GW_ID: MOCK_GW_ID}
    c = LinktapCoordinator(hass, mock_linktap_api, conf, MOCK_TAP_ID)
    c.data = dict(MOCK_TAP_STATUS)
    c.last_update_success = True
    return c


def _make_refresh(coordinator, *, success=True, paused=False):
    """Return an async side_effect for async_refresh that sets coordinator state."""

    async def _refresh():
        coordinator.last_update_success = success
        coordinator.data = {**MOCK_TAP_STATUS, "is_paused": paused}

    return _refresh


# ---------------------------------------------------------------------------
# async_set_water_plan_pause
# ---------------------------------------------------------------------------


class TestAsyncSetWaterPlanPause:
    async def test_negative_hours_raises_immediately(self, coordinator):
        with pytest.raises(HomeAssistantError, match="cannot be negative"):
            await coordinator.async_set_water_plan_pause(-1)

    async def test_refresh_failure_before_decision_raises(self, coordinator):
        with patch.object(
            coordinator,
            "async_refresh",
            side_effect=_make_refresh(coordinator, success=False),
        ):
            with pytest.raises(HomeAssistantError, match="Unable to verify"):
                await coordinator.async_set_water_plan_pause(1)

    async def test_already_paused_positive_hours_raises(self, coordinator):
        """Sending a second positive pause risks deactivating the plan (issue #88)."""
        with patch.object(
            coordinator,
            "async_refresh",
            side_effect=_make_refresh(coordinator, paused=True),
        ):
            with pytest.raises(HomeAssistantError, match="already paused"):
                await coordinator.async_set_water_plan_pause(2)

    async def test_unpause_when_already_unpaused_is_noop(self, coordinator):
        refresh_calls = []

        async def _refresh():
            refresh_calls.append(1)
            coordinator.last_update_success = True
            coordinator.data = {**MOCK_TAP_STATUS, "is_paused": False}

        with patch.object(coordinator, "async_refresh", side_effect=_refresh):
            await coordinator.async_set_water_plan_pause(0)

        coordinator.tap_api.pause_tap.assert_not_called()

    async def test_pause_calls_api_with_correct_args(self, coordinator):
        refresh_count = [0]

        async def _refresh():
            refresh_count[0] += 1
            coordinator.last_update_success = True
            # Second refresh (post-command) reflects the paused state.
            paused = refresh_count[0] >= 2
            coordinator.data = {**MOCK_TAP_STATUS, "is_paused": paused}

        coordinator.tap_api.pause_tap.return_value = True

        with patch.object(coordinator, "async_refresh", side_effect=_refresh):
            await coordinator.async_set_water_plan_pause(3)

        coordinator.tap_api.pause_tap.assert_called_once_with(
            MOCK_GW_ID, MOCK_TAP_ID, 3
        )

    async def test_unpause_calls_api_and_verifies_unpaused_state(self, coordinator):
        coordinator.data = {**MOCK_TAP_STATUS, "is_paused": True}
        refresh_count = [0]

        async def _refresh():
            refresh_count[0] += 1
            coordinator.last_update_success = True
            # First refresh (safety check): still paused.
            # Second refresh (post-command): now unpaused.
            paused = refresh_count[0] < 2
            coordinator.data = {**MOCK_TAP_STATUS, "is_paused": paused}

        coordinator.tap_api.pause_tap.return_value = True

        with patch.object(coordinator, "async_refresh", side_effect=_refresh):
            await coordinator.async_set_water_plan_pause(0)

        coordinator.tap_api.pause_tap.assert_called_once_with(
            MOCK_GW_ID, MOCK_TAP_ID, 0
        )

    async def test_gateway_rejection_raises(self, coordinator):
        coordinator.tap_api.pause_tap.return_value = False

        with patch.object(
            coordinator,
            "async_refresh",
            side_effect=_make_refresh(coordinator, paused=False),
        ):
            with pytest.raises(HomeAssistantError, match="rejected"):
                await coordinator.async_set_water_plan_pause(1)

    async def test_state_mismatch_after_pause_raises(self, coordinator):
        """Gateway accepted the command but reported state did not change."""
        coordinator.tap_api.pause_tap.return_value = True

        async def _refresh():
            coordinator.last_update_success = True
            # State stubbornly stays unpaused despite a successful pause command.
            coordinator.data = {**MOCK_TAP_STATUS, "is_paused": False}

        with patch.object(coordinator, "async_refresh", side_effect=_refresh):
            with pytest.raises(HomeAssistantError, match="did not report"):
                await coordinator.async_set_water_plan_pause(2)

    async def test_second_refresh_failure_after_pause_raises(self, coordinator):
        coordinator.tap_api.pause_tap.return_value = True
        refresh_count = [0]

        async def _refresh():
            refresh_count[0] += 1
            if refresh_count[0] == 1:
                coordinator.last_update_success = True
                coordinator.data = {**MOCK_TAP_STATUS, "is_paused": False}
            else:
                # Post-command refresh fails.
                coordinator.last_update_success = False

        with patch.object(coordinator, "async_refresh", side_effect=_refresh):
            with pytest.raises(HomeAssistantError, match="could not verify"):
                await coordinator.async_set_water_plan_pause(1)
