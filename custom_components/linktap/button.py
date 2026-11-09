"""LinkTap action buttons."""
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN, GW_IP, MANUFACTURER, NAME, TAP_ID


async def async_setup_entry(hass, config, async_add_entities, discovery_info=None):
    """Set up LinkTap buttons."""
    entities = []
    for tap in hass.data[DOMAIN][config.entry_id]["conf"]["taps"]:
        coordinator = tap["coordinator"]
        if getattr(coordinator.tap_api, "session_pause_supported", False) is True:
            entities.append(LinktapStopWateringButton(coordinator, tap))
    async_add_entities(entities, True)


class LinktapStopWateringButton(CoordinatorEntity, ButtonEntity):
    """Explicitly terminate an active or CMD19-paused watering session."""

    _attr_has_entity_name = True
    _attr_name = "Stop Watering"
    _attr_icon = "mdi:stop-circle-outline"

    def __init__(self, coordinator, tap):
        super().__init__(coordinator)
        self.tap_id = tap[TAP_ID]
        self._attr_unique_id = slugify(
            f"{DOMAIN}_button_{self.tap_id}_stop_watering"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tap[TAP_ID])},
            name=tap[NAME],
            manufacturer=MANUFACTURER,
            model=tap[TAP_ID],
            configuration_url="http://" + tap[GW_IP] + "/",
        )

    async def async_press(self):
        # Revised CMD7 clears a paused session directly; poll CMD3 afterwards.
        await self.coordinator.async_safe_stop_watering()
        await self.coordinator.async_request_refresh()
