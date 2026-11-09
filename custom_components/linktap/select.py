from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN, GW_IP, MANUFACTURER, NAME, TAP_ID

OPTIONS = ["Keep Original End Time", "Complete Full Watering Duration"]

async def async_setup_entry(hass, config, async_add_entities, discovery_info=None):
    entities = []
    for tap in hass.data[DOMAIN][config.entry_id]["conf"]["taps"]:
        coordinator = tap["coordinator"]
        if getattr(coordinator.tap_api, "session_pause_supported", False) is True:
            entities.append(LinktapPauseResumeBehaviourSelect(coordinator, tap))
    async_add_entities(entities, True)

class LinktapPauseResumeBehaviourSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Resume Behaviour"
    _attr_icon = "mdi:restart"
    _attr_options = OPTIONS

    def __init__(self, coordinator, tap):
        super().__init__(coordinator)
        self.tap_id = tap[TAP_ID]
        self._attr_unique_id = slugify(f"{DOMAIN}_select_{self.tap_id}_pause_resume_behaviour")
        self._attr_current_option = OPTIONS[0]
        coordinator.current_pause_selected_option = 0
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, tap[TAP_ID])}, name=tap[NAME], manufacturer=MANUFACTURER, model=tap[TAP_ID], configuration_url="http://" + tap[GW_IP] + "/")

    async def async_select_option(self, option):
        if option not in OPTIONS:
            raise ValueError(option)
        self._attr_current_option = option
        self.coordinator.current_pause_selected_option = OPTIONS.index(option)
        self.async_write_ha_state()
