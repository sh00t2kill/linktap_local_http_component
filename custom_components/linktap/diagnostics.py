"""LinkTap gateway and watering diagnostics for Home Assistant."""

from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass, entry):
    """Export telemetry and command failure context without raw network errors."""
    taps = hass.data[DOMAIN][entry.entry_id]["conf"]["taps"]
    fields = (
        "is_rf_linked", "signal", "is_watering", "is_paused", "is_paused_sess",
        "remain_duration", "total_duration", "volume",
    )
    result = []
    for tap in taps:
        coordinator = tap["coordinator"]
        result.append({
            "gateway_version": coordinator.tap_api.gateway_version,
            "session_pause_supported": coordinator.supports_session_pause,
            "last_update_success": coordinator.last_update_success,
            "state": {key: (coordinator.data or {}).get(key) for key in fields},
            "last_session_failure": coordinator.last_session_failure,
        })
    return {"taps": result}
