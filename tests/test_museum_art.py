"""Tests for museum artwork selection and image safety."""
from io import BytesIO
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from PIL import Image

from custom_components.samsung_tv_frame import museum_art


def test_prepare_rejects_oversized_image_before_decoding(monkeypatch):
    image = Image.new("RGB", (4000, 3000))
    payload = BytesIO()
    image.save(payload, "PNG")
    monkeypatch.setattr(museum_art, "MAX_PIXELS", 10_000_000, raising=False)
    with patch.object(Image.Image, "convert", side_effect=AssertionError("decoded")):
        with pytest.raises(ValueError, match="too large"):
            museum_art._prepare(payload.getvalue())


async def test_met_skips_failed_metadata_and_uses_next_candidate(hass, monkeypatch):
    monkeypatch.setattr(museum_art.random, "shuffle", lambda x: None)
    monkeypatch.setattr(museum_art.random, "sample", lambda x, n: x[:n])
    async def get_json(session, url, **params):
        if url == museum_art.CMA:
            return {"info": {"total": 0}}
        if url == museum_art.MET_SEARCH:
            return {"objectIDs": [1, 2]}
        if url.endswith("/1"):
            raise aiohttp.ClientConnectionError("temporary failure")
        return {"isPublicDomain": True, "primaryImage": "https://example.org/art.jpg", "title": "Painting"}
    monkeypatch.setattr(museum_art, "_json", get_json)
    monkeypatch.setattr(museum_art, "_image", AsyncMock(return_value=b"image"))
    monkeypatch.setattr(museum_art, "_prepare", lambda data: b"prepared")
    image, metadata = await museum_art.fetch_art(hass)
    assert image == b"prepared"
    assert metadata["title"] == "Painting"


def test_prepare_preserves_landscape_without_stretching():
    source = Image.new("RGB", (3840, 2400), (255, 0, 0))
    payload = BytesIO()
    source.save(payload, "PNG")
    with Image.open(BytesIO(museum_art._prepare(payload.getvalue()))) as result:
        assert result.size == (3840, 2160)
        # The 16:10 image is letterboxed on both sides, not cropped.
        assert result.getpixel((0, 1080))[0] < 40
        assert result.getpixel((1920, 1080))[0] > 240


async def test_met_skips_malformed_metadata_and_continues(hass, monkeypatch):
    monkeypatch.setattr(museum_art.random, "shuffle", lambda x: None)
    monkeypatch.setattr(museum_art.random, "sample", lambda x, n: x[:n])
    async def get_json(session, url, **params):
        if url == museum_art.CMA:
            return {"info": {"total": 0}}
        if url == museum_art.MET_SEARCH:
            return {"objectIDs": [1, 2]}
        if url.endswith("/1"):
            return None
        return {"isPublicDomain": True, "primaryImage": "https://example.org/art.jpg", "title": "Painting"}
    monkeypatch.setattr(museum_art, "_json", get_json)
    monkeypatch.setattr(museum_art, "_image", AsyncMock(return_value=b"image"))
    monkeypatch.setattr(museum_art, "_prepare", lambda data: b"prepared")
    image, metadata = await museum_art.fetch_art(hass)
    assert image == b"prepared"
    assert metadata["title"] == "Painting"


async def test_skips_decompression_bomb_and_uses_another_image(hass, monkeypatch):
    monkeypatch.setattr(museum_art.random, "shuffle", lambda x: None)
    async def get_json(session, url, **params):
        if url == museum_art.CMA and params.get("limit") == 1:
            return {"info": {"total": 2}}
        if url == museum_art.CMA:
            return {"data": [
                {"title": "Huge", "images": {"print": {"width": 4000, "height": 3000, "url": "https://example.org/huge"}}},
                {"title": "Valid", "images": {"print": {"width": 4000, "height": 3000, "url": "https://example.org/valid"}}},
            ]}
        raise AssertionError("unexpected request")
    monkeypatch.setattr(museum_art, "_json", get_json)
    monkeypatch.setattr(museum_art, "_image", AsyncMock(side_effect=[b"huge", b"valid"]))
    def prepare(data):
        if data == b"huge":
            raise Image.DecompressionBombError("too large")
        return b"prepared"
    monkeypatch.setattr(museum_art, "_prepare", prepare)
    image, metadata = await museum_art.fetch_art(hass)
    assert image == b"prepared"
    assert metadata["title"] == "Valid"
