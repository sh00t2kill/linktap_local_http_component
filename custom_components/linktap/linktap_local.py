import aiohttp
import re
import json
import logging

from .const import START_CMD, STATUS_CMD, STOP_CMD, DEFAULT_TIME

_LOGGER = logging.getLogger(__name__)

class LinktapLocal:

    ip = False

    def __init__(self):
        # Do nothing
        print("Hello, its me!")

    def set_ip(self, ip):
        self.ip = ip

    def get_ip(self, ip):
        return self.ip

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
        async with aiohttp.ClientSession() as session:
            async with await session.post(url, json=data, headers=headers) as resp:
                response = await resp.text()
        await session.close()
        _LOGGER.debug(f"Response: {response}")
        clean_resp = self.clean_response(response)
        _LOGGER.debug(f"Stripped Response: {clean_resp}")
        return json.loads(clean_resp)

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

    async def turn_on(self, gw_id, dev_id, duration):
        if not duration:
            duration = DEFAULT_TIME
        data = {
            "cmd": START_CMD,
            "gw_id": gw_id,
            "dev_id": dev_id,
            "duration": int(float(duration))
        }
        _LOGGER.debug(f"Data to Turn ON: {data}")
        status = await self._request(data)
        _LOGGER.debug(f"Response: {status}")
        return status

    async def turn_off(self, gw_id, dev_id):
        data = {
            "cmd": STOP_CMD,
            "gw_id": gw_id,
            "dev_id": dev_id,
        }
        status = await self._request(data)
        return status

    async def get_gw_id(self):
        data = {
            "cmd":3
        }
        status = await self._request(data)
        return status["gw_id"]


#linker = LinktapLocal()
#linker.set_ip("192.168.1.109")

#gw_id = "EE54B60C004B1200"
#front_garden = "67B93C27004B1200_4"

#status = await linker.get_tap_status(gw_id, front_garden)
#print(status)

