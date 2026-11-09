"""Tests for the LinktapLocal HTTP API client."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.linktap.const import (
    CONFIG_CMD,
    DEFAULT_TIME,
    DISMISS_ALERT_CMD,
    GW_IP,
    NAME,
    PAUSE_CMD,
    START_CMD,
    STATUS_CMD,
    STOP_CMD,
    TAP_ID,
)
from custom_components.linktap.linktap_local import (
    GatewayHTTPError,
    GatewayPayloadError,
    GatewayResponseError,
    LinktapLocal,
)
from custom_components.linktap.sensor import LinktapSensor
from tests.conftest import MOCK_GW_CONFIG, MOCK_GW_ID, MOCK_GW_IP, MOCK_TAP_ID


def _make_session_mock(status=200, json_payload=None, text=None):
    """Return a minimal aiohttp.ClientSession mock for _request tests."""
    resp = MagicMock()
    resp.status = status
    resp.text = AsyncMock(
        return_value=json.dumps(json_payload) if text is None else text
    )
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
            return_value=_make_session_mock(text=body),
        ):
            result = await linktap._request({"cmd": STATUS_CMD})
        assert result["gw_id"] == "testgw"
        assert result["ret"] == 0

    @pytest.mark.parametrize(
        "status,attempts", [(404, 3), (307, 1), (401, 1), (500, 1)]
    )
    async def test_http_errors_are_not_reported_as_bad_json(
        self, linktap, status, attempts
    ):
        session = _make_session_mock(status=status)
        with (
            patch("asyncio.sleep", AsyncMock()),
            patch("aiohttp.ClientSession", return_value=session),
            pytest.raises(GatewayHTTPError, match=f"HTTP {status}"),
        ):
            await linktap.get_gw_id()
        assert session.post.await_count == attempts

    @pytest.mark.parametrize(
        "body,message",
        [
            ("", "empty reply"),
            ("<html><body><!--#RET-->  </body></html>", "empty reply"),
            (
                "<html><head><title>api</title></head><body>"
                '{"gw_id":"example"}</body></html>',
                "invalid JSON",
            ),
            ('<!--#RET-->{"gw_id":', "invalid JSON"),
        ],
    )
    async def test_bad_discovery_body_has_bounded_retries(self, linktap, body, message):
        session = _make_session_mock(text=body)
        with (
            patch("asyncio.sleep", AsyncMock()),
            patch("aiohttp.ClientSession", return_value=session),
            pytest.raises(GatewayPayloadError, match=message),
        ):
            await linktap.get_gw_id()
        assert session.post.await_count == 3

    @pytest.mark.parametrize(
        "content_type", ["text/html", "application/json", "text/plain", None]
    )
    async def test_discovery_handles_documented_html_envelope(
        self, linktap, content_type
    ):
        body = (
            '<html>\r\n<head><title>api</title><meta name="robots" content="noindex">'
            '</head><body>\r\n<!--#RET-->{"cmd":3,"gw_id":"ExampleGW","ret":1}\r\n'
            "</body></html>"
        )
        session = _make_session_mock(text=body)
        session.post.return_value.headers = (
            {} if content_type is None else {"Content-Type": content_type}
        )
        with patch("aiohttp.ClientSession", return_value=session):
            assert await linktap.get_gw_id() == "ExampleGW"
        session.post.assert_awaited_once()
        assert session.post.call_args.args == (f"http://{MOCK_GW_IP}/api.shtml",)
        assert session.post.call_args.kwargs["json"] == {"cmd": 3}

    async def test_raw_json_can_contain_the_html_marker(self, linktap):
        payload = {"gw_id": "example", "name": "api <!--#RET--> <Garden>"}
        session = _make_session_mock(json_payload=payload)
        with patch("aiohttp.ClientSession", return_value=session):
            assert await linktap._request({"cmd": STATUS_CMD}) == payload

    @pytest.mark.parametrize("cmd", [START_CMD, STOP_CMD, PAUSE_CMD, 19])
    @pytest.mark.parametrize("failure", ["decode", "404", "307", "timeout"])
    async def test_ambiguous_mutation_reply_is_not_replayed(
        self, linktap, cmd, failure
    ):
        status = int(failure) if failure.isdigit() else 200
        session = _make_session_mock(status=status, text="not JSON")
        if failure == "timeout":
            session.post.side_effect = TimeoutError
        with (
            patch("aiohttp.ClientSession", return_value=session) as factory,
            pytest.raises((ValueError, TimeoutError)),
        ):
            await linktap._request({"cmd": cmd})
        session.post.assert_awaited_once()
        assert session.post.call_args.kwargs["allow_redirects"] is False
        assert factory.call_args.kwargs["timeout"].total == 10

    @pytest.mark.parametrize(
        "response",
        [
            None,
            [],
            {},
            {"ret": False},
            {"ret": "0"},
            {"ret": 0, "cmd": 6},
            {"ret": 0, "dev_id": "different"},
        ],
    )
    async def test_invalid_stop_acknowledgment_is_not_success(self, linktap, response):
        session = _make_session_mock(json_payload=response)
        with (
            patch("aiohttp.ClientSession", return_value=session),
            pytest.raises(ValueError),
        ):
            await linktap.turn_off(MOCK_GW_ID, MOCK_TAP_ID)
        session.post.assert_awaited_once()


# ---------------------------------------------------------------------------
# LinktapLocal.clean_response
# ---------------------------------------------------------------------------


class TestCleanResponse:
    def test_preserves_values_containing_wrapper_tokens(self, linktap):
        body = '<html>api{"dev_name":"api <Garden>"}api</html>'
        assert linktap.clean_response(body) == '{"dev_name":"api <Garden>"}'

    async def test_html_wrapped_array_cannot_acknowledge_stop(self, linktap):
        session = _make_session_mock(text='<html>api[{"ret":0}]api</html>')
        with (
            patch("aiohttp.ClientSession", return_value=session),
            pytest.raises(ValueError, match="not a JSON object"),
        ):
            await linktap.turn_off(MOCK_GW_ID, MOCK_TAP_ID)

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


class TestPlanModeTranslation:
    def test_maps_master_valve_mode_and_unknown_values(self):
        tap = {TAP_ID: "tap-1", NAME: "Test Tap", GW_IP: MOCK_GW_IP}
        sensor = LinktapSensor(
            MagicMock(), MagicMock(), tap, "plan_mode_string", "mode"
        )

        assert sensor.translate_plan_mode(7) == "Master Valve"
        assert sensor.translate_plan_mode(99) == "Unknown (99)"


# ---------------------------------------------------------------------------
# LinktapLocal.get_gw_id  (API helper)
# ---------------------------------------------------------------------------


class TestGetGwId:
    @pytest.mark.parametrize("payload", [{}, {"gw_id": 123}, {"gw_id": " "}])
    async def test_missing_or_invalid_id_reports_unexpected_response(
        self, linktap, payload
    ):
        session = _make_session_mock(json_payload=payload)
        with (
            patch("aiohttp.ClientSession", return_value=session),
            pytest.raises(GatewayResponseError, match="gateway ID"),
        ):
            await linktap.get_gw_id()
        session.post.assert_awaited_once()

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
    @pytest.mark.parametrize(
        "seconds,volume", [(2, 0), (86341, 0), (3.5, 0), (60, -1), (60, float("nan"))]
    )
    async def test_invalid_start_values_do_not_send(self, linktap, seconds, volume):
        with (
            patch.object(linktap, "_request", AsyncMock()) as request,
            pytest.raises(ValueError),
        ):
            await linktap.turn_on(MOCK_GW_ID, MOCK_TAP_ID, seconds, volume)
        request.assert_not_awaited()

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
            result = await linktap.turn_on(
                MOCK_GW_ID, MOCK_TAP_ID, seconds=0, volume=500
            )
        assert result is True
        payload = mock_req.call_args[0][0]
        assert payload["volume"] == 500
        assert payload["duration"] == DEFAULT_TIME * 60

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
    async def test_whole_hour_cmd18_preserves_integer_wire_format(self, linktap):
        request = AsyncMock(return_value={"ret": 0})
        with patch.object(linktap, "_request", request):
            await linktap.pause_tap(MOCK_GW_ID, MOCK_TAP_ID, 24.0)
        assert type(request.call_args.args[0]["duration"]) is int

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
