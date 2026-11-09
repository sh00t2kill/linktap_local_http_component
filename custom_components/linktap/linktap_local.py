import json
import logging
import math
import re
from json.decoder import JSONDecodeError

import aiohttp
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .const import (
    CONFIG_CMD,
    DEFAULT_TIME,
    DISMISS_ALERT_CMD,
    PAUSE_CMD,
    SESSION_PAUSE_CMD,
    START_CMD,
    STATUS_CMD,
    STOP_CMD,
)

_LOGGER = logging.getLogger(__name__)

SESSION_PAUSE_MIN_VERSION = 60951
REQUEST_TIMEOUT = 10
READ_COMMANDS = {STATUS_CMD, CONFIG_CMD}
HTML_REPLY_MARKER = "<!--#RET-->"


class GatewayResponseError(ValueError):
    """The gateway replied but its response could not be used."""


class GatewayPayloadError(GatewayResponseError):
    """The reply body was empty or could not be decoded."""


class GatewayHTTPError(GatewayResponseError):
    """The gateway returned an unexpected HTTP status."""

    def __init__(self, status):
        self.status = status
        super().__init__(f"Gateway returned HTTP {status}")


def _retryable_read_reply(error):
    # Older gateways occasionally return HTTP 404 on an otherwise valid read.
    return isinstance(error, GatewayPayloadError) or (
        isinstance(error, GatewayHTTPError) and error.status == 404
    )


def parse_gateway_firmware_version(version):
    """Return the six-digit LinkTap firmware number, or None if invalid.

    LinkTap defines the capability version as the six characters immediately
    following the gateway-generation prefix (for example S060951... -> 60951).
    """
    if not isinstance(version, str) or not re.match(r"^[A-Za-z][0-9]{6}", version):
        return None
    numeric_version = version[1:7]
    if not numeric_version.isdigit():
        return None
    return int(numeric_version)


def supports_session_pause(version):
    """Return CMD19/revised CMD7 support for Jim's x060951+ firmware family.

    The generation prefix and build suffix are not capability numbers. Unknown
    formats fail closed; firmware alone cannot distinguish an intermediate
    prerelease build using the same family number from the revised protocol.
    """
    numeric_version = parse_gateway_firmware_version(version)
    return (
        numeric_version is not None
        and numeric_version >= SESSION_PAUSE_MIN_VERSION
    )


class LinktapLocal:

    ip = False
    gw_id = False

    def __init__(self):
        # Keep capability unknown/legacy-safe until CMD16 config is read.
        self.gateway_version = None
        self.session_pause_supported = False

    def set_ip(self, ip):
        self.ip = ip

    def get_ip(self, ip):
        return self.ip

    def set_gw_id(self, gw_id):
        self.gw_id = gw_id

    def get_gw_id(self):
        return self.gw_id

    def clean_response(self, text):
        """Unwrap legacy HTML without rewriting JSON field values."""
        text = text.strip().removeprefix("\ufeff").lstrip()
        unwrapped = re.sub(r"^(?:\s*<[^>]*>)+", "", text)
        if (
            text.startswith("<")
            and not unwrapped.removeprefix("api").lstrip().startswith(("{", "["))
            and HTML_REPLY_MARKER in text
        ):
            # Skip the entire HTML header, including the text inside <title>.
            unwrapped = text.partition(HTML_REPLY_MARKER)[2]
        unwrapped = re.sub(r"(?:<[^>]*>\s*)+$", "", unwrapped).strip()
        return unwrapped.removeprefix("api").removesuffix("api").strip()

    async def _request(self, data):
        # A gateway may apply a write before sending a missing or malformed
        # reply. Replaying it is unsafe, particularly for CMD6 and CMD18.
        if data["cmd"] in READ_COMMANDS:
            return await self._request_read(data)
        return await self._request_once(data)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception(_retryable_read_reply),
        reraise=True,
    )
    async def _request_read(self, data):
        return await self._request_once(data)

    async def _request_once(self, data):
        headers = {"content-type": "application/json; charset=UTF-8"}

        url = "http://" + self.ip + "/api.shtml"

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        ) as session:
            async with await session.post(
                url, json=data, headers=headers, allow_redirects=False
            ) as resp:
                if not 200 <= resp.status < 300:
                    raise GatewayHTTPError(resp.status)
                try:
                    body = self.clean_response(await resp.text())
                    if not body:
                        raise GatewayPayloadError(f"CMD{data['cmd']} returned an empty reply payload")
                    response = json.loads(body)
                except (JSONDecodeError, UnicodeDecodeError) as err:
                    raise GatewayPayloadError(f"CMD{data['cmd']} returned invalid JSON") from err

        if not isinstance(response, dict):
            raise GatewayResponseError("Gateway response was not a JSON object")
        for field in ("cmd", "gw_id", "dev_id"):
            if field in data and field in response and response[field] != data[field]:
                raise GatewayResponseError(f"Gateway response did not match requested {field}")
        if ("ret" in response or data["cmd"] not in READ_COMMANDS) and type(
            response.get("ret")
        ) is not int:
            raise GatewayResponseError("Gateway response has no valid return code")
        return response

    async def fetch_data(self, gw_id, dev_id):
        status = await self.get_tap_status(gw_id, dev_id)
        return status

    async def get_tap_status(self, gw_id, dev_id):
        data = {
            "cmd": STATUS_CMD,
            "gw_id": gw_id,
            "dev_id": dev_id,
        }
        status = await self._request(data)
        # v1.11.3 documents both grouped and single-device CMD3 envelopes.
        # Older HTTP firmware returns a flat status object; preserve that form.
        if status.get("ret", 0) != 0:
            raise ValueError(f"Gateway rejected CMD3 (ret={status.get('ret')})")
        if "dev_stat" in status:
            devices = status["dev_stat"]
            if isinstance(devices, dict):
                devices = [devices]
            if not isinstance(devices, list):
                raise ValueError("Invalid CMD3 device status envelope")
            for device in devices:
                if isinstance(device, dict) and device.get("dev_id") == dev_id:
                    return {**{k: v for k, v in status.items() if k != "dev_stat"}, **device}
            raise ValueError("CMD3 did not contain the requested device")
        return status

    async def turn_on(self, gw_id, dev_id, seconds=None, volume=None):
        if seconds is None or seconds == 0:
            seconds = DEFAULT_TIME * 60
        duration = float(seconds)
        if not duration.is_integer() or not 3 <= duration <= 86340:
            raise ValueError("Watering duration must be a whole number of seconds from 3 to 86340")
        volume = 0 if volume is None else float(volume)
        if not math.isfinite(volume) or not 0 <= volume <= 60000:
            raise ValueError("Watering volume must be finite and between 0 and 60000")
        data = {
            "cmd": START_CMD,
            "gw_id": gw_id,
            "dev_id": dev_id,
            "duration": int(duration),
        }
        if volume and volume != 0:
            data["volume"] = volume
        # Deliberately omit live_only. It is persistent gateway state, including
        # later physical-button/server/CMD4 sessions, until reset or restart.
        # In live_only mode runtime totals clear only at session end, not pause.
        _LOGGER.debug(f"Data to Turn ON: {data}")
        status = await self._request(data)
        _LOGGER.debug(f"Response: {status}")
        return status["ret"] == 0

    async def turn_off(self, gw_id, dev_id):
        data = {
            "cmd": STOP_CMD,
            "gw_id": gw_id,
            "dev_id": dev_id,
        }
        status = await self._request(data)
        return status["ret"] == 0

    async def cmd18(self, gw_id, dev_id, hours):
        """Pause/resume the server watering plan; never a current session."""
        if isinstance(hours, float) and hours.is_integer():
            hours = int(hours)  # Preserve the original integer wire format.
        data = {
            "cmd": PAUSE_CMD,
            "gw_id": gw_id,
            "dev_id": dev_id,
            "duration": hours,
        }
        _LOGGER.debug(f"Pause Payload: {data}")
        status = await self._request(data)
        _LOGGER.debug(f"Pause Response: {status}")
        return status

    async def pause_tap(self, gw_id, dev_id, hours):
        """Send CMD18 while preserving the existing boolean API contract."""
        status = await self.cmd18(gw_id, dev_id, hours)
        return status["ret"] == 0

    async def cmd19(self, gw_id, dev_id, hours, option=0):
        """Pause/resume the current session, returning the gateway response."""
        if not self.session_pause_supported:
            raise ValueError("Gateway firmware does not support CMD19")
        if type(option) is not int or option not in (0, 1):
            raise ValueError("CMD19 option must be 0 or 1")
        data = {
            "cmd": SESSION_PAUSE_CMD,
            "gw_id": gw_id,
            "dev_id": dev_id,
            "duration": hours,
        }
        if hours != 0:
            data["option"] = option
        return await self._request(data)

    async def get_gw_config(self, gw_id):
        data = {"cmd": CONFIG_CMD, "gw_id": gw_id}
        status = await self._request(data)
        # async_setup_entry already reads CMD16 once at startup. Cache the
        # capability on this shared API object so every tap coordinator can use
        # the same gateway-level result without another HTTP request.
        self.gateway_version = status.get("ver")
        self.session_pause_supported = (
            status.get("ret", 0) == 0 and supports_session_pause(self.gateway_version)
        )
        _LOGGER.debug(
            "LinkTap gateway firmware %r CMD19 support: %s",
            self.gateway_version,
            self.session_pause_supported,
        )
        return status

    async def get_vol_unit(self, gw_id):
        config = await self.get_gw_config(gw_id)
        return config["vol_unit"]

    async def get_version(self, gw_id):
        config = await self.get_gw_config(gw_id)
        return config["ver"]

    async def get_end_devs(self, gw_id):
        config = await self.get_gw_config(gw_id)
        return {
            "devs": config["end_dev"],
            "names": config["dev_name"],
        }

    async def get_gw_id(self):
        # The legacy discovery request intentionally omits the IDs. The gateway
        # can return a nonzero ret along with its own ID in this case.
        data = {"cmd": STATUS_CMD}
        status = await self._request(data)
        gw_id = status.get("gw_id")
        if not isinstance(gw_id, str) or not gw_id.strip():
            raise GatewayResponseError("CMD3 discovery reply has no valid gateway ID")
        return gw_id

    async def dismiss_alert(self, gw_id, dev_id, alert_id=False):
        if not alert_id:
            alert_id = 0
        data = {
            "cmd": DISMISS_ALERT_CMD,
            "gw_id": gw_id,
            "dev_id": dev_id,
            "alert": alert_id,
            "enable": True,
        }
        status = await self._request(data)
        return status["ret"] == 0
        return status["ret"] == 0
