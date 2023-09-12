A custom component for linktap tap and watering valve controllers.


Linktap already have an MQTT implementation, but for home assistant users its support is rudimentary. They have a more advanced mode of operation via MQTT, but it involves complicated manual setup of switches and sensors.
This custom component replaces both of those mechanisms, and uses the locally available HTTP API.

It requires just the configuration IP of your gateway. If you have more than 1 gateway, you can setup multiple instances of the integration.

A device is created for each tap found. Multi-valve TapLinkers or ValveLinkers will get a device created for each output.
<br><b>Note:</b> version "x060820” (x is S or G, indicating that the firmware belongs to GW-01 or GW-02, respectively) is required on your Linktap Gateway in order for this component to work.

For each device, multiple entities are created:<br>
binary sensors:
<ul>
<li>Is Linked</li>
<li>Has a fall alert</li>
<li>Has a cutoff alert</li>
<li>Is leaking</li>
<li>Is clogged</li>
<li>Is broken</li>
</ul>

Binary sensors also have some services registered:<br/>
dismiss_alerts: dismiss all alerts<br/>
dismiss_alert: dismisses a single alert. Takes an entity ID of one of the binary sensors.

sensors:
<ul>
<li>Signal Strength</li>
<li>Battery</li>
<li>Total Duration</li>
<li>Remaining Duration</li>
<li>Speed</li>
<li>Volume</li>
<li>Volume Limit</li>
<li>Failsafe Duration</li>
<li>Plan Mode</li>
<li>Plan SN</li>
</ul>

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

<p><strong>NOTE: WATER BY VOLUME IS CURRENTLY PENDING A NEW RELEASE FROM LINKTAP.</strong> Until this is released, the volume parameter will have no effect.</p>

switch:<br/>
The tap/valve itself.



As yet there is no support for controlling scheduling. The API does have support for this, but unless there is demand for it, this is likely more clunky to manage in Home Assistant than the native app.
