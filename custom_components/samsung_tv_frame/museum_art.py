"""Fetch public-domain landscape art and prepare a 4K image."""
from __future__ import annotations

import asyncio
from io import BytesIO
import random
from typing import Any

import aiohttp
from PIL import Image, ImageOps
from homeassistant.helpers.aiohttp_client import async_get_clientsession

HEADERS = {"User-Agent": "HomeAssistantFrameArt/1.0 (personal museum art display)"}
MET_SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1.1/search"
MET_OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{}"
CMA = "https://openaccess-api.clevelandart.org/api/artworks/"
MAX_BYTES = 35 * 1024 * 1024
MAX_PIXELS = 50_000_000

async def _json(session, url, **params):
    async with session.get(url, params=params, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=25)) as response:
        response.raise_for_status()
        return await response.json(content_type=None)

async def _image(session, url):
    async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=60)) as response:
        response.raise_for_status()
        if response.content_length and response.content_length > MAX_BYTES:
            raise ValueError("image too large")
        result = bytearray()
        async for chunk in response.content.iter_chunked(65536):
            result.extend(chunk)
            if len(result) > MAX_BYTES:
                raise ValueError("image too large")
        return bytes(result)

def _prepare(data: bytes) -> bytes:
    with Image.open(BytesIO(data)) as original:
        if original.width * original.height > MAX_PIXELS:
            raise ValueError("image dimensions are too large")
        original = ImageOps.exif_transpose(original).convert("RGB")
        width, height = original.size
        if width < 3840 or height < 2160 or width / height < 1.25:
            raise ValueError("image is too small or not landscape")
        # Preserve the whole painting; never stretch or crop it.
        original.thumbnail((3840, 2160), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (3840, 2160), (32, 32, 32))
        canvas.paste(original, ((3840-original.width)//2, (2160-original.height)//2))
        out = BytesIO()
        canvas.save(out, "JPEG", quality=94, optimize=True)
        return out.getvalue()

async def fetch_art(hass) -> tuple[bytes, dict[str, str]]:
    """Try both museums, returning one qualifying public-domain landscape."""
    session = async_get_clientsession(hass)
    sources = ["cleveland", "met"]
    random.shuffle(sources)
    for source in sources:
        try:
            if source == "cleveland":
                params = {"has_image": "1", "cc0": "1", "type": "Painting", "q": "landscape"}
                info = await _json(session, CMA, **params, limit=1)
                total = info.get("info", {}).get("total", 0)
                if not total:
                    continue
                data = await _json(session, CMA, **params, limit=50, skip=random.randrange(max(1, total-49)))
                records = data.get("data", [])
                random.shuffle(records)
                candidates = []
                for item in records:
                    img = (item.get("images") or {}).get("print") or {}
                    if int(img.get("width") or 0) >= 3840 and int(img.get("height") or 0) >= 2160 and img.get("url"):
                        creators = item.get("creators") or []
                        candidates.append((img["url"], {"source": "Cleveland Museum of Art", "title": item.get("title") or "Untitled", "artist": creators[0].get("description", "Unknown") if creators else "Unknown", "link": item.get("url") or "https://www.clevelandart.org/open-access"}))
            else:
                info = await _json(session, MET_SEARCH, hasImages="true", isPublicDomain="true", q="landscape", medium="Paintings")
                ids = info.get("objectIDs") or []
                candidates = []
                for obj_id in random.sample(ids, min(12, len(ids))):
                    try:
                        item = await _json(session, MET_OBJECT.format(obj_id))
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                        continue
                    if item.get("isPublicDomain") and item.get("primaryImage"):
                        candidates.append((item["primaryImage"], {"source": "The Metropolitan Museum of Art", "title": item.get("title") or "Untitled", "artist": item.get("artistDisplayName") or "Unknown", "link": item.get("objectURL") or "https://www.metmuseum.org/hubs/open-access"}))
            for url, metadata in candidates[:12]:
                try:
                    data = await _image(session, url)
                    image = await hass.async_add_executor_job(_prepare, data)
                    return image, metadata
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
                    continue
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, KeyError):
            continue
    raise RuntimeError("No suitable museum image available")
