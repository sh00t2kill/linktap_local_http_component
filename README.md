# LinkTap Local HTTP API for Home Assistant

A custom Home Assistant integration for LinkTap TapLinkers and ValveLinkers using the LinkTap gateway's **local HTTP API**.

The integration provides local control and monitoring of LinkTap devices, including **Instant Watering**, water and flow sensors, cumulative totals, watering-plan pause, alerts, and optional Home Assistant watering limits. Compatible gateway firmware also adds [current-session pause, resume and stop controls](docs/session-controls.md).

> [!IMPORTANT]
> The LinkTap gateway's **Local HTTP API must be enabled** and the gateway must be reachable directly from Home Assistant on the local network.

## Installation

Install the integration through **HACS** and restart Home Assistant if required.

Then add it from:

**Settings → Devices & services → Add integration → Local HTTP API for LinkTap**

Enter the **IPv4 address of the LinkTap gateway**, for example:

```text
192.168.1.123
```

Do not enter a URL, port, path, hostname or IPv6 address, for example:

```text
http://192.168.1.123
192.168.1.123:80
192.168.1.123/api.shtml
gateway-hostname.local
```

Since v0.8.4, the config flow now validates and normalises the gateway IPv4 address before saving it.

If you have more than one LinkTap gateway, add the integration once for each gateway.

## What the integration creates

A Home Assistant **device** is created for each LinkTap output discovered through the gateway.

For multi-valve TapLinkers or ValveLinkers, a separate Home Assistant device is created for each output.

The integration creates:

- a main **switch** for watering;
- a matching **valve** entity;
- a **Pause Water Plan** switch;
- watering duration, watering volume and pause-duration **number** entities;
- status and alert **binary sensors**;
- water, flow, duration, plan and diagnostic **sensors**.

The main switch and valve both control instant watering. The [session control guide](docs/session-controls.md#session-entities) lists the six additional entities created for each output on compatible firmware. Upgrading preserves existing entity IDs, unique IDs and settings. Keep the existing integration entry when upgrading.

## Instant Watering

For normal Home Assistant instant watering:

1. Set **Watering duration**.
2. Optionally set **Watering volume**.
3. Turn on the main LinkTap switch or open the LinkTap valve.

The integration sends a duration and, when set, a volume target to the gateway. On a device with a connected, supported flow meter, watering stops at the first applicable limit.

### Watering Duration

- Unit: **minutes**
- Default: **15 minutes**
- Native integration range: **0–120 minutes**
- Step: **5 minutes**

`0` selects the 15-minute default, capped by any configured maximum duration.

### Watering Volume

- Unit: the volume unit configured on the LinkTap gateway, normally **L** or **Gal**
- Default: **0**
- Native integration range: **0–2000**
- Step: **10**

A Watering Volume value of `0` means **no volume cutoff**. In that case watering is controlled by duration only.

> [!NOTE]
> These Home Assistant duration/volume helpers are used for watering started through the integration's normal switch/valve control path. Watering started from the LinkTap app, the physical device button, MQTT, or another external mechanism is controlled by LinkTap itself and does not use these Home Assistant helper values.

### Retained session telemetry and `live_only`

After a session ends, the gateway normally retains the last reported `volume`, `total_duration` and `remain_duration`. Those values can describe a completed session even when the valve is idle. Home Assistant displays **Remain Duration** as zero when idle is confirmed.

The gateway API has an optional CMD6 field, `live_only`, that clears these three fields when a session fully ends. A CMD19 pause preserves them. Setting `live_only` to `1` persists across subsequent watering tasks, including those started by the physical button or a watering plan, until a client explicitly resets it to `0` or the gateway restarts. The integration omits this field and has no control for changing it.

## Optional instant-watering safety limits

Since **v0.8.3**, optional per-device Home Assistant safety ceilings can be configured for instant watering.

Open:

**Settings → Devices & services → LinkTap → Configure**

For each LinkTap device you may independently set:

- **Maximum watering duration:** 5–120 minutes
- **Maximum watering volume:** 10–2000 in the gateway's configured volume unit

Either limit may be left unset.

These are **Home Assistant-side safety controls only**. They do not modify the LinkTap gateway, firmware, watering plans or native LinkTap limits.

When configured, the selected maximum:

- reduces the maximum allowed value of the corresponding Home Assistant number entity;
- clamps a restored/default helper value into the permitted range;
- is enforced again immediately before the normal switch watering command is sent;
- is exposed as a state attribute for diagnostic visibility.

`0` retains its existing special meaning for Watering Volume: **no volume cutoff**.

> [!CAUTION]
> `linktap.start_watering` accepts its own duration in seconds. The helper values and their safety ceilings apply to the normal switch and valve controls only.

## Water-plan pause controls

**Pause Water Plan** uses CMD18 to pause the existing LinkTap server schedule. The gateway must be connected to the LinkTap server. LinkTap documents that a successful plan pause ends any watering in progress early. Resuming the plan restores the schedule. Use [Pause Current Watering](docs/session-controls.md) to suspend and later resume an individual session on compatible firmware.

The relevant entities are:

- **Pause Water Plan**
- **Pause Duration Water Plan**

### Pause Duration Water Plan

- Unit: **hours**
- Default: **24 hours**
- Range: **1–240 hours**
- Step: **1 hour**

Turning **Pause Water Plan** on pauses the LinkTap watering plan for the configured number of hours.

Turning it off resumes a paused plan. **Is Paused** continues to report the plan state (`is_paused`).

### Repeated-pause protection

Since **v0.8.2**, the integration protects against a LinkTap local-API behaviour where sending another positive pause request while a plan is already paused can deactivate the underlying watering plan even though the gateway reports a successful response.

Before sending a positive pause request, the integration refreshes gateway state and rejects another positive pause when `is_paused` is already true. Unpause while already unpaused is treated as an idempotent no-op.

Because no documented safe LinkTap local-API operation is currently known for replacing or extending an already-active pause, the integration deliberately **does not change the expiry time of an existing pause**.

If you need a different pause duration, unpause first and then apply a new pause.

## Entity naming and renaming

Since **v0.8.0**, internal relationships between LinkTap entities are resolved through Home Assistant's **Entity Registry and stable unique IDs**, rather than by reconstructing entity IDs from the LinkTap device name.

This fixes a long-standing failure mode where newer Home Assistant entity-ID formats, recreated entities, area/device naming, or user-renamed entity IDs could cause the integration to miss the Watering Duration/Volume helper and silently fall back to the default duration.

You may now rename LinkTap entity IDs in Home Assistant without breaking the integration's internal relationships.

Existing entity IDs and unique IDs were intentionally preserved during this change, so upgrading does not force an entity migration.

Example IDs for an output named Garden Tap may look like:

```text
switch.garden_tap
valve.garden_tap
switch.garden_tap_pause_water_plan
number.garden_tap_watering_duration
number.garden_tap_watering_volume
number.garden_tap_pause_duration_water_plan
sensor.garden_tap_battery
sensor.garden_tap_signal
```

These are examples only; Home Assistant controls generated entity IDs.

## Binary sensors

| Binary sensor | Description |
|---|---|
| **Is Linked** | Whether the TapLinker is linked to the gateway |
| **Has a Fall Alert** | Fall alert reported by the device |
| **Has a Cutoff Alert** | Water-cutoff / failed-shutoff alert |
| **Is Leaking** | Leak condition reported by the device |
| **Is Clogged** | Clogged condition reported by the device |
| **Is Broken** | Other broken/fault condition reported by the device |
| **Is Manual Mode** | Device has been triggered manually (if device supports this)|
| **Is Paused** | LinkTap reports the water plan as paused |
| **Is Watering** | Device is currently watering |

Since v0.8.0, the fault-oriented entities — fall, cutoff, leaking, clogged and broken — are categorised as Home Assistant **diagnostic** entities. Operational states remain normal device entities.

## Sensors

| Sensor | Description |
|---|---|
| **Signal** | Signal strength between the LinkTap device and gateway |
| **Battery** | Device battery level |
| **Total Duration** | Current LinkTap watering-job duration, reported in seconds |
| **Remain Duration** | Remaining duration for the current watering job, in seconds |
| **Watering Time Total** | Home Assistant-maintained cumulative watering time |
| **Speed** | Current water flow rate |
| **Volume** | Water volume reported for the current watering session |
| **Volume Limit** | Current LinkTap volume limit |
| **Volume Total** | Home Assistant-maintained cumulative water volume |
| **Failsafe Duration** | LinkTap failsafe duration reported by the gateway, in seconds; currently read-only |
| **Plan Mode** | Numeric LinkTap watering-plan mode |
| **Plan Mode String** | Human-readable translation of the plan mode |
| **Plan SN** | LinkTap watering-plan serial number |

### Remain Duration

Since v0.8.0, **Remain Duration** is normalised to `0` when watering has stopped.

The integration reports the gateway value while watering or while the current session is paused, and `0` when idle is confirmed. If the RF link is lost or the runtime state cannot be confirmed, the value can be `unknown`. Plan pause alone does not indicate a paused session.

## Water flow and Home Assistant statistics

Since **v0.8.0**, the **Speed** sensor exposes Home Assistant's proper `volume_flow_rate` device class and `measurement` state class, using canonical units:

- `L/min`
- `gal/min`

This now allows the sensor to participate correctly in Home Assistant statistics and compatible water/energy dashboard features.

## Volume and watering totals

### Volume

`Volume` is the LinkTap gateway's raw/current-session water-volume value and is expected to reset when a new watering session begins.

### Volume Total

`Volume Total` is maintained by this Home Assistant integration because the local API does not provide the same cumulative total directly.

It is:

- persistent across Home Assistant restarts;
- `state_class: total_increasing`;
- suitable for Home Assistant long-term statistics;
- suitable for `utility_meter` helpers;
- suitable as a cumulative water source where Home Assistant accepts a water `total_increasing` sensor.

The integration compensates for the gateway retaining the previous session's raw `volume` after watering finishes so that a Home Assistant restart does not count the same completed session again.

### Protection against corrupt raw volume readings

Since **v0.8.1**, `Volume Total` includes defensive protection against persistent corruption from grossly implausible raw volume samples.

Before a raw sample can affect the persistent accumulator, the integration rejects:

- non-numeric values;
- non-finite values such as `NaN` or infinity;
- negative values;
- grossly implausible session-volume values.

During active or session-paused watering, the integration also checks the reported volume against a non-zero `volume_limit`, with tolerance. When idle, the reported volume may belong to the previous session, so the integration uses the absolute plausibility bound.

Rejected values are **dropped rather than clamped**, so they do not replace the last known-good accumulator sample. A warning is logged when a sample is rejected.

This is a defensive Home Assistant safeguard. It does **not** claim to fix the underlying LinkTap telemetry source if the gateway/firmware/API itself emits a bad value.

### Watering Time Total

`Watering Time Total` is maintained by Home Assistant, persists across restarts, reports cumulative watering time in seconds and uses `state_class: total_increasing`. Totals use confirmed samples and may miss activity during an outage. A failed poll can make the totals unavailable until communication recovers.

## Number entities

| Number entity | Default | Range | Unit | Purpose |
|---|---:|---:|---|---|
| **Watering duration** | 15 | 0-120 | min | Requested instant-watering duration |
| **Watering volume** | 0 | 0-2000 | L or Gal | Optional volume cutoff; `0` disables it |
| **Pause Duration Water Plan** | 24 | 1–240 | h | Duration used when pausing the water plan |

Optional per-device safety limits reduce the effective maximum of Watering Duration and/or Watering Volume.

## Switch and valve

Each LinkTap output has both a main **switch** and a **valve** entity.

For normal operation:

- switch on / valve open → start instant watering using the configured Home Assistant duration/volume values;
- switch off / valve close → stop watering.

The valve resolves its backing switch by stable unique ID when opening, so user-renamed entity IDs are supported. Switch off and valve close send CMD7 directly. On compatible firmware, Stop also clears a paused current session. See [pause, resume and stop](docs/session-controls.md#pause-resume-or-stop-from-a-device-page) for how to stop a paused session.

## Entity services

### `linktap.pause`

Pause or unpause a LinkTap watering plan through a LinkTap switch entity.

| Field | Required | Description |
|---|---|---|
| `entity_id` | yes | LinkTap switch entity |
| `hours` | no | Pause duration in hours; default `1`; `0` unpauses |

### `linktap.pause_valve`

Pause or unpause through a LinkTap valve entity.

| Field | Required | Description |
|---|---|---|
| `entity_id` | yes | LinkTap valve entity |
| `hours` | no | Pause duration in hours; default `1`; `0` unpauses |

Both plan actions use whole hours from `0` to `240`. Numeric fractions truncate toward zero, so `1.9` means `1` hour and `0.9` means resume. For example, in **Developer tools → Actions**, target the valve to suspend its plan for 12 hours:

```yaml
action: linktap.pause_valve
target:
  entity_id: valve.garden_tap
data:
  hours: 12
```

Replace `valve.garden_tap` with the valve ID from your own entity registry. Use `hours: 0` to resume the plan.

### `linktap.start_watering`

Start watering through a LinkTap valve entity for an explicit duration in seconds.

| Field | Required | Description |
|---|---|---|
| `entity_id` | yes | LinkTap valve entity |
| `seconds` | no | Whole seconds from `3` to `86340`; default `9000` when omitted |

Supply an explicit duration. The LinkTap API specifies a 60-second minimum for G1 and G2 hardware. A duration of `0` is rejected. To use the duration and volume helpers, set them and call `switch.turn_on` on the main switch or `valve.open_valve` on the valve.

### Alert dismissal

`linktap.dismiss_alert` and `linktap.dismiss_alerts` target LinkTap binary sensors to dismiss one alert or all applicable alerts. See the [session control actions](docs/session-controls.md#home-assistant-action-examples) for `linktap.pause_current_watering` and `linktap.resume_current_watering`.

## Watering plans and scheduling

The integration can report LinkTap plan information and can **pause/unpause the existing water plan**, but it does not currently provide Home Assistant controls for creating or editing LinkTap watering schedules.

Use the LinkTap app/web interface to manage schedules.

## Multiple gateways

Multiple LinkTap gateways are supported.

Each gateway must:

- have the Local HTTP API enabled;
- be reachable directly by Home Assistant;
- be added as a separate integration config entry using its IPv4 address.

## Device naming changes from LinkTap

When a TapLinker or ValveLinker is newly added or renamed in LinkTap, there can be a delay before the new name appears in the gateway's local API.

If Home Assistant initially discovers a generic name such as `TapLinker`, it waits for the gateway to update and then reload the integration.

Current versions resolve internal relationships by stable unique ID, so renaming Home Assistant entity IDs no longer breaks watering controls.

## G1 devices and flow measurement

If Volume or Speed always remains zero, check the LinkTap hardware model.

Older **G1** devices do not have the integrated flow-meter capability available on models such as the G2S. The integration cannot provide flow or volume data that the hardware does not measure/report.

## Failsafe Duration

The integration currently exposes LinkTap's reported **Failsafe Duration** as a read-only sensor.

This is distinct from the optional Home Assistant instant-watering safety ceilings. The current integration does **not** provide a control for changing `failsafe_duration`.

## Troubleshooting

### Watering always uses 15 minutes

Current releases resolve Watering Duration through the Entity Registry using its stable unique ID rather than guessing an entity ID.

If a current release still falls back to 15 minutes:

1. confirm the Watering Duration number entity exists and is available;
2. check whether it is temporarily `unknown` or `unavailable`;
3. reload the LinkTap integration;
4. check Home Assistant logs;
5. open an issue with the integration version, Home Assistant version and relevant diagnostics.

Temporary invalid helper states are handled safely and cause the normal fallback rather than a numeric-conversion error.

### Gateway address rejected during setup

Enter only the gateway's IPv4 address, for example:

```text
192.168.1.123
```

Do not include a URL scheme, hostname, port or API path.

### Volume Total looks incorrect

Compare:

- the raw LinkTap `Volume` for the completed session;
- the increase in `Volume Total`;
- the LinkTap app/cloud value separately.

`Volume Total` accumulates the volume reported by the **local API**. The LinkTap app/cloud may present a different value, beyond the scope of this integration.

Current releases also contain restart double-count protection and protection against grossly implausible raw-volume spikes.

### Repeated pause is rejected

This is intentional. A second positive LinkTap water-plan pause request has been observed to deactivate the underlying watering plan despite a successful gateway response, so the integration blocks it.

### Gateway replies are malformed or controls are unavailable

An unexpected gateway response means Home Assistant received a reply it could not use. Check that the gateway address is correct and the Local HTTP API is enabled. Review the setup error before reloading the integration. For missing session controls, RF loss or an unverified watering action, see [session troubleshooting](docs/session-controls.md#troubleshooting).

## Recent changes

### v0.8.4

- Validate and normalise the LinkTap gateway IPv4 address during config flow.
- Reject URLs, ports, paths, hostnames and IPv6 with a user-friendly error.

### v0.8.3

- Add optional per-device Home Assistant instant-watering safety ceilings.
- Independently configure maximum duration and/or maximum volume.
- Apply limits to the Home Assistant number controls and enforce them again at the normal switch command boundary.

### v0.8.2

- Protect against destructive repeated water-plan pause requests.
- Refresh state before mutation and verify the resulting state.
- Treat unpause while already unpaused as a no-op.

### v0.8.1

- Protect persistent `Volume Total` from grossly implausible raw-volume spikes.
- Reject invalid/non-finite/negative samples before they can affect the accumulator.
- Preserve restart double-count protection.

### v0.8.0

- Resolve sibling LinkTap entities through stable unique IDs and the Home Assistant Entity Registry.
- Support renamed/recreated/current-format Home Assistant entity IDs.
- Modernise device-relative entity naming while preserving existing unique IDs.
- Add correct flow-rate metadata and statistics support.
- Handle unavailable/unknown number helpers safely.
- Reset stale Remaining Duration to zero when watering has stopped.
- Categorise LinkTap fault indicators as diagnostic entities.
- Rename pause controls to **Pause Water Plan** and **Pause Duration Water Plan**.

## Reporting issues

When reporting an issue, please include:

- integration version;
- Home Assistant version;
- LinkTap gateway/device model and complete firmware version;
- whether the action originated from Home Assistant, the LinkTap app, MQTT or the physical device;
- relevant logs;
- raw/current entity values involved;
- clear reproduction steps.

For volume-related issues, include both the raw session `Volume` and the change in `Volume Total`.

---

This integration uses LinkTap's local HTTP API and is an independent Home Assistant community integration.
