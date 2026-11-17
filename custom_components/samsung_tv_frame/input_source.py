"""Select an external input using the Frame's local mobilebff channel."""
from __future__ import annotations

import asyncio
import base64
import json

import aiohttp

from .const import CLIENT_NAME

CHANNEL = "com.samsung.tv.mobilebff"
EVENT = "/sec/tv/appdata/mobilebff"


class InputSourceError(Exception):
    """The TV did not confirm the input request."""


async def select_input(session, host: str, source: str, *, settle_seconds: float = 3) -> None:
    """Select an offered HDMI input once and confirm it from the TV's list.

    This opens one tokenless connection and never retries a handshake. Callers
    must prevent repeated attempts after connection errors or rejection.
    """
    name = base64.b64encode(CLIENT_NAME.encode()).decode()
    url = f"wss://{host}:8002/api/v2/channels/{CHANNEL}?name={name}"
    ws = None
    try:
        async with asyncio.timeout(25):
            ws = await session.ws_connect(url, ssl=False)
            hello = await ws.receive()
            if hello.type != aiohttp.WSMsgType.TEXT or json.loads(hello.data).get("event") != "ms.channel.connect":
                raise InputSourceError("TV input connection was not accepted")
            seq = 0

            async def request(name: str, params: dict) -> dict:
                nonlocal seq
                seq += 1
                identifier = str(seq)
                inner = {"version": "0.2", "id": name, "seqId": identifier, "params": params}
                await ws.send_json({"method": "ms.channel.emit", "params": {"event": EVENT, "to": "host", "data": json.dumps(inner)}})
                async with asyncio.timeout(8):
                    while True:
                        msg = await ws.receive()
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            raise InputSourceError("TV input connection closed")
                        outer = json.loads(msg.data)
                        if outer.get("event") != EVENT:
                            continue
                        payload = outer.get("data")
                        if isinstance(payload, str):
                            payload = json.loads(payload)
                        if isinstance(payload, dict) and payload.get("id") == name and payload.get("seqId") == identifier:
                            return payload

            listing = await request("get.extsources", {})
            entries = listing.get("response")
            if not isinstance(entries, list):
                raise InputSourceError("TV returned an invalid input list")
            target = f"s/source.layer.hdmi@{source}"
            if not any(isinstance(x, dict) and x.get("sourceId") == target for x in entries):
                raise InputSourceError("HDMI input is not offered by the TV")
            response = await request("launch.extsource", {"requestId": target})
            if response.get("statusCode") != 100 or response.get("response", {}).get("status") != "ok":
                raise InputSourceError("TV rejected the input request")
            await asyncio.sleep(settle_seconds)
            listing = await request("get.extsources", {})
            entries = listing.get("response")
            if not isinstance(entries, list) or not any(
                isinstance(x, dict) and x.get("sourceId") == target
                and str(x.get("currentSource")).lower() == "true" for x in entries
            ):
                raise InputSourceError("TV did not confirm the selected input")
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, AttributeError) as err:
        raise InputSourceError("TV input connection failed") from err
    finally:
        if ws is not None:
            await ws.close()
