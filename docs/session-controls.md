# Pause, resume and stop a LinkTap watering session

**Pause Current Watering** suspends one active session through the gateway's local API (CMD19). **Pause Water Plan** suspends the LinkTap server schedule (CMD18). LinkTap can report both states independently. Use **Current Session Paused** for a suspended session and **Is Paused** for the schedule.

## Firmware requirements

Use LinkTap firmware with CMD19 and revised CMD7 support. At setup, the integration reads the gateway configuration (CMD16) and enables the session controls when the six-digit family after the leading letter is `060951` or newer, such as `S060951…` or `S060952…`. It does not compare the trailing build suffix or send a test watering command. Some pre-release builds may share the same family number. If the controls appear but the command is rejected, check the complete firmware version with LinkTap. Older or unrecognized firmware keeps the existing watering and plan controls.

After a gateway firmware update, reload the LinkTap integration to refresh capability detection. The two session actions may appear in Home Assistant even when a particular valve's gateway does not support them. Choose a valve on a compatible gateway.

## Pause, resume or stop from a device page

Open your LinkTap output in **Settings → Devices & services → Devices**.

1. While watering is active, set **Pause Duration** and choose **Resume Behaviour**.
2. Turn on **Pause Current Watering**. Home Assistant checks that the device has a confirmed RF link, is watering, and has more than 15 seconds remaining before sending CMD19.
3. Turn **Pause Current Watering** off to resume manually, or let the gateway resume automatically when the pause expires. The timer runs on the gateway, so no Home Assistant automation or scheduled action is required. A cleared pause confirms the session is no longer paused. Check **Is Watering** separately for actual valve activity.
4. To end the session, press **Stop Watering**. It sends CMD7 directly, including while the session is paused. You can also call `valve.close_valve` or `switch.turn_off` on the main watering switch. The main control may already show closed or off during a pause, so use the button or an explicit action in that case.

Stop leaves the watering plan in place. A future scheduled run can still start. LinkTap documents that changing the plan or reaching a scheduled start can also discard a paused session. The session pause is managed locally by the gateway and does not synchronize with the LinkTap server or app.

## Resume behaviours

Choose a behaviour before pausing. It determines how the gateway treats paused time for both manual and automatic resume.

| Behaviour                           | Effect                                                                                                                                                                    |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Keep Original End Time**          | Paused time counts toward the original run window. In a 20-minute time-based run, pausing after 5 minutes for 6 minutes leaves about 9 minutes of watering after resume.  |
| **Complete Full Watering Duration** | Paused time does not count toward the watering duration. In the same run, about 15 minutes of watering remain after resume. The pause extends the wall-clock finish time. |

These examples assume timely reports and no other applicable cutoff. Changing the selector during a pause sets the preference for the next switch-initiated pause. It does not update a pause already accepted by the gateway.

## Session entities

| Entity                                       | Function                                                                                                                                                                                                                                                                                                           |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Pause Current Watering** (`switch`)        | Turn on to pause using the helper and selected behaviour. Turn off to resume. The switch follows the confirmed session pause state.                                                                                                                                                                                |
| **Current Session Paused** (`binary_sensor`) | Read-only confirmed CMD19 session state from `is_paused_sess`. Use this to distinguish a paused session from an idle valve.                                                                                                                                                                                        |
| **Pause Duration** (`number`)                | Duration for switch-initiated pauses in minutes, from 1 to 60 in 1-minute steps. Defaults to 10 minutes and restores its last saved value.                                                                                                                                                                         |
| **Resume Behaviour** (`select`)              | Preference for future switch-initiated pauses. Defaults to **Keep Original End Time** after setup or reload.                                                                                                                                                                                                       |
| **Pause Remaining** (`sensor`)               | Estimated seconds to expiry for a pause started and confirmed by this Home Assistant instance. The estimate updates with status polls. It can be `unknown` when a pause was started elsewhere, Home Assistant reloaded, or the device state is unconfirmed. It is zero when the gateway confirms no session pause. |
| **Stop Watering** (`button`)                 | End the active or paused session. The integration checks that the RF-linked device is idle and the session pause has cleared.                                                                                                                                                                                      |

**Pause Water Plan**, **Pause Duration Water Plan**, **Is Paused**, the main switch and valve, and the instant-watering helpers retain their existing roles. Legacy firmware continues to support the main switch and valve for Stop.

## Home Assistant action examples

Run these examples individually in **Developer tools → Actions** in YAML mode, or use them as actions in a script. Replace the example entity IDs with the IDs shown in your Home Assistant entity registry. Actual IDs depend on your installation and any renames.

Pause a running session for six minutes and complete the full watering duration after resume. The action takes `hours` from `0.01` to `240`, independent of the minute helper. Use `keep_end_time` for the other behaviour. Specify both fields so the desired action is explicit.

```yaml
action: linktap.pause_current_watering
target:
  entity_id: valve.garden_tap
data:
  hours: 0.1
  mode: complete_duration
```

Resume the paused session early. If a fresh status confirms that the session is already unpaused, this action does nothing.

```yaml
action: linktap.resume_current_watering
target:
  entity_id: valve.garden_tap
```

Set the dashboard pause controls and then turn on the session-pause switch. Use the following as a script sequence while the device is actively watering.

```yaml
sequence:
  - action: number.set_value
    target:
      entity_id: number.garden_tap_pause_duration
    data:
      value: 5
  - action: select.select_option
    target:
      entity_id: select.garden_tap_resume_behaviour
    data:
      option: Keep Original End Time
  - action: switch.turn_on
    target:
      entity_id: switch.garden_tap_pause_current_watering
```

End a session, including a paused one, using the dedicated button.

```yaml
action: button.press
target:
  entity_id: button.garden_tap_stop_watering
```

For instant watering and plan-pause actions, see the [README](../README.md#entity-services).

## Troubleshooting

- **The session controls are missing.** Check the firmware and reload the integration after an update. If a gateway reports an older or unrecognized firmware format, its current-session entities are not created. The original plan and watering entities still apply.
- **Pause is rejected.** Confirm the device is watering, **Is Linked** is on, and more than 15 seconds remain. A positive pause request is also refused if a session is already paused or Home Assistant cannot verify the required state. The gateway can still reject a request if the session changes before it receives the command.
- **A command was accepted but could not be verified.** An acknowledgement only means the gateway accepted the request. LinkTap documents that device reports can take more than 5 seconds in Performance mode and more than 15 seconds in Power save mode. The integration checks for confirmation for up to 30 seconds after acknowledgement and does not automatically resend the write. Check the reported RF link and valve state before sending another command. If Stop cannot be confirmed and continued watering would cause damage, check the valve locally and shut off the water supply if necessary.
- **State is unknown or unavailable.** A reachable gateway can still lose the RF link to a tap. Treat `unknown` watering, pause or flow data as unconfirmed. A failed Home Assistant poll can instead make entities `unavailable`. Check **Is Linked**, **Signal**, the gateway network connection and the device battery. [Retained telemetry](../README.md#retained-session-telemetry-and-live_only) may still describe a completed run, even with a good RF link.
- **Pause Remaining is unknown, or the session did not resume as expected.** An unknown estimate does not cancel the gateway timer. Check **Current Session Paused** and **Is Watering** separately. A stop, a plan change, or a scheduled start can discard the paused run. If an expected automatic resume is missing, record both states, RF link, signal, and the approximate pause and expiry times.

To report an issue, use **Download diagnostics** from the LinkTap integration entry menu and include the complete gateway firmware, device model, action and approximate time. Diagnostics include gateway capability, the latest accepted status fields and a snapshot for the last captured command failure. Review diagnostics and logs before sharing. Logs can include network details.
