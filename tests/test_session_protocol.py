"""CMD18 plan / CMD19 session protocol, entity and latency regressions."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.linktap import (
    LinktapCoordinator,
    binary_sensor,
    button,
    number,
    select,
    sensor,
    switch,
)
from custom_components.linktap.const import DOMAIN, GW_ID, GW_IP, NAME, TAP_ID
from custom_components.linktap.diagnostics import async_get_config_entry_diagnostics
from custom_components.linktap.linktap_local import (
    LinktapLocal,
    parse_gateway_firmware_version,
    supports_session_pause,
)
from custom_components.linktap.valve import LinktapValve
from tests.conftest import MOCK_GW_ID, MOCK_GW_IP, MOCK_TAP_ID, MOCK_TAP_STATUS


@pytest.fixture
def session(hass, mock_linktap_api):
    """Build a revised-firmware coordinator without network access."""
    mock_linktap_api.session_pause_supported = True
    coordinator = LinktapCoordinator(
        hass, mock_linktap_api, {GW_ID: MOCK_GW_ID, GW_IP: MOCK_GW_IP}, MOCK_TAP_ID
    )
    coordinator.data = {**MOCK_TAP_STATUS, "is_watering": True, "remain_duration": 120}
    coordinator.last_update_success = True
    return coordinator


def tap_for(coordinator):
    """Return an entity's runtime tap definition."""
    return {
        TAP_ID: MOCK_TAP_ID,
        NAME: "Garden",
        GW_IP: MOCK_GW_IP,
        "coordinator": coordinator,
    }


def refresh_sequence(coordinator, states):
    """Apply each sample once, retaining the final sample for further polls."""
    iterator = iter(states)

    async def refresh():
        state = next(iterator, None)
        coordinator.last_update_success = state is not False
        if isinstance(state, dict):
            coordinator.data = {**MOCK_TAP_STATUS, **state}

    return AsyncMock(side_effect=refresh)


@pytest.mark.parametrize("option", [0, 1])
async def test_cmd19_pause_payload_and_plan_cmd18(option):
    client = LinktapLocal()
    client.session_pause_supported = True
    client._request = AsyncMock(return_value={"ret": 0})
    assert await client.pause_tap(MOCK_GW_ID, MOCK_TAP_ID, 2)
    assert await client.pause_tap(MOCK_GW_ID, MOCK_TAP_ID, 0)
    await client.cmd19(MOCK_GW_ID, MOCK_TAP_ID, 0.1, option)
    await client.cmd19(MOCK_GW_ID, MOCK_TAP_ID, 0)
    payloads = [call.args[0] for call in client._request.await_args_list]
    assert [payload["cmd"] for payload in payloads] == [18, 18, 19, 19]
    assert [payload["duration"] for payload in payloads] == [2, 0, 0.1, 0]
    assert "option" not in payloads[0]
    assert payloads[2]["option"] == option
    assert "option" not in payloads[3]


@pytest.mark.parametrize("option", [-1, 2, 99, None, "1", 1.0, True])
async def test_invalid_option_cannot_reach_gateway(session, option):
    with pytest.raises(HomeAssistantError, match="option must be"):
        await session.async_pause_current_watering(0.1, option)
    session.tap_api.cmd19.assert_not_awaited()
    client = LinktapLocal()
    client.session_pause_supported = True
    client._request = AsyncMock()
    with pytest.raises(ValueError, match="option must be"):
        await client.cmd19(MOCK_GW_ID, MOCK_TAP_ID, 0.1, option)
    client._request.assert_not_awaited()


@pytest.mark.parametrize("hours", [float("nan"), float("inf"), -1, 0, 241, "bad", None])
async def test_invalid_pause_duration(session, hours):
    with pytest.raises(HomeAssistantError, match="0.01 to 240"):
        await session.async_pause_current_watering(hours)
    session.tap_api.cmd19.assert_not_awaited()


@pytest.mark.parametrize(
    "watering,remaining,error",
    [
        (False, 120, "not currently watering"),
        (True, 15, "exceed 15"),
        (True, 0, "exceed 15"),
        (True, 14, "exceed 15"),
        (True, None, "verify remaining"),
        (True, float("nan"), "verify remaining"),
    ],
)
async def test_pause_preconditions(session, watering, remaining, error):
    session.async_refresh = refresh_sequence(
        session,
        [
            {
                "is_watering": watering,
                "remain_duration": remaining,
            }
        ],
    )
    with pytest.raises(HomeAssistantError, match=error):
        await session.async_pause_current_watering(0.1)
    session.tap_api.cmd19.assert_not_awaited()


@pytest.mark.parametrize("option", [0, 1])
async def test_session_pause_ignores_plan_pause_and_tolerates_delay(session, option):
    active = {"is_watering": True, "remain_duration": 16, "is_paused": True}
    session.async_refresh = refresh_sequence(
        session,
        [
            active,
            active,
            active,
            {
                **active,
                "is_watering": False,
                "is_paused_sess": True,
            },
        ],
    )
    with patch("custom_components.linktap.COMMAND_VERIFY_INTERVAL", 0):
        await session.async_pause_current_watering(0.1, option)
    session.tap_api.cmd19.assert_awaited_once_with(
        MOCK_GW_ID, MOCK_TAP_ID, 0.1, option=option
    )
    session.tap_api.pause_tap.assert_not_awaited()
    assert session.plan_paused is True
    assert session.session_paused is True
    assert session.current_pause_mode == option
    assert session.async_refresh.await_count == 4


async def test_resume_duration_zero_and_independent_plan_state(session):
    paused = {"is_paused": True, "is_paused_sess": True}
    session.async_refresh = refresh_sequence(
        session,
        [
            paused,
            paused,
            {
                "is_paused": True,
                "is_paused_sess": False,
                "is_watering": True,
            },
        ],
    )
    with patch("custom_components.linktap.COMMAND_VERIFY_INTERVAL", 0):
        await session.async_resume_current_watering()
    session.tap_api.cmd19.assert_awaited_once_with(MOCK_GW_ID, MOCK_TAP_ID, 0)
    assert session.plan_paused is True
    assert session.session_paused is False
    assert session.current_pause_until is None


@pytest.mark.parametrize("plan_paused,session_paused", [(True, False), (False, True)])
@pytest.mark.parametrize("envelope", ["flat", "dict", "list"])
async def test_independent_cmd3_parsing(session, plan_paused, session_paused, envelope):
    status = {
        **MOCK_TAP_STATUS,
        "dev_id": MOCK_TAP_ID,
        "is_paused": int(plan_paused),
        "is_paused_sess": int(session_paused),
    }
    payload = (
        status
        if envelope == "flat"
        else {
            "cmd": 3,
            "gw_id": MOCK_GW_ID,
            "dev_stat": status if envelope == "dict" else [{"dev_id": "other"}, status],
        }
    )
    client = LinktapLocal()
    client._request = AsyncMock(return_value=payload)
    session.data = session._validated_status(
        await client.fetch_data(MOCK_GW_ID, MOCK_TAP_ID)
    )
    assert session.plan_paused is plan_paused
    assert session.session_paused is session_paused


@pytest.mark.parametrize("plan,paused", [(True, False), (False, True)])
def test_entities_use_separate_states(session, plan, paused):
    session.data = {
        **MOCK_TAP_STATUS,
        "is_paused": plan,
        "is_paused_sess": paused,
        "remain_duration": 100,
    }
    tap = tap_for(session)
    assert switch.LinktapPauseSwitch(session, session.hass, tap).is_on is plan
    assert (
        switch.LinktapCurrentWateringPauseSwitch(session, session.hass, tap).is_on
        is paused
    )
    session.current_pause_until = datetime.now(timezone.utc) + timedelta(minutes=10)
    remaining = sensor.LinktapCurrentPauseRemainingSensor(session, tap)
    assert (remaining.native_value > 0) is paused
    duration = sensor.LinktapSensor(session, session.hass, tap, "remain_duration", "s")
    assert duration.state == (100 if paused else 0)
    flag = binary_sensor.LinktapBinarySensor(
        session, session.hass, tap, "is_paused_sess"
    )
    assert flag.state == ("on" if paused else "off")


@pytest.mark.parametrize("initial", [{"is_watering": True}, {"is_paused_sess": True}])
async def test_cmd7_direct_for_active_and_paused(session, initial):
    session.data.update(initial)
    events = []

    async def stop(*args):
        events.append("CMD7")
        return True

    session.tap_api.turn_off.side_effect = stop
    refresh = refresh_sequence(session, [initial, {"is_paused": True}])

    async def observe():
        events.append("CMD3")
        await refresh()

    session.async_refresh = AsyncMock(side_effect=observe)
    with patch("custom_components.linktap.COMMAND_VERIFY_INTERVAL", 0):
        await session.async_safe_stop_watering()
    assert events == ["CMD7", "CMD3", "CMD3"]
    session.tap_api.cmd19.assert_not_awaited()
    session.tap_api.cmd18.assert_not_awaited()
    session.tap_api.pause_tap.assert_not_awaited()


async def test_safe_stop_requires_both_flags_and_valid_rf(session):
    session.async_refresh = refresh_sequence(
        session,
        [
            {"is_watering": True, "is_paused_sess": False},
            {"is_watering": False, "is_paused_sess": True},
            {"is_watering": False, "is_paused_sess": False, "is_rf_linked": False},
            {"is_watering": False, "is_paused_sess": False, "is_paused": True},
        ],
    )
    with patch("custom_components.linktap.COMMAND_VERIFY_INTERVAL", 0):
        assert await session._async_verify_safe_idle()
    assert session.async_refresh.await_count == 4


@pytest.mark.parametrize("field", ["is_watering", "is_paused_sess", "is_rf_linked"])
async def test_missing_status_flag_cannot_confirm_safe_stop(session, field):
    session.data = dict(MOCK_TAP_STATUS)
    session.data.pop(field)
    session.async_refresh = AsyncMock()
    with patch("custom_components.linktap.COMMAND_VERIFY_TIMEOUT", 0.01):
        assert not await session._async_verify_safe_idle()


@pytest.mark.parametrize("operation", ["pause", "resume", "stop"])
async def test_timeout_diagnostics_include_jims_fields(session, operation):
    state = {
        "is_watering": True,
        "remain_duration": 100,
        "is_paused": True,
        "is_paused_sess": operation == "resume",
        "signal": 82,
        "volume": 20,
        "total_duration": 180,
    }
    session.async_refresh = refresh_sequence(session, [state])
    action = {
        "pause": lambda: session.async_pause_current_watering(1),
        "resume": session.async_resume_current_watering,
        "stop": session.async_safe_stop_watering,
    }[operation]
    with patch("custom_components.linktap.COMMAND_VERIFY_TIMEOUT", 0.01):
        with pytest.raises(HomeAssistantError, match="final observed state") as error:
            await action()
    for field in (
        "is_rf_linked",
        "signal",
        "is_watering",
        "is_paused",
        "is_paused_sess",
        "remain_duration",
        "total_duration",
        "volume",
    ):
        assert field in str(error.value)
        assert field in session.last_session_failure["state"]


async def test_stop_timeout_includes_refresh_io(session):
    session.async_refresh = AsyncMock(side_effect=lambda: None)

    async def slow_refresh():
        await asyncio.sleep(10)

    session.async_refresh.side_effect = slow_refresh
    with patch("custom_components.linktap.COMMAND_VERIFY_TIMEOUT", 0.01):
        with pytest.raises(HomeAssistantError, match="within 30 seconds"):
            await session.async_safe_stop_watering()


async def test_start_tolerates_delayed_cmd3(session):
    session.async_refresh = refresh_sequence(
        session,
        [
            False,
            {},
            {},
            {
                "is_watering": True,
                "is_paused_sess": False,
            },
        ],
    )
    with patch("custom_components.linktap.COMMAND_VERIFY_INTERVAL", 0):
        await session.async_start_watering(120, 5)
    assert session.async_refresh.await_count == 4
    session.tap_api.turn_on.assert_awaited_once_with(MOCK_GW_ID, MOCK_TAP_ID, 120, 5)


@pytest.mark.parametrize("operation", ["pause", "resume"])
async def test_rf_loss_blocks_session_mutation(session, operation):
    session.data.update(is_rf_linked=False, is_paused_sess=True)
    session.async_refresh = AsyncMock()
    with pytest.raises(HomeAssistantError, match="RF-linked"):
        if operation == "pause":
            await session.async_pause_current_watering(1)
        else:
            await session.async_resume_current_watering()
    session.tap_api.cmd19.assert_not_awaited()
    assert (
        switch.LinktapCurrentWateringPauseSwitch(
            session, session.hass, tap_for(session)
        ).is_on
        is None
    )


async def test_rejected_corrupt_volume_cannot_verify_stop(session):
    session.data = dict(MOCK_TAP_STATUS)
    session._validated_status(
        {**MOCK_TAP_STATUS, "volume": 999999, "is_watering": True}
    )
    session.async_refresh = AsyncMock()
    with patch("custom_components.linktap.COMMAND_VERIFY_TIMEOUT", 0.01):
        assert not await session._async_verify_safe_idle()


@pytest.mark.parametrize(
    "version,expected",
    [
        ("S0609502601010000", False),
        ("S0609512601010000", True),
        ("G0609522601010000", True),
        ("S0609532601010000", True),
        ("S060954", True),
        (None, False),
        ("4.38", False),
        ("", False),
        ("060951", False),
        ("1060951", False),
        ("S06x951", False),
    ],
)
def test_firmware_family_gating(version, expected):
    assert supports_session_pause(version) is expected
    if expected:
        assert parse_gateway_firmware_version(version) >= 60951


async def test_unknown_or_failed_config_is_legacy_safe():
    client = LinktapLocal()
    assert not client.session_pause_supported
    client._request = AsyncMock(return_value={"ret": 0, "ver": "S060951build"})
    await client.get_gw_config(MOCK_GW_ID)
    assert client.session_pause_supported
    client._request.return_value = {"ret": 6, "ver": "S060953build"}
    await client.get_gw_config(MOCK_GW_ID)
    assert not client.session_pause_supported
    with pytest.raises(ValueError, match="does not support CMD19"):
        await client.cmd19(MOCK_GW_ID, MOCK_TAP_ID, 1)


async def test_legacy_operations_remain_cmd19_free(session):
    session.tap_api.session_pause_supported = False
    session.async_refresh = refresh_sequence(session, [{}])
    with pytest.raises(HomeAssistantError, match="does not support CMD19"):
        await session.async_pause_current_watering(1)
    with pytest.raises(HomeAssistantError, match="does not support CMD19"):
        await session.async_resume_current_watering()
    await session.async_safe_stop_watering()
    session.tap_api.turn_off.assert_awaited_once()
    assert session.async_refresh.await_count == 1
    session.tap_api.cmd19.assert_not_awaited()


async def test_legacy_stop_sends_before_read_even_if_last_poll_failed(session):
    session.tap_api.session_pause_supported = False
    session.last_update_success = False
    session.data.pop("is_paused_sess")
    session.data.update(is_rf_linked=False, is_watering=True)

    async def refresh():
        session.tap_api.turn_off.assert_awaited_once()
        session.last_update_success = True
        session.data.update(is_rf_linked=True, is_watering=False)

    session.async_refresh = AsyncMock(side_effect=refresh)
    await session.async_safe_stop_watering()
    session.tap_api.pause_tap.assert_not_awaited()
    session.tap_api.cmd19.assert_not_awaited()


async def test_stop_interrupts_start_verification(session):
    checking = asyncio.Event()

    async def refresh():
        if not session.tap_api.turn_off.await_count:
            checking.set()
            await asyncio.Event().wait()
        session.data.update(is_watering=False, is_paused_sess=False)

    session.async_refresh = AsyncMock(side_effect=refresh)
    start = asyncio.create_task(session.async_start_watering(120))
    try:
        async with asyncio.timeout(2):
            await checking.wait()
            await session.async_safe_stop_watering()
        with pytest.raises(HomeAssistantError, match="interrupted by Stop"):
            await start
    finally:
        if not start.done():
            start.cancel()
            await asyncio.gather(start, return_exceptions=True)
    session.tap_api.turn_on.assert_awaited_once()
    session.tap_api.turn_off.assert_awaited_once()


@pytest.mark.parametrize(
    "hours,was_paused,expected",
    [
        (0, True, 0),
        (0.5, True, 0),
        (0.5, False, None),
        (1, False, 1),
        (1.9, False, 1),
        (240.9, False, 240),
    ],
)
async def test_cmd18_uses_released_whole_hour_coercion(
    session, hours, was_paused, expected
):
    session.async_refresh = refresh_sequence(
        session,
        [
            {"is_paused": was_paused},
            {"is_paused": bool(expected)},
        ],
    )
    await session.async_set_water_plan_pause(hours)
    if expected is None:
        session.tap_api.pause_tap.assert_not_awaited()
    else:
        session.tap_api.pause_tap.assert_awaited_once_with(
            MOCK_GW_ID, MOCK_TAP_ID, expected
        )
        assert type(session.tap_api.pause_tap.call_args.args[2]) is int
    session.tap_api.cmd19.assert_not_awaited()


@pytest.mark.parametrize("hours", [-1, 241, float("inf"), float("nan"), "0.5"])
async def test_invalid_plan_pause_is_not_dispatched(session, hours):
    with pytest.raises(HomeAssistantError, match="negative|0 to 240"):
        await session.async_set_water_plan_pause(hours)
    session.tap_api.pause_tap.assert_not_awaited()


async def test_cmd19_requires_explicit_unpaused_session(session):
    session.data.pop("is_paused_sess")
    session.async_refresh = AsyncMock()
    with pytest.raises(HomeAssistantError, match="valid session pause flag"):
        await session.async_pause_current_watering(0.1)
    session.tap_api.cmd19.assert_not_awaited()


async def test_cmd19_pause_waits_for_physical_stop(session):
    session.async_refresh = refresh_sequence(
        session,
        [
            {"is_watering": True, "remain_duration": 120},
            {"is_watering": True, "is_paused_sess": True},
            {"is_watering": False, "is_paused_sess": True},
        ],
    )
    with patch("custom_components.linktap.COMMAND_VERIFY_INTERVAL", 0):
        await session.async_pause_current_watering(0.1)
    assert session.async_refresh.await_count == 3


def test_pause_metadata_clears_on_confirmed_gateway_resume(session):
    session.current_pause_mode = 1
    session.current_pause_until = datetime.now(timezone.utc) + timedelta(minutes=5)
    session._validated_status({**MOCK_TAP_STATUS, "is_rf_linked": False})
    assert session.current_pause_mode == 1
    session.data = session._validated_status(MOCK_TAP_STATUS)
    assert session.current_pause_mode is None
    assert session.current_pause_until is None
    session.data = session._validated_status(
        {**MOCK_TAP_STATUS, "is_paused_sess": True}
    )
    entity = sensor.LinktapCurrentPauseRemainingSensor(session, tap_for(session))
    assert entity.native_value is None
    assert not entity.extra_state_attributes["expiry_known"]


@pytest.mark.parametrize("untrusted", ["rf", "failed", "rejected"])
def test_untrusted_runtime_states_are_unknown_but_plan_state_is_separate(
    session, untrusted
):
    tap = tap_for(session)
    session.data.update(is_paused=True, is_paused_sess=True, volume=100)
    if untrusted == "rf":
        session.data["is_rf_linked"] = False
    elif untrusted == "failed":
        session.last_update_success = False
    else:
        session._validated_status({**MOCK_TAP_STATUS, "volume": 999999})
    water = switch.LinktapSwitch(session, session.hass, tap)
    valve = LinktapValve(session, session.hass, tap)
    assert water.is_on is None
    assert valve.state == "unknown"
    assert valve.is_closed is None
    for field in ("is_watering", "is_paused_sess"):
        entity = binary_sensor.LinktapBinarySensor(
            session, session.hass, tap, data_attribute=field
        )
        assert entity.state == "unknown"
    plan = binary_sensor.LinktapBinarySensor(
        session, session.hass, tap, data_attribute="is_paused"
    )
    assert plan.state == "on"
    assert (
        sensor.LinktapSensor(session, session.hass, tap, "volume", "L").state
        == "unknown"
    )


def test_rf_loss_does_not_accumulate_stale_volume_or_unconfirmed_time(session):
    tap = tap_for(session)
    volume = sensor.LinktapVolumeTotalSensor(session, session.hass, tap, "L")
    duration = sensor.LinktapWateringTimeTotalSensor(session, session.hass, tap)
    volume.async_write_ha_state = MagicMock()
    duration.async_write_ha_state = MagicMock()
    start = datetime.now(timezone.utc)
    snapshots = [
        (0, True, True, 0),
        (10, True, True, 5),
        (20, False, True, 500),
        (60, True, True, 6),
        (65, True, False, 7),
    ]
    for offset, linked, watering, raw_volume in snapshots:
        session.data.update(
            is_rf_linked=linked, is_watering=watering, volume=raw_volume
        )
        with patch.object(
            sensor.dt_util, "utcnow", return_value=start + timedelta(seconds=offset)
        ):
            volume._handle_coordinator_update()
            duration._handle_coordinator_update()
            if not linked:
                assert volume.native_value == 5
                assert duration.native_value == 10
    assert volume.native_value == 7
    assert duration.native_value == 15


async def test_zero_seconds_valve_service_does_not_start_watering(session):
    valve = LinktapValve(session, session.hass, tap_for(session))
    with pytest.raises(HomeAssistantError, match="Watering duration"):
        await valve._start_watering(0)
    session.tap_api.turn_on.assert_not_awaited()


async def test_zero_helper_uses_default_bounded_by_configured_maximum(session):
    entity = switch.LinktapSwitch(
        session, session.hass, tap_for(session), max_watering_duration=5
    )
    session.async_start_watering = AsyncMock()
    session.async_request_refresh = AsyncMock()
    with patch.object(entity, "get_watering_duration", return_value=0):
        await entity.async_turn_on()
    session.async_start_watering.assert_awaited_once_with(300, 0)


@pytest.mark.parametrize(
    "module", [binary_sensor, button, number, select, sensor, switch]
)
async def test_legacy_hides_session_entities(session, module):
    session.tap_api.session_pause_supported = False
    config = SimpleNamespace(entry_id="test", options={})
    session.hass.data[DOMAIN] = {
        "test": {
            "conf": {
                "taps": [tap_for(session)],
                "vol_unit": "L",
            }
        }
    }
    add = MagicMock()
    with (
        patch.object(
            module.entity_platform,
            "async_get_current_platform",
            return_value=MagicMock(),
        )
        if hasattr(module, "entity_platform")
        else nullcontext()
    ):
        await module.async_setup_entry(session.hass, config, add)
    entities = add.call_args.args[0]
    assert all("current" not in entity.unique_id for entity in entities)
    assert all("pause_resume" not in entity.unique_id for entity in entities)
    assert all("is_paused_sess" not in entity.unique_id for entity in entities)
    if module is switch:
        assert any(isinstance(entity, switch.LinktapPauseSwitch) for entity in entities)
        assert len(entities) == 2


async def test_valve_services_use_shared_coordinator(session):
    valve = LinktapValve(session, session.hass, tap_for(session))
    session.async_pause_current_watering = AsyncMock()
    session.async_resume_current_watering = AsyncMock()
    await valve._pause_current_watering(0.1, "complete_duration")
    await valve._resume_current_watering()
    session.async_pause_current_watering.assert_awaited_once_with(0.1, 1)
    session.async_resume_current_watering.assert_awaited_once_with()
    with pytest.raises(HomeAssistantError, match="Unknown LinkTap pause mode"):
        await valve._pause_current_watering(0.1, "bad")


async def test_live_only_is_never_implicitly_changed():
    client = LinktapLocal()
    client._request = AsyncMock(return_value={"ret": 0})
    await client.turn_on(MOCK_GW_ID, MOCK_TAP_ID, 120, 5)
    assert "live_only" not in client._request.call_args.args[0]


async def test_diagnostics_expose_both_pause_flags_and_failure(session):
    config = SimpleNamespace(entry_id="test")
    session.hass.data[DOMAIN] = {"test": {"conf": {"taps": [tap_for(session)]}}}
    session.tap_api.turn_off.side_effect = TimeoutError(f"Connection to {MOCK_GW_IP}")
    with pytest.raises(HomeAssistantError, match="Connection to"):
        await session.async_safe_stop_watering()
    diagnostics = await async_get_config_entry_diagnostics(session.hass, config)
    assert diagnostics["taps"][0]["state"]["is_paused"] is False
    assert diagnostics["taps"][0]["state"]["is_paused_sess"] is False
    failure = diagnostics["taps"][0]["last_session_failure"]
    assert failure["error"] == "Stop result unknown"
    assert failure["error_type"] == "TimeoutError"
    assert MOCK_GW_IP not in str(diagnostics)


async def test_official_option_labels_and_selection(session):
    entity = select.LinktapPauseResumeBehaviourSelect(session, tap_for(session))
    entity.async_write_ha_state = MagicMock()
    assert entity.options == [
        "Keep Original End Time",
        "Complete Full Watering Duration",
    ]
    await entity.async_select_option("Complete Full Watering Duration")
    assert session.current_pause_selected_option == 1
    with pytest.raises(ValueError):
        await entity.async_select_option("Restart Full Watering Duration")


async def test_plan_pause_is_independent_of_session_pause(session):
    session.async_refresh = refresh_sequence(
        session,
        [
            {"is_paused": False, "is_paused_sess": True},
            {"is_paused": False, "is_paused_sess": True},
            {"is_paused": True, "is_paused_sess": True},
        ],
    )
    with patch("custom_components.linktap.COMMAND_VERIFY_INTERVAL", 0):
        await session.async_set_water_plan_pause(2)
    session.tap_api.pause_tap.assert_awaited_once_with(MOCK_GW_ID, MOCK_TAP_ID, 2)
    session.tap_api.cmd19.assert_not_awaited()


@pytest.mark.parametrize("ret", [9, 10, 13])
async def test_gateway_pause_rejections_capture_diagnostics(session, ret):
    session.async_refresh = AsyncMock()
    session.tap_api.cmd19.return_value = {"ret": ret}
    with pytest.raises(HomeAssistantError, match=f"ret={ret}"):
        await session.async_pause_current_watering(1)
    assert session.last_session_failure["state"]["remain_duration"] == 120


async def test_power_save_delay_exceeding_fifteen_seconds(session):
    """Exercise real reporting latency without shortening the production budget."""
    session.async_refresh = refresh_sequence(
        session,
        [
            *([{}] * 6),
            {
                "is_watering": True,
                "is_paused_sess": False,
            },
        ],
    )
    started = asyncio.get_running_loop().time()
    await session.async_start_watering(120)
    assert asyncio.get_running_loop().time() - started >= 15


async def test_stop_accepts_retained_runtime_context(session):
    """live_only=0 can retain totals; only RF/watering/session flags prove stop."""
    session.async_refresh = refresh_sequence(
        session,
        [
            {
                "is_paused": True,
                "is_paused_sess": False,
                "is_watering": False,
                "remain_duration": 111,
                "total_duration": 180,
                "volume": 3.5,
            }
        ],
    )
    await session.async_safe_stop_watering()
    assert session.data["remain_duration"] == 111
    assert session.data["total_duration"] == 180
    assert session.data["volume"] == 3.5
    assert session.plan_paused is True


async def test_start_and_stop_entities_use_coordinator(session):
    tap = tap_for(session)
    session.async_start_watering = AsyncMock()
    session.async_safe_stop_watering = AsyncMock()
    session.async_request_refresh = AsyncMock()
    main_switch = switch.LinktapSwitch(session, session.hass, tap)
    with (
        patch.object(main_switch, "get_watering_duration", return_value=2),
        patch.object(main_switch, "get_watering_volume", return_value=0),
    ):
        await main_switch.async_turn_on()
    session.async_start_watering.assert_awaited_once_with(120, 0)
    await main_switch.async_turn_off()
    valve = LinktapValve(session, session.hass, tap)
    await valve._start_watering(180)
    await valve.async_close_valve()
    await button.LinktapStopWateringButton(session, tap).async_press()
    assert session.async_safe_stop_watering.await_count == 3


async def test_stale_dev21_legacy_option_cannot_disable_cmd19(
    hass, mock_config_entry, mock_linktap_api
):
    """Ignore test-only saved options without rewriting the config entry."""
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.linktap import async_setup_entry

    mock_config_entry.add_to_hass(hass)
    mock_config_entry._async_set_state(hass, ConfigEntryState.SETUP_IN_PROGRESS, None)
    options = {"test_simulate_legacy_gateway": True}
    hass.config_entries.async_update_entry(mock_config_entry, options=options)
    mock_linktap_api.session_pause_supported = True
    with (
        patch("custom_components.linktap.LinktapLocal", return_value=mock_linktap_api),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
    ):
        await async_setup_entry(hass, mock_config_entry)
    assert mock_linktap_api.session_pause_supported
    assert dict(mock_config_entry.options) == options
