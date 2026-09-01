"""Tests for the LinktapLocal HTTP API client."""

from __future__ import annotations

from json import JSONDecodeError
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp.client_exceptions
import pytest
from tenacity import RetryError

from custom_components.linktap.const import (
    CONFIG_CMD,
    DEFAULT_TIME,
    DISMISS_ALERT_CMD,
    PAUSE_CMD,
    START_CMD,
    STATUS_CMD,
    STOP_CMD,
)
from custom_components.linktap.linktap_local import LinktapLocal
from tests.conftest import MOCK_GW_CONFIG, MOCK_GW_ID, MOCK_GW_IP, MOCK_TAP_ID


def _make_session_mock(
    status=200, json_payload=None, raises_content_type_error=False, text=None
):
    """Return a minimal aiohttp.ClientSession mock for _request tests."""
    resp = MagicMock()
    resp.status = status
    if raises_content_type_error:
        resp.json = AsyncMock(
            side_effect=aiohttp.client_exceptions.ContentTypeError(
                MagicMock(), MagicMock()
            )
        )
        resp.text = AsyncMock(return_value=text or "")
    else:
        resp.json = AsyncMock(return_value=json_payload)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.post = AsyncMock(return_value=resp)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.fixture
def linktap():
    client = LinktapLocal()
    client.set_ip(MOCK_GW_IP)
    return client


# ---------------------------------------------------------------------------
# LinktapLocal._request  (HTTP layer)
# ---------------------------------------------------------------------------


class TestRequest:
    async def test_success_returns_parsed_json(self, linktap):
        payload = {"ret": 0, "gw_id": MOCK_GW_ID}
        with patch(
            "aiohttp.ClientSession",
            return_value=_make_session_mock(json_payload=payload),
        ):
            result = await linktap._request({"cmd": STATUS_CMD})
        assert result == payload

    async def test_html_wrapped_response_is_parsed_via_fallback(self, linktap):
        """Gateway sometimes wraps JSON in HTML tags; the client must strip them."""
        body = '<html><body>api{"ret":0,"gw_id":"testgw"}api</body></html>'
        with patch(
            "aiohttp.ClientSession",
            return_value=_make_session_mock(raises_content_type_error=True, text=body),
        ):
            result = await linktap._request({"cmd": STATUS_CMD})
        assert result["gw_id"] == "testgw"
        assert result["ret"] == 0

    async def test_404_raises_retry_error_after_exhausted_attempts(self, linktap):
        """After 3 failed 404s tenacity wraps the JSONDecodeError in RetryError."""
        with patch("asyncio.sleep", AsyncMock()):  # skip tenacity back-off waits
            with patch(
                "aiohttp.ClientSession",
                return_value=_make_session_mock(status=404, json_payload={"ret": 1}),
            ):
                with pytest.raises(RetryError) as exc_info:
                    await linktap._request({"cmd": STATUS_CMD})
        assert isinstance(exc_info.value.last_attempt.exception(), JSONDecodeError)


# ---------------------------------------------------------------------------
# LinktapLocal.clean_response
# ---------------------------------------------------------------------------


class TestCleanResponse:
    def test_strips_html_tags(self, linktap):
        html = '<html><body>api{"ret": 0}api</body></html>'
        result = linktap.clean_response(html)
        assert result == '{"ret": 0}'

    def test_strips_bare_api_prefix_and_suffix(self, linktap):
        result = linktap.clean_response('api{"ret": 0}api')
        assert result == '{"ret": 0}'

    def test_strips_whitespace(self, linktap):
        result = linktap.clean_response('  {"ret": 0}  ')
        assert result == '{"ret": 0}'


# ---------------------------------------------------------------------------
# LinktapLocal.get_gw_id  (API helper)
# ---------------------------------------------------------------------------


class TestGetGwId:
    async def test_returns_gw_id_from_response(self, linktap):
        resp = {"gw_id": MOCK_GW_ID, "ret": 0}
        with patch.object(linktap, "_request", AsyncMock(return_value=resp)):
            result = await linktap.get_gw_id()
        assert result == MOCK_GW_ID

    async def test_sends_status_cmd_without_dev_id(self, linktap):
        mock_req = AsyncMock(return_value={"gw_id": MOCK_GW_ID, "ret": 0})
        with patch.object(linktap, "_request", mock_req):
            await linktap.get_gw_id()
        assert mock_req.call_args[0][0] == {"cmd": STATUS_CMD}


# ---------------------------------------------------------------------------
# LinktapLocal.get_gw_config
# ---------------------------------------------------------------------------


class TestGetGwConfig:
    async def test_returns_full_config(self, linktap):
        with patch.object(linktap, "_request", AsyncMock(return_value=MOCK_GW_CONFIG)):
            result = await linktap.get_gw_config(MOCK_GW_ID)
        assert result["end_dev"] == [MOCK_TAP_ID]
        assert result["vol_unit"] == "L"

    async def test_sends_config_cmd_with_gw_id(self, linktap):
        mock_req = AsyncMock(return_value=MOCK_GW_CONFIG)
        with patch.object(linktap, "_request", mock_req):
            await linktap.get_gw_config(MOCK_GW_ID)
        mock_req.assert_called_once_with({"cmd": CONFIG_CMD, "gw_id": MOCK_GW_ID})


# ---------------------------------------------------------------------------
# LinktapLocal.turn_on / turn_off
# ---------------------------------------------------------------------------


class TestTurnOn:
    async def test_returns_true_on_success(self, linktap):
        with patch.object(linktap, "_request", AsyncMock(return_value={"ret": 0})):
            result = await linktap.turn_on(MOCK_GW_ID, MOCK_TAP_ID, seconds=120)
        assert result is True

    async def test_returns_false_on_gateway_error(self, linktap):
        with patch.object(linktap, "_request", AsyncMock(return_value={"ret": 1})):
            result = await linktap.turn_on(MOCK_GW_ID, MOCK_TAP_ID, seconds=60)
        assert result is False

    async def test_sends_start_cmd_with_duration(self, linktap):
        mock_req = AsyncMock(return_value={"ret": 0})
        with patch.object(linktap, "_request", mock_req):
            await linktap.turn_on(MOCK_GW_ID, MOCK_TAP_ID, seconds=300)
        payload = mock_req.call_args[0][0]
        assert payload["cmd"] == START_CMD
        assert payload["duration"] == 300
        assert "volume" not in payload

    async def test_uses_default_duration_when_no_args_given(self, linktap):
        mock_req = AsyncMock(return_value={"ret": 0})
        with patch.object(linktap, "_request", mock_req):
            await linktap.turn_on(MOCK_GW_ID, MOCK_TAP_ID)
        payload = mock_req.call_args[0][0]
        assert payload["duration"] == DEFAULT_TIME * 60

    async def test_sends_volume_when_provided(self, linktap):
        mock_req = AsyncMock(return_value={"ret": 0})
        with patch.object(linktap, "_request", mock_req):
            # seconds=0 avoids float(None) — turn_on always builds a duration field.
            result = await linktap.turn_on(
                MOCK_GW_ID, MOCK_TAP_ID, seconds=0, volume=500
            )
        assert result is True
        payload = mock_req.call_args[0][0]
        assert payload["volume"] == 500

    async def test_volume_zero_is_not_sent(self, linktap):
        """A volume of 0 must not be included in the payload (falsy guard)."""
        mock_req = AsyncMock(return_value={"ret": 0})
        with patch.object(linktap, "_request", mock_req):
            await linktap.turn_on(MOCK_GW_ID, MOCK_TAP_ID, seconds=60, volume=0)
        payload = mock_req.call_args[0][0]
        assert "volume" not in payload


class TestTurnOff:
    async def test_returns_true_on_success(self, linktap):
        with patch.object(linktap, "_request", AsyncMock(return_value={"ret": 0})):
            result = await linktap.turn_off(MOCK_GW_ID, MOCK_TAP_ID)
        assert result is True

    async def test_returns_false_on_gateway_error(self, linktap):
        with patch.object(linktap, "_request", AsyncMock(return_value={"ret": 1})):
            result = await linktap.turn_off(MOCK_GW_ID, MOCK_TAP_ID)
        assert result is False

    async def test_sends_stop_cmd(self, linktap):
        mock_req = AsyncMock(return_value={"ret": 0})
        with patch.object(linktap, "_request", mock_req):
            await linktap.turn_off(MOCK_GW_ID, MOCK_TAP_ID)
        assert mock_req.call_args[0][0]["cmd"] == STOP_CMD


# ---------------------------------------------------------------------------
# LinktapLocal.pause_tap
# ---------------------------------------------------------------------------


class TestPauseTap:
    async def test_returns_true_on_success(self, linktap):
        with patch.object(linktap, "_request", AsyncMock(return_value={"ret": 0})):
            result = await linktap.pause_tap(MOCK_GW_ID, MOCK_TAP_ID, hours=2)
        assert result is True

    async def test_sends_pause_cmd_with_duration(self, linktap):
        mock_req = AsyncMock(return_value={"ret": 0})
        with patch.object(linktap, "_request", mock_req):
            await linktap.pause_tap(MOCK_GW_ID, MOCK_TAP_ID, hours=3)
        payload = mock_req.call_args[0][0]
        assert payload["cmd"] == PAUSE_CMD
        assert payload["duration"] == 3
        assert payload["gw_id"] == MOCK_GW_ID
        assert payload["dev_id"] == MOCK_TAP_ID


# ---------------------------------------------------------------------------
# LinktapLocal.dismiss_alert
# ---------------------------------------------------------------------------


class TestDismissAlert:
    async def test_defaults_to_alert_type_zero(self, linktap):
        mock_req = AsyncMock(return_value={"ret": 0})
        with patch.object(linktap, "_request", mock_req):
            result = await linktap.dismiss_alert(MOCK_GW_ID, MOCK_TAP_ID)
        assert result is True
        assert mock_req.call_args[0][0]["alert"] == 0

    async def test_sends_specific_alert_type(self, linktap):
        mock_req = AsyncMock(return_value={"ret": 0})
        with patch.object(linktap, "_request", mock_req):
            result = await linktap.dismiss_alert(MOCK_GW_ID, MOCK_TAP_ID, alert_id=2)
        assert result is True
        assert mock_req.call_args[0][0]["alert"] == 2

    async def test_sends_dismiss_cmd(self, linktap):
        mock_req = AsyncMock(return_value={"ret": 0})
        with patch.object(linktap, "_request", mock_req):
            await linktap.dismiss_alert(MOCK_GW_ID, MOCK_TAP_ID)
        assert mock_req.call_args[0][0]["cmd"] == DISMISS_ALERT_CMD
