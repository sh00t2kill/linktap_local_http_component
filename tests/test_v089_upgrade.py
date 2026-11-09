"""Load a v0.8.9 registry and restore cache into the current integration."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.components.number import NumberExtraStoredData
from homeassistant.components.sensor import SensorExtraStoredData
from homeassistant.core import State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import (
    mock_restore_cache_with_extra_data,
)

from custom_components.linktap.const import DOMAIN
from tests.conftest import MOCK_TAP_ID


# Registry contract from ef757ec (v0.8.9). Freeze the released keys independently
# of current entity constructors, so shallow CI checkouts need no older objects.
def released_registry_keys(tap):
    return {
        "switch": [f"linktap_switch_{tap}", f"linktap_switch_{tap}_pause"],
        "valve": [f"linktap_valve_{tap}"],
        "number": [
            f"linktap_number_{tap}_{key}"
            for key in (
                "watering_duration",
                "watering_volume",
                "pause_duration",
            )
        ],
        "binary_sensor": [
            f"linktap_binary_sensor_{key}_{tap}"
            for key in (
                "is_rf_linked",
                "is_fall",
                "is_cutoff",
                "is_leak",
                "is_clog",
                "is_broken",
                "is_manual_mode",
                "is_watering",
                "is_paused",
            )
        ],
        "sensor": [
            f"linktap_sensor_{key}_{tap}"
            for key in (
                "signal",
                "battery",
                "total_duration",
                "remain_duration",
                "speed",
                "volume",
                "volume_limit",
                "failsafe_duration",
                "plan_mode",
                "plan_sn",
                "plan_mode_string",
                "volume_total",
                "watering_time_total",
            )
        ],
    }


@pytest.mark.parametrize(
    "revised_firmware,outage_restore", [(False, False), (True, False), (True, True)]
)
async def test_upgrade_preserves_released_registry_and_restored_values(
    hass,
    enable_custom_integrations,
    mock_config_entry,
    mock_linktap_api,
    revised_firmware,
    outage_restore,
):
    entry = mock_config_entry
    entry.add_to_hass(hass)
    tap = MOCK_TAP_ID
    options = {
        "watering_safety_limits": {
            tap: {"max_watering_duration": 10, "max_watering_volume": 60}
        }
    }
    hass.config_entries.async_update_entry(entry, options=options)
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, tap)},
        name="Garden Tap",
    )
    devices.async_update_device(device.id, name_by_user="G2S01")
    registry = er.async_get(hass)
    names = {
        f"linktap_switch_{tap}_pause": "linktap_g2s01_pause",
        f"linktap_binary_sensor_is_paused_{tap}": "linktap_g2s01_is_paused",
        f"linktap_number_{tap}_watering_duration": "custom_watering_duration",
    }
    entities = {}
    for domain, keys in released_registry_keys(tap).items():
        for key in keys:
            registered = registry.async_get_or_create(
                domain,
                DOMAIN,
                key,
                config_entry=entry,
                device_id=device.id,
                suggested_object_id=names.get(key, key),
            )
            entities[key] = registered.entity_id

    duration_id = entities[f"linktap_number_{tap}_watering_duration"]
    volume_id = entities[f"linktap_number_{tap}_watering_volume"]
    total_id = entities[f"linktap_sensor_volume_total_{tap}"]
    time_id = entities[f"linktap_sensor_watering_time_total_{tap}"]
    totals = [(State(total_id, "125.0"), {}), (State(time_id, "90.0"), {})]
    if outage_restore:
        totals = [
            (State(total_id, "unavailable"), SensorExtraStoredData(125, "L").as_dict()),
            (State(time_id, "unavailable"), SensorExtraStoredData(90, "s").as_dict()),
        ]
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(duration_id, "0"),
                NumberExtraStoredData(10, 0, 5, "m", 0).as_dict(),
            ),
            (
                State(volume_id, "40"),
                NumberExtraStoredData(60, 0, 10, "L", 40).as_dict(),
            ),
            *totals,
        ],
    )
    status = mock_linktap_api.fetch_data.return_value
    status.update(volume=45, volume_limit=5)
    if not revised_firmware:
        status.pop("is_paused_sess")
    mock_linktap_api.session_pause_supported = revised_firmware

    with patch("custom_components.linktap.LinktapLocal", return_value=mock_linktap_api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    for key, entity_id in entities.items():
        registered = registry.async_get(entity_id)
        assert registered.unique_id == key
        assert registered.device_id == device.id
        assert hass.states.get(entity_id) is not None
    assert devices.async_get(device.id).name_by_user == "G2S01"
    assert set(entry.options) == set(options)
    assert dict(entry.options) == options
    assert float(hass.states.get(duration_id).state) == 0
    assert float(hass.states.get(volume_id).state) == 40
    for entity_id, label, maximum, step in (
        (duration_id, "Watering duration", 10, 5),
        (volume_id, "Watering volume", 60, 10),
    ):
        assert registry.async_get(entity_id).original_name == label
        assert hass.states.get(entity_id).attributes["min"] == 0
        assert hass.states.get(entity_id).attributes["max"] == maximum
        assert hass.states.get(entity_id).attributes["step"] == step
    assert hass.states.get("switch.linktap_g2s01_pause").state == "off"
    assert hass.states.get("binary_sensor.linktap_g2s01_is_paused").state == "off"

    for service in (
        "pause",
        "pause_valve",
        "start_watering",
        "dismiss_alert",
        "dismiss_alerts",
    ):
        assert hass.services.has_service(DOMAIN, service)

    async def pause_plan(gateway, device, hours):
        status["is_paused"] = bool(hours)
        return True

    mock_linktap_api.pause_tap.side_effect = pause_plan
    for service, entity_id, hours, expected in (
        ("pause", "switch.linktap_g2s01_pause", 1.9, 1),
        ("pause_valve", entities[f"linktap_valve_{tap}"], 0.9, 0),
    ):
        await hass.services.async_call(
            DOMAIN, service, {"entity_id": entity_id, "hours": hours}, blocking=True
        )
        assert type(mock_linktap_api.pause_tap.call_args.args[2]) is int
        assert mock_linktap_api.pause_tap.call_args.args[2] == expected
    mock_linktap_api.cmd19.assert_not_awaited()

    registered = er.async_entries_for_config_entry(registry, entry.entry_id)
    extras = {
        item.unique_id: item.original_name
        for item in registered
        if item.unique_id not in entities
    }
    dev21_session_entities = {
        f"linktap_binary_sensor_is_paused_sess_{tap}": "Current Session Paused",
        f"linktap_button_{tap}_stop_watering": "Stop Watering",
        f"linktap_number_{tap}_current_watering_pause_duration": "Pause Duration",
        f"linktap_select_{tap}_pause_resume_behaviour": "Resume Behaviour",
        f"linktap_sensor_current_pause_remaining_{tap}": "Pause Remaining",
        f"linktap_switch_{tap}_pause_current_watering": "Pause Current Watering",
    }
    assert extras == (dev21_session_entities if revised_firmware else {})
    if revised_firmware:
        for item in registered:
            if item.unique_id in dev21_session_entities:
                assert item.device_id == device.id
                assert hass.states.get(item.entity_id) is not None
        select_id = registry.async_get_entity_id(
            "select", DOMAIN, f"linktap_select_{tap}_pause_resume_behaviour"
        )
        assert hass.states.get(select_id).state == "Keep Original End Time"
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": select_id, "option": "Complete Full Watering Duration"},
            blocking=True,
        )
        assert hass.states.get(select_id).state == "Complete Full Watering Duration"

    coordinator = hass.data[DOMAIN][entry.entry_id]["conf"]["taps"][0]["coordinator"]
    assert float(hass.states.get(total_id).state) == 125
    assert float(hass.states.get(time_id).state) == 90
    status.update(is_rf_linked=False, volume=500)
    await coordinator.async_refresh()
    assert float(hass.states.get(total_id).state) == 125
    assert hass.states.get(entities[f"linktap_sensor_volume_{tap}"]).state == "unknown"
    mock_linktap_api.fetch_data.side_effect = UpdateFailed("mock poll outage")
    await coordinator.async_refresh()
    assert hass.states.get(total_id).state == "unavailable"
    assert hass.states.get(time_id).state == "unavailable"
    mock_linktap_api.fetch_data.side_effect = None
    status.update(is_rf_linked=True, volume=47)
    await coordinator.async_refresh()
    assert float(hass.states.get(total_id).state) == 127
    assert float(hass.states.get(time_id).state) == 90
    assert await hass.config_entries.async_unload(entry.entry_id)
