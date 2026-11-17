"""Tests for the Frame's local HDMI source channel."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from custom_components.samsung_tv_frame.input_source import select_input, InputSourceError


def message(event, data):
    return MagicMock(type=aiohttp.WSMsgType.TEXT, data=json.dumps({"event": event, "data": data}))


def answer(request, seq, response):
    return message('/sec/tv/appdata/mobilebff', {'id': request, 'seqId': str(seq), 'statusCode': 100, 'response': response})


async def test_select_input_confirms_television_readback():
    ws = MagicMock()
    ws.receive = AsyncMock(side_effect=[
        message('ms.channel.connect', {}),
        answer('get.extsources', 1, [{'sourceId': 's/source.layer.hdmi@HDMI4', 'currentSource': 'false'}]),
        answer('launch.extsource', 2, {'status': 'ok'}),
        answer('get.extsources', 3, [{'sourceId': 's/source.layer.hdmi@HDMI4', 'currentSource': 'true'}]),
    ])
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    session = MagicMock(ws_connect=AsyncMock(return_value=ws))
    await select_input(session, 'example', 'HDMI4', settle_seconds=0)
    sent = [json.loads(call.args[0]['params']['data']) for call in ws.send_json.await_args_list]
    assert [x['id'] for x in sent] == ['get.extsources', 'launch.extsource', 'get.extsources']
    assert sent[1]['params'] == {'requestId': 's/source.layer.hdmi@HDMI4'}
    ws.close.assert_awaited_once()


async def test_select_input_refuses_unknown_input_without_switching():
    ws = MagicMock()
    ws.receive = AsyncMock(side_effect=[message('ms.channel.connect', {}), answer('get.extsources', 1, [])])
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    session = MagicMock(ws_connect=AsyncMock(return_value=ws))
    with pytest.raises(InputSourceError, match='not offered'):
        await select_input(session, 'example', 'HDMI4', settle_seconds=0)
    assert ws.send_json.await_count == 1
    ws.close.assert_awaited_once()


async def test_refused_connection_is_not_retried():
    ws = MagicMock()
    ws.receive = AsyncMock(return_value=message('ms.channel.unauthorized', {}))
    ws.close = AsyncMock()
    session = MagicMock(ws_connect=AsyncMock(return_value=ws))
    with pytest.raises(InputSourceError, match='connection'):
        await select_input(session, 'example', 'HDMI4', settle_seconds=0)
    session.ws_connect.assert_awaited_once()
    ws.close.assert_awaited_once()
