A custom component for linktap tap and watering valve controllers.


Linktap already have an MQTT implementation, but for home assistant users its support is rudimentary. They have a more advanced mode of operation via MQTT, but it involves complicated manual setup of switches and sensors.
This custom component replaces both of those mechanisms, and uses the locally available HTTP API.

It requires just the configuration IP of your gateway. If you have more than 1 gateway, you can setup multiple instances of the integration.

A device is created for each tap found. Multi-valve TapLinkers or ValveLinkers will get a device created for each output.
<br><b>Note:</b> version `x060820` (x is S or G, indicating that the firmware belongs to GW-01 or GW-02, respectively) is required on your Linktap Gateway in order for this component to work.

<b>How do I use this integration?</b>
<p>
If you want to water by duration, and not volume:<br/>
  Set volume number entity to 0, set required duration entity to your desired time in minutes. Turn on switch/valve<br/>
If you want to water by volume, and not duration<br/>
  Set duration entity to its max number (120), set the volume you desire. Turn on switch/valve. (Note, if it matches 120 minutes first, it will turn off, as duration is required.)<br/>
If you want to order by duration OR volume.<br/>
  Set both the duration entity to your desired time, and the volume to your desired volume. Turn on switch/valve. It will turn off when it hits the first defined threshold.<br/>
</p>
For each device, multiple entities are created:<br>
binary sensors:

| Binary Sensor Name       | Description  |
|--------------------------|-------------------------------------------------------|
| Is Linked               | Is the tap linked to the gateway?                     |
| Has a fall alert        | Has an alert been raised due to a detected fall?      |
| Has a cutoff alert      | Has something happened to the tap and it failed to shut off? |
| Is leaking              | Has the tap detected a leak?                          |
| Is clogged              | Has the tap detected it is clogged?                   |
| Is broken               | Is the tap in an otherwise broken state?              |
| Is Manual Mode          | Has the tap been triggered manually (via physical button)? |
| Is Paused               | Has the tap been paused?                              |
| Is Watering             | Is the tap currently watering?                        |


Binary sensors also have some services registered:<br/>
dismiss_alerts: dismiss all alerts<br/>
dismiss_alert: dismisses a single alert. Takes an entity ID of one of the binary sensors.

Other than the alerts, the binary sensors are information about a tap, and are not controlled by the integration.

sensors:

| Sensor Name           | Description  |
|-----------------------|-----------------------------|
| Signal               | Strength of the signal between the tap and gateway |
| Battery              | Battery level of the tap device |
| Total Duration       | Watering duration of the current watering job. Should match the number entity, converted to seconds. |
| Remain Duration      | Remaining watering duration, of the current watering job|
| Speed                | Water flow speed |
| Volume               | Total water volume used for the current watering job. Resets to 0 upon completion to support the energy dashboard |
| Volume Limit         | The volume limit set on the current watering job. Should match the number entity if set. |
| Failsafe Duration    | The failsafe duration set for the tap - This is not configurable via this integration. |
| Plan Mode            | Current watering plan mode. A numerical identifier. |
| Plan Mode String     | A translation of the plan mode into the terms matching the app |
| Plan SN              | Serial number of the watering plan. A numerical identifier. |

number:
<ul>
<li>Watering Duration (Defaults to 15 minutes)</li>
<li>Watering Volume (Defaults to 0)</li>
</ul>
<p><strong>Note:</strong>The volume unit is pulled from the gateway. It can either be in L or Gal.</p>

These control the watering time and volume, when the switch for a tap is turned on.<br/>
If duration is 0 AND volume is 0, default time is applied (currently 15 mins)<br/>
If duration is 0 AND volume is >0, water by volume is used<br/>
If duration > 0 AND volume is 0, water by duration is used<br/>
If both duration AND volume > 0, both duration AND volume are used, and tap will turn off when either is reached<br/>


switch:<br/>
The tap controller itself. The switch has a number of attributes. In general these can be ignored, as they have matching sensors and binary_sensors, but are helpful in debugging.

There are 3 additional attributes set by the integration itself.

| Attribute Name           | Description  |
|-----------------------|-----------------------------|
| Duration Entity   | The entity the integration is using to control duration |
| Default time | Is the time being sent set to the default? This will be true if either the number entity has never been changed, OR if the number enttiy cannot be found (eg because its been renamed -- dont do this!) |
| Watering by Volume | Has a volume value been sent to the api when the switch/value was turned on |

valve:<br/>
A wrapper for the switch -- a valve for each tap

Using the switch and the valve are functionally equivalent, and the entities should always remain in sync.


As yet there is no support for controlling scheduling. The API does have support for this, but unless there is demand for it, this is likely more clunky to manage in Home Assistant than the native app.


<h1>FAQ</h1>
<b>Why don't my volume or speed values update? They always show 0.</b></br >
Chances are you have a G1 device. The G1 devices do not have an inbuilt flow meter. To my knowledge there is no way to retrofit one within the linktap ecosystem.<br />
https://www.link-tap.com/#!/faq/en/What-is-the-difference-between-the-G1S-and-G2S-water-timers<br /><br />


<b>Why do my taps always water for 15 mins, rather than the value defined by the duration number entity?</b><br />
This is likely due to a mapping issue with the integration. Each switch has an attribute called `duration_entity`. This should match the entity created for duration. If not, please lodge an issue.<br />
There is also an attribute called `Default Time`. If the duration entity matches, and has been changed from the default, this should be set to `false`. If not, again please lodge an issue. <br />
This can also occur if you have renamed entities, as it uses some fuzzy logic name matching in order to get the duration. If you have renamed entities in HA, delete the integration, change the names as desired in the Linktap app, and re-add the integration again. <br />

<b>I added a new taplinker or valvelinker to my gateway, and changed the names of them in the app. Why are they called TapLinker 1 and TapLinker 2 in Home Assistant?</b><br />
There can be a slight delay of up to 30 moinutes between devices being renamed on the mobile app and those changes being sycned with the local API. You can reload the integration later and the name changes should get picked up. Note that this will create all new entities, so dont setup any automations etc until the name change has come in.<br />

<b>What do I do if i have more than 1 gateway?</b><br />
If you have more than 1 gateway, ensure the local HTTP API is enabled on each one, and set them up separately via its IP address or hostname. The integration has been tested and is known to work with multiple gateways. There should be no limitation on how many gateways can be added, and in theory you should be able to add gateways that are connected to different linktap accounts, as long as they are directly accessible via HTTP.
