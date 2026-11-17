"""Media player entity for Samsung Frame TV (state + power + basic controls)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components.media_player import (
    ATTR_MEDIA_EXTRA,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_CATEGORY_ID,
    ATTR_CONTENT_ID,
    ATTR_DURATION,
    ATTR_ENABLED,
    ATTR_FAVOURITE,
    ATTR_FILTER_ID,
    ATTR_KEY,
    ATTR_MATTE,
    ATTR_MATTE_ID,
    ATTR_PATH,
    ATTR_SHOW,
    ATTR_SHUFFLE,
    CONF_MAC,
    LOGGER,
    SERVICE_CHANGE_MATTE,
    SERVICE_DELETE_ART,
    SERVICE_SELECT_ART,
    SERVICE_SEND_KEY,
    SERVICE_SET_ART_MODE,
    SERVICE_SET_FAVOURITE,
    SERVICE_SET_PHOTO_FILTER,
    SERVICE_SET_SLIDESHOW,
    SERVICE_UPLOAD_ART,
)
from .coordinator import FrameConfigEntry, FrameCoordinator
from .entity import FrameEntity
from .frame_art import UnsupportedArtCommandError
from .models import TvMode
from .museum_art import fetch_art

PARALLEL_UPDATES = 0

_MODE_TO_STATE = {
    TvMode.OFF: MediaPlayerState.OFF,
    TvMode.WATCHING: MediaPlayerState.PLAYING,
    TvMode.ART_MODE: MediaPlayerState.ON,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FrameConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SEND_KEY,
        {vol.Required(ATTR_KEY): cv.string},
        "async_send_key_service",
    )
    platform.async_register_entity_service(
        SERVICE_SET_ART_MODE,
        {vol.Required(ATTR_ENABLED): cv.boolean},
        "async_set_art_mode_service",
    )
    platform.async_register_entity_service(
        SERVICE_SELECT_ART,
        {
            vol.Required(ATTR_CONTENT_ID): cv.string,
            vol.Optional(ATTR_SHOW, default=True): cv.boolean,
        },
        "async_select_art_service",
    )
    platform.async_register_entity_service(
        SERVICE_UPLOAD_ART,
        {
            vol.Required(ATTR_PATH): cv.string,
            vol.Optional(ATTR_MATTE, default="none"): cv.string,
            vol.Optional(ATTR_SHOW, default=True): cv.boolean,
        },
        "async_upload_art_service",
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        "list_art", {}, "async_list_art_service",
        supports_response=SupportsResponse.ONLY,
    )
    platform.async_register_entity_service(
        "rotate_museum_art", {}, "async_rotate_museum_art_service",
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        SERVICE_DELETE_ART,
        {vol.Required(ATTR_CONTENT_ID): cv.string},
        "async_delete_art_service",
    )
    platform.async_register_entity_service(
        SERVICE_SET_SLIDESHOW,
        {
            vol.Required(ATTR_DURATION): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=1440)
            ),
            vol.Optional(ATTR_SHUFFLE, default=True): cv.boolean,
            vol.Optional(ATTR_CATEGORY_ID, default="MY-C0002"): cv.string,
        },
        "async_set_slideshow_service",
    )
    platform.async_register_entity_service(
        SERVICE_CHANGE_MATTE,
        {
            vol.Required(ATTR_MATTE_ID): cv.string,
            vol.Optional(ATTR_CONTENT_ID): cv.string,
        },
        "async_change_matte_service",
    )
    platform.async_register_entity_service(
        SERVICE_SET_PHOTO_FILTER,
        {
            vol.Required(ATTR_FILTER_ID): cv.string,
            vol.Optional(ATTR_CONTENT_ID): cv.string,
        },
        "async_set_photo_filter_service",
    )
    platform.async_register_entity_service(
        SERVICE_SET_FAVOURITE,
        {
            vol.Optional(ATTR_FAVOURITE, default=True): cv.boolean,
            vol.Optional(ATTR_CONTENT_ID): cv.string,
        },
        "async_set_favourite_service",
    )
    async_add_entities([FrameMediaPlayer(entry.runtime_data)])


class FrameMediaPlayer(FrameEntity, MediaPlayerEntity):
    """Standard media_player surface; art state lives in the sensors, never here."""

    _attr_name = None  # main feature of the device
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.PLAY_MEDIA
    )

    def __init__(self, coordinator: FrameCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.config_entry.data[CONF_MAC]
        self._museum_lock = asyncio.Lock()

    @property
    def state(self) -> MediaPlayerState | None:
        return _MODE_TO_STATE.get(self.coordinator.data.tv_mode)

    @property
    def source_list(self) -> list[str] | None:
        if self.coordinator.app_map is None:
            return None
        return sorted(self.coordinator.app_map)

    @property
    def source(self) -> str | None:
        data = self.coordinator.data
        if data.tv_mode is not TvMode.WATCHING:
            return None
        # No visible app while watching = live TV or an HDMI input.
        return data.running_app or "TV"

    @property
    def app_name(self) -> str | None:
        return self.coordinator.data.running_app

    @property
    def volume_level(self) -> float | None:
        return self.coordinator.data.volume_level

    @property
    def is_volume_muted(self) -> bool | None:
        return self.coordinator.data.is_muted

    async def async_turn_on(self) -> None:
        await self.coordinator.device.async_turn_on()
        self.coordinator.async_notify_turn_on()

    async def async_turn_off(self) -> None:
        await self.coordinator.device.async_turn_off()

    async def async_volume_up(self) -> None:
        await self._async_send_key("KEY_VOLUP")

    async def async_volume_down(self) -> None:
        await self._async_send_key("KEY_VOLDOWN")

    async def async_set_volume_level(self, volume: float) -> None:
        try:
            await self.coordinator.device.async_set_volume(volume)
        except Exception as err:
            raise HomeAssistantError("Failed to set volume on the TV") from err
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        try:
            await self.coordinator.device.async_set_mute(mute)
        except Exception as err:
            raise HomeAssistantError("Failed to set mute on the TV") from err
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        await self._async_send_key("KEY_PLAY")

    async def async_media_pause(self) -> None:
        await self._async_send_key("KEY_PAUSE")

    async def async_media_stop(self) -> None:
        await self._async_send_key("KEY_STOP")

    async def async_media_next_track(self) -> None:
        await self._async_send_key("KEY_CHUP")

    async def async_media_previous_track(self) -> None:
        await self._async_send_key("KEY_CHDOWN")

    async def async_select_source(self, source: str) -> None:
        app_map = self.coordinator.app_map or {}
        app = app_map.get(source)
        if app is None:
            raise ServiceValidationError(
                f"Unknown source '{source}'; choose an app from the curated "
                "built-in catalog"
            )
        app_type = "DEEP_LINK" if app.get("app_type") == 2 else "NATIVE_LAUNCH"
        try:
            await self.coordinator.device.async_launch_app(app["appId"], app_type)
        except Exception as err:
            raise HomeAssistantError(f"Failed to launch {source}") from err

    async def async_send_key_service(self, key: str) -> None:
        await self._async_send_key(key)

    async def async_set_art_mode_service(self, enabled: bool) -> None:
        try:
            await self.coordinator.device.async_set_artmode(enabled)
        except Exception as err:
            raise HomeAssistantError("Failed to set art mode on the TV") from err
        await self.coordinator.async_request_refresh()

    async def async_select_art_service(self, content_id: str, show: bool) -> None:
        try:
            await self.coordinator.device.async_select_art(content_id, show)
        except Exception as err:
            raise HomeAssistantError(f"Failed to select artwork {content_id}") from err
        await self.coordinator.async_request_refresh()

    async def async_upload_art_service(
        self, path: str, matte: str, show: bool
    ) -> dict[str, str]:
        hass = self.hass
        if not hass.config.is_allowed_path(path):
            raise ServiceValidationError(
                f"Path '{path}' is not in allowlist_external_dirs"
            )
        file = Path(path)
        if not file.is_file():
            raise ServiceValidationError(f"No such file: {path}")
        file_type = file.suffix.lstrip(".").lower() or "png"
        data = await hass.async_add_executor_job(file.read_bytes)
        try:
            content_id = await self.coordinator.device.async_upload_art(
                data, file_type, matte
            )
        except Exception as err:
            raise HomeAssistantError(f"Failed to upload {path} to the TV") from err
        if show:
            await self.async_select_art_service(content_id, True)
        return {"content_id": content_id}

    async def async_list_art_service(self) -> dict[str, Any]:
        """Return the TV's artwork list."""
        return {"artworks": await self.coordinator.device.async_get_content_list()}

    async def async_rotate_museum_art_service(self) -> dict[str, Any]:
        """Replace at most one museum image per day when Art Mode is active."""
        async with self._museum_lock:
            store = Store(self.hass, 1, f"frame_museum_{self.coordinator.config_entry.entry_id}")
            today = dt_util.now().date().isoformat()
            state = await store.async_load() or {}
            if state.get("date") == today:
                return {"status": "already_updated", "artwork": state.get("artwork", {})}
            if self.coordinator.data.tv_mode != TvMode.ART_MODE:
                return {"status": "not_in_art_mode"}
            image, metadata = await fetch_art(self.hass)
            if self.coordinator.data.tv_mode != TvMode.ART_MODE:
                return {"status": "not_in_art_mode"}
            device = self.coordinator.device
            new_id = await device.async_upload_art(image, "jpg", "none")
            if not isinstance(new_id, str) or not new_id.startswith("MY_"):
                raise HomeAssistantError("TV did not return an uploaded image ID")
            old_ids = list(dict.fromkeys(state.get("owned_ids", [])))
            pending = {"owned_ids": list(dict.fromkeys(old_ids + [new_id])), "artwork": metadata}
            await store.async_save(pending)
            # Do not switch someone back to art if they began watching while uploading.
            if self.coordinator.data.tv_mode != TvMode.ART_MODE:
                return {"status": "uploaded_not_shown"}
            await device.async_select_art(new_id, True)
            if await device.async_get_current_art() != new_id:
                raise HomeAssistantError("TV did not confirm the new artwork; previous images retained")
            pending["date"] = today
            await store.async_save(pending)
            for old_id in old_ids:
                if old_id != new_id and old_id.startswith("MY_"):
                    try:
                        if await device.async_delete_art(old_id):
                            pending["owned_ids"].remove(old_id)
                            await store.async_save(pending)
                    except Exception:
                        # Keep the ID for retry on a later successful rotation.
                        pass
            cleanup_pending = sum(old_id in pending["owned_ids"] for old_id in old_ids if old_id != new_id)
            if cleanup_pending:
                LOGGER.warning("Museum artwork updated, but %d old image(s) could not be removed", cleanup_pending)
            await self.coordinator.async_request_refresh()
            return {
                "status": "updated_cleanup_pending" if cleanup_pending else "updated",
                "content_id": new_id,
                "artwork": metadata,
                "cleanup_pending": cleanup_pending,
            }

    async def async_delete_art_service(self, content_id: str) -> None:
        try:
            confirmed = await self.coordinator.device.async_delete_art(content_id)
        except Exception as err:
            raise HomeAssistantError(f"Failed to delete artwork {content_id}") from err
        if not confirmed:
            raise HomeAssistantError(
                f"The TV did not confirm deleting artwork {content_id}; "
                "it may still be on the TV"
            )
        await self.coordinator.async_request_refresh()

    async def async_set_slideshow_service(
        self, duration_minutes: int, shuffle: bool, category_id: str
    ) -> None:
        try:
            await self.coordinator.device.async_set_slideshow(
                duration_minutes, shuffle, category_id
            )
        except UnsupportedArtCommandError as err:
            # Carries its own reason: the TV refused the capability, or the
            # Art session went away before one could be established.
            raise HomeAssistantError(str(err)) from err
        except Exception as err:
            raise HomeAssistantError("Failed to configure the slideshow") from err
        await self.coordinator.async_request_art_reconcile()

    async def async_change_matte_service(
        self, matte_id: str, content_id: str | None = None
    ) -> None:
        content_id = self._resolve_content_id(content_id)
        try:
            await self.coordinator.device.async_change_matte(content_id, matte_id)
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to change matte on {content_id}"
            ) from err
        await self.coordinator.async_request_refresh()

    async def async_set_photo_filter_service(
        self, filter_id: str, content_id: str | None = None
    ) -> None:
        content_id = self._resolve_content_id(content_id)
        try:
            await self.coordinator.device.async_set_photo_filter(
                content_id, filter_id
            )
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to set photo filter on {content_id}"
            ) from err

    async def async_set_favourite_service(
        self, favourite: bool, content_id: str | None = None
    ) -> None:
        content_id = self._resolve_content_id(content_id)
        try:
            await self.coordinator.device.async_set_favourite(content_id, favourite)
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to change favourite on {content_id}"
            ) from err

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        """Launch an app, optionally with deep-link content.

        media_type must be "app"; media_id is an app name (from the source
        list) or a raw Tizen app id. extra.meta_tag carries deep-link content
        (e.g. a YouTube video id) — support varies per app.
        """
        if media_type != MediaType.APP:
            raise ServiceValidationError(
                f"Unsupported media type '{media_type}'; only 'app' is supported"
            )
        extra = kwargs.get(ATTR_MEDIA_EXTRA) or {}
        app_map = self.coordinator.app_map or {}
        app = app_map.get(media_id)
        app_id = app["appId"] if app else media_id
        app_type = "DEEP_LINK" if (app is None or app.get("app_type") == 2) else "NATIVE_LAUNCH"
        meta_tag = extra.get("meta_tag", "")
        try:
            await self.coordinator.device.async_launch_app(
                app_id, app_type, meta_tag
            )
        except Exception as err:
            raise HomeAssistantError(f"Failed to launch {media_id}") from err

    def _resolve_content_id(self, content_id: str | None) -> str:
        resolved = content_id or self.coordinator.data.current_art
        if not resolved:
            raise ServiceValidationError(
                "No content_id given and no current artwork is known"
            )
        return resolved

    async def _async_send_key(self, key: str) -> None:
        try:
            await self.coordinator.device.async_send_key(key)
        except Exception as err:
            raise HomeAssistantError(f"Failed to send {key} to the TV") from err
