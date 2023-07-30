import asyncio
import json
import logging
import random
import re
from json.decoder import JSONDecodeError

import aiohttp

from .const import (CONFIG_CMD, DEFAULT_TIME, DISMISS_ALERT_CMD, START_CMD,
                    STATUS_CMD, STOP_CMD)

_LOGGER = logging.getLogger(__name__)

class LinktapLocal:

    ip = False
    gw_id = False

    def __init__(self):
        # Do nothing
        print("Hello, its me!")

    def set_ip(self, ip):
        self.ip = ip

    def get_ip(self, ip):
        return self.ip

    def set_gw_id(self, gw_id):
        self.gw_id = gw_id

    def get_gw_id(self):
        return self.gw_id

    def clean_response(self, text):
        """Remove html tags from a string"""
        text = text.replace("api", "")
        clean = re.compile('<.*?>')
        cleaned_text = re.sub(clean, '', text)
        cleaned_text = cleaned_text.replace("api", "")
        return cleaned_text.strip()

    async def _request(self, data):

        headers = {
          "content-type": "application/json; charset=UTF-8"
        }

        url = "http://" + self.ip + "/api.shtml"
        response = await self._make_request(url, data, headers)
        # Every now and then, a request will throw a 404.
        # Ive never seen it fail twice, so lets try it again.
        if response.find("404") != -1:
            _LOGGER.debug("Got a 404 issue: Wait and try again")
            await asyncio.sleep(random.randint(1,3))
            response = await self._make_request(url, data, headers)
        try:
            jsonresp = json.loads(self.clean_response(response))
        except JSONDecodeError:
            response = await self._make_request(url, data, headers)
            jsonresp = json.loads(self.clean_response(response))
        return jsonresp

    async def _make_request(self, url, data, headers):
        async with aiohttp.ClientSession() as session:
                async with await session.post(url, json=data, headers=headers) as resp:
                    response = await resp.text()
        await session.close()
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
        return status

    async def turn_on(self, gw_id, dev_id, seconds=None, volume=None):
        if (not seconds or seconds == 0) and not volume:
            seconds = DEFAULT_TIME
        data = {
            "cmd": START_CMD,
            "gw_id": gw_id,
            "dev_id": dev_id,
            "duration": int(float(seconds))
        }
        if volume and volume != 0:
            data["volume"] = volume
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

    async def get_gw_config(self, gw_id):
        data = {
            "cmd": CONFIG_CMD,
            "gw_id": gw_id
        }
        status = await self._request(data)
        return status

    ## Config helper functions: If multiples of these are going to be used,
    ## it would make sense to use the config function above and use the output
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

    """This is potentially a little hacky, as it actually sends a malformatted request to the gateway.
    The ID of the gateway is returned in this malformed request, so lets use it for good and not evil."""
    async def get_gw_id(self):
        data = {
            "cmd":STATUS_CMD
        }
        status = await self._request(data)
        return status["gw_id"]

    """alert: type of alert
    0: all types of alert.
    1: device fall alert.
    2: valve shut-down failure alert.
    3: water cut-off alert.
    4: unusually high flow alert.
    5: unusually low flow alert.
    """
    async def dismiss_alert(self, gw_id, dev_id, alert_id=False):
        if not alert_id:
            alert_id = 0
        data = {
            "cmd": DISMISS_ALERT_CMD,
            "gw_id": gw_id,
            "dev_id": dev_id,
            "alert": alert_id,
            "enable": True
        }
        status = await self._request(data)
        return status["ret"] == 0
