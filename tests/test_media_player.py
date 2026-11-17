# tests/test_media_player.py
from unittest.mock import AsyncMock, call, patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samsung_tv_frame.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_TOKEN,
    DEFAULT_APP_MAP,
    DOMAIN,
)

ENTITY = "media_player.samsung_frame_tv"


async def _setup(hass, mock_device):
    mock_device.art_ready = True
    mock_device.art_generation = 1
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "1.2.3.4", CONF_MAC: "02:00:00:00:00:01", CONF_TOKEN: "t"},
        unique_id="02:00:00:00:00:01",
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.samsung_tv_frame.FrameDevice", return_value=mock_device
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_media_player_reports_playing_when_watching(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    state = hass.states.get("media_player.samsung_frame_tv")
    assert state is not None
    assert state.state == "playing"


async def test_turn_on_sends_wol_and_kicks_wake_probe(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    entry = await _setup(hass, mock_device)
    coordinator = entry.runtime_data
    with patch.object(coordinator, "async_notify_turn_on") as notify:
        await hass.services.async_call(
            "media_player", "turn_on",
            {"entity_id": "media_player.samsung_frame_tv"}, blocking=True,
        )
    mock_device.async_turn_on.assert_awaited_once()
    notify.assert_called_once()


async def test_turn_off_calls_device(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    await hass.services.async_call(
        "media_player", "turn_off",
        {"entity_id": "media_player.samsung_frame_tv"}, blocking=True,
    )
    mock_device.async_turn_off.assert_awaited_once()


@pytest.mark.parametrize(
    ("service", "data", "expected_key"),
    [
        ("volume_up", {}, "KEY_VOLUP"),
        ("volume_down", {}, "KEY_VOLDOWN"),
        ("media_play", {}, "KEY_PLAY"),
        ("media_pause", {}, "KEY_PAUSE"),
        ("media_stop", {}, "KEY_STOP"),
        ("media_next_track", {}, "KEY_CHUP"),
        ("media_previous_track", {}, "KEY_CHDOWN"),
    ],
)
async def test_key_backed_controls(hass, mock_device, service, data, expected_key):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    await hass.services.async_call(
        "media_player", service, {"entity_id": ENTITY, **data}, blocking=True,
    )
    mock_device.async_send_key.assert_awaited_once_with(expected_key)


async def test_volume_level_and_mute_reported(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    mock_device.async_get_volume.return_value = (0.23, False)
    await _setup(hass, mock_device)
    state = hass.states.get(ENTITY)
    assert state.attributes["volume_level"] == 0.23
    assert state.attributes["is_volume_muted"] is False


async def test_set_volume_level(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    await hass.services.async_call(
        "media_player", "volume_set",
        {"entity_id": ENTITY, "volume_level": 0.4}, blocking=True,
    )
    mock_device.async_set_volume.assert_awaited_once_with(0.4)


async def test_mute_uses_upnp_absolute_mute(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    await hass.services.async_call(
        "media_player", "volume_mute",
        {"entity_id": ENTITY, "is_volume_muted": True}, blocking=True,
    )
    mock_device.async_set_mute.assert_awaited_once_with(True)


async def test_send_key_failure_raises_ha_error(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    mock_device.async_send_key.side_effect = OSError("gone")
    await _setup(hass, mock_device)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "media_player", "volume_up", {"entity_id": ENTITY}, blocking=True,
        )


async def test_select_source_launches_app(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    await hass.async_block_till_done(wait_background_tasks=True)

    state = hass.states.get(ENTITY)
    assert state.attributes["source_list"] == sorted(DEFAULT_APP_MAP)

    await hass.services.async_call(
        "media_player", "select_source",
        {"entity_id": ENTITY, "source": "Netflix"}, blocking=True,
    )
    mock_device.async_launch_app.assert_awaited_once_with("11101200001", "DEEP_LINK")

    mock_device.async_launch_app.reset_mock()
    await hass.services.async_call(
        "media_player", "select_source",
        {"entity_id": ENTITY, "source": "YouTube"}, blocking=True,
    )
    mock_device.async_launch_app.assert_awaited_once_with(
        "111299001912", "DEEP_LINK"
    )


async def test_select_source_unknown_app_raises(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            "media_player", "select_source",
            {"entity_id": ENTITY, "source": "Nope"}, blocking=True,
        )

    assert str(raised.value) == (
        "Unknown source 'Nope'; choose an app from the curated built-in "
        "catalog"
    )


async def test_media_player_sources_are_exact_curated_builtin_catalog(
    hass, mock_device
):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    mock_device.remote_confirmed = True
    mock_device.async_app_list.return_value = [
        {"name": "Discovered App", "appId": "PRIVATE", "app_type": 4}
    ]
    await _setup(hass, mock_device)
    await hass.async_block_till_done(wait_background_tasks=True)

    state = hass.states.get(ENTITY)
    assert state.attributes["source_list"] == sorted(DEFAULT_APP_MAP)
    mock_device.async_app_list.assert_not_awaited()


async def test_send_key_entity_service(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    await hass.services.async_call(
        DOMAIN, "send_key",
        {"entity_id": ENTITY, "key": "KEY_HOME"}, blocking=True,
    )
    mock_device.async_send_key.assert_awaited_once_with("KEY_HOME")


async def test_set_art_mode_entity_service(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    await hass.services.async_call(
        DOMAIN, "set_art_mode",
        {"entity_id": ENTITY, "enabled": True}, blocking=True,
    )
    mock_device.async_set_artmode.assert_awaited_once_with(True)


async def test_source_and_app_name_reflect_running_app(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False

    async def _status(_app_id):
        return {"visible": True, "running": True}

    mock_device.async_app_status.side_effect = _status
    await _setup(hass, mock_device)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    await coordinator.async_refresh()
    state = hass.states.get(ENTITY)
    assert state.attributes["source"] == "Netflix"
    assert state.attributes["app_name"] == "Netflix"


async def test_source_falls_back_to_tv_when_no_app_visible(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    mock_device.async_app_status.return_value = {"visible": False}
    await _setup(hass, mock_device)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    await coordinator.async_refresh()
    state = hass.states.get(ENTITY)
    assert state.attributes["source"] == "TV"
    assert "app_name" not in state.attributes


async def test_select_art_service(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    await hass.services.async_call(
        DOMAIN, "select_art",
        {"entity_id": ENTITY, "content_id": "MY_F0034"}, blocking=True,
    )
    mock_device.async_select_art.assert_awaited_once_with("MY_F0034", True)


async def test_upload_art_service(hass, mock_device, tmp_path):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    img = tmp_path / "monet.jpg"
    img.write_bytes(b"fake-jpeg-bytes")
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    await _setup(hass, mock_device)
    await hass.services.async_call(
        DOMAIN, "upload_art",
        {"entity_id": ENTITY, "path": str(img)}, blocking=True,
    )
    mock_device.async_upload_art.assert_awaited_once_with(
        b"fake-jpeg-bytes", "jpg", "none"
    )
    # show=True default selects the freshly uploaded content id
    mock_device.async_select_art.assert_awaited_once_with("MY_F9999", True)


async def test_upload_art_rejects_disallowed_path(hass, mock_device, tmp_path):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    img = tmp_path / "monet.jpg"
    img.write_bytes(b"x")
    await _setup(hass, mock_device)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "upload_art",
            {"entity_id": ENTITY, "path": str(img)}, blocking=True,
        )
    mock_device.async_upload_art.assert_not_awaited()


async def test_delete_art_service(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    mock_device.async_delete_art.return_value = True
    await _setup(hass, mock_device)
    await hass.services.async_call(
        DOMAIN, "delete_art",
        {"entity_id": ENTITY, "content_id": "MY_F0001"}, blocking=True,
    )
    mock_device.async_delete_art.assert_awaited_once_with("MY_F0001")


async def test_delete_art_service_fails_when_the_tv_does_not_confirm(
    hass, mock_device
):
    """An unconfirmed delete must not be reported to the user as success.

    The TV echoes the deleted content id back on success (live 2026-08-16),
    so a reply that fails that check deleted nothing we can point to.
    """
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    mock_device.async_delete_art.return_value = False
    await _setup(hass, mock_device)

    with pytest.raises(HomeAssistantError, match="did not confirm"):
        await hass.services.async_call(
            DOMAIN, "delete_art",
            {"entity_id": ENTITY, "content_id": "MY_F0001"}, blocking=True,
        )
    mock_device.async_delete_art.assert_awaited_once_with("MY_F0001")


async def test_set_slideshow_service(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    entry = await _setup(hass, mock_device)
    coordinator = entry.runtime_data
    with (
        patch.object(
            coordinator,
            "async_request_art_reconcile",
            new_callable=AsyncMock,
        ) as reconcile,
        patch.object(
            coordinator,
            "async_request_refresh",
            new_callable=AsyncMock,
        ) as ordinary_refresh,
    ):
        await hass.services.async_call(
            DOMAIN, "set_slideshow",
            {"entity_id": ENTITY, "duration_minutes": 60, "shuffle": False,
             "category_id": "MY-C0004"},
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN, "set_slideshow",
            {"entity_id": ENTITY, "duration_minutes": 30, "shuffle": True,
             "category_id": "MY-C0002"},
            blocking=True,
        )

    assert mock_device.async_set_slideshow.await_args_list == [
        call(60, False, "MY-C0004"),
        call(30, True, "MY-C0002"),
    ]
    assert reconcile.await_count == 2
    ordinary_refresh.assert_not_awaited()


async def test_set_slideshow_mutation_error_hides_submitted_data(
    hass, mock_device
):
    duration_minutes = 123
    category_id = "MY-PRIVATE-CATEGORY"
    error = RuntimeError(
        f"private protocol data {duration_minutes} {category_id}"
    )
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    mock_device.async_set_slideshow.side_effect = error
    entry = await _setup(hass, mock_device)
    coordinator = entry.runtime_data

    with (
        patch.object(
            coordinator,
            "async_request_art_reconcile",
            new_callable=AsyncMock,
        ) as reconcile,
        pytest.raises(HomeAssistantError) as raised,
    ):
        await hass.services.async_call(
            DOMAIN,
            "set_slideshow",
            {
                "entity_id": ENTITY,
                "duration_minutes": duration_minutes,
                "shuffle": True,
                "category_id": category_id,
            },
            blocking=True,
        )

    message = str(raised.value)
    assert message == "Failed to configure the slideshow"
    assert "private protocol" not in message
    assert str(duration_minutes) not in message
    assert category_id not in message
    assert raised.value.__cause__ is error
    reconcile.assert_not_awaited()


async def test_change_matte_defaults_to_current_art(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = True
    mock_device.async_get_current_art.return_value = "MY_F0034"
    await _setup(hass, mock_device)
    await hass.services.async_call(
        DOMAIN, "change_matte",
        {"entity_id": ENTITY, "matte_id": "shadowbox_polar"}, blocking=True,
    )
    mock_device.async_change_matte.assert_awaited_once_with(
        "MY_F0034", "shadowbox_polar"
    )


async def test_change_matte_without_art_raises(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False  # no current art known
    await _setup(hass, mock_device)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "change_matte",
            {"entity_id": ENTITY, "matte_id": "none"}, blocking=True,
        )


async def test_set_favourite_service(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = True
    mock_device.async_get_current_art.return_value = "MY_F0034"
    await _setup(hass, mock_device)
    await hass.services.async_call(
        DOMAIN, "set_favourite", {"entity_id": ENTITY}, blocking=True,
    )
    mock_device.async_set_favourite.assert_awaited_once_with("MY_F0034", True)


async def test_set_photo_filter_service(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = True
    mock_device.async_get_current_art.return_value = "MY_F0034"
    await _setup(hass, mock_device)
    await hass.services.async_call(
        DOMAIN, "set_photo_filter",
        {"entity_id": ENTITY, "filter_id": "ink"}, blocking=True,
    )
    mock_device.async_set_photo_filter.assert_awaited_once_with("MY_F0034", "ink")


async def test_play_media_launches_app_with_deep_link(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    await hass.async_block_till_done(wait_background_tasks=True)
    await hass.services.async_call(
        "media_player", "play_media",
        {"entity_id": ENTITY, "media_content_type": "app",
         "media_content_id": "YouTube",
         "extra": {"meta_tag": "v=dQw4w9WgXcQ"}},
        blocking=True,
    )
    mock_device.async_launch_app.assert_awaited_once_with(
        "111299001912", "DEEP_LINK", "v=dQw4w9WgXcQ"
    )


async def test_play_media_rejects_non_app_type(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "media_player", "play_media",
            {"entity_id": ENTITY, "media_content_type": "music",
             "media_content_id": "x"},
            blocking=True,
        )

async def test_upload_art_returns_content_id(hass, mock_device, tmp_path):
    img = tmp_path / "art.jpg"
    img.write_bytes(b"image")
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    await _setup(hass, mock_device)
    result = await hass.services.async_call(
        DOMAIN, "upload_art", {"entity_id": ENTITY, "path": str(img), "show": False},
        blocking=True, return_response=True,
    )
    assert result[ENTITY]["content_id"] == "MY_F9999"

async def test_list_art_returns_records(hass, mock_device):
    mock_device.async_get_content_list = AsyncMock(return_value=[{"content_id": "MY_F0001"}])
    await _setup(hass, mock_device)
    result = await hass.services.async_call(
        DOMAIN, "list_art", {"entity_id": ENTITY}, blocking=True, return_response=True,
    )
    assert result[ENTITY]["artworks"] == [{"content_id": "MY_F0001"}]

async def test_museum_rotation_does_not_interrupt_watching(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    with patch("custom_components.samsung_tv_frame.media_player.fetch_art", new_callable=AsyncMock) as fetch:
        response = await hass.services.async_call(DOMAIN, "rotate_museum_art", {"entity_id": ENTITY}, blocking=True, return_response=True)
    assert response[ENTITY]["status"] == "not_in_art_mode"
    fetch.assert_not_awaited()

async def test_museum_rotation_deletes_only_previous_owned_after_confirm(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = True
    entry = await _setup(hass, mock_device)
    from homeassistant.helpers.storage import Store
    store = Store(hass, 1, f"frame_museum_{entry.entry_id}")
    await store.async_save({"date": "2000-01-01", "owned_ids": ["MY_F0001"]})
    mock_device.async_get_current_art.return_value = "MY_F9999"
    with patch("custom_components.samsung_tv_frame.media_player.fetch_art", new_callable=AsyncMock, return_value=(b"image", {"title": "Test"})):
        result = await hass.services.async_call(DOMAIN, "rotate_museum_art", {"entity_id": ENTITY}, blocking=True, return_response=True)
    assert result[ENTITY]["status"] == "updated"
    mock_device.async_select_art.assert_awaited_with("MY_F9999", True)
    mock_device.async_delete_art.assert_awaited_once_with("MY_F0001")
    assert (await store.async_load())["owned_ids"] == ["MY_F9999"]
    from dataclasses import replace
    entry.runtime_data.async_set_updated_data(replace(entry.runtime_data.data, current_art="MY_F9999"))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.samsung_frame_tv_current_art").attributes["title"] == "Test"

async def test_museum_rotation_keeps_old_art_when_selection_unconfirmed(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = True
    entry = await _setup(hass, mock_device)
    from homeassistant.helpers.storage import Store
    store = Store(hass, 1, f"frame_museum_{entry.entry_id}")
    await store.async_save({"date": "2000-01-01", "owned_ids": ["MY_F0001"]})
    mock_device.async_get_current_art.return_value = "MY_F0001"
    with patch("custom_components.samsung_tv_frame.media_player.fetch_art", new_callable=AsyncMock, return_value=(b"image", {})):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(DOMAIN, "rotate_museum_art", {"entity_id": ENTITY}, blocking=True)
    mock_device.async_delete_art.assert_not_awaited()
    assert set((await store.async_load())["owned_ids"]) == {"MY_F0001", "MY_F9999"}

async def test_museum_rotation_reports_unconfirmed_cleanup(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = True
    entry = await _setup(hass, mock_device)
    from homeassistant.helpers.storage import Store
    store = Store(hass, 1, f"frame_museum_{entry.entry_id}")
    await store.async_save({"date": "2000-01-01", "owned_ids": ["MY_F0001"]})
    mock_device.async_get_current_art.return_value = "MY_F9999"
    mock_device.async_delete_art.return_value = False
    with patch("custom_components.samsung_tv_frame.media_player.fetch_art", new_callable=AsyncMock, return_value=(b"image", {"title": "Test"})):
        result = await hass.services.async_call(DOMAIN, "rotate_museum_art", {"entity_id": ENTITY}, blocking=True, return_response=True)
    assert result[ENTITY]["status"] == "updated_cleanup_pending"
    assert result[ENTITY]["cleanup_pending"] == 1
    assert set((await store.async_load())["owned_ids"]) == {"MY_F0001", "MY_F9999"}

async def test_select_hdmi_service_calls_local_input_channel(hass, mock_device):
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    with patch("custom_components.samsung_tv_frame.media_player.select_input", new_callable=AsyncMock) as select:
        await hass.services.async_call(DOMAIN, "select_hdmi", {"entity_id": ENTITY, "input": "HDMI4"}, blocking=True)
    assert select.await_args.args[-1] == "HDMI4"


async def test_select_hdmi_service_pauses_after_failure(hass, mock_device):
    from custom_components.samsung_tv_frame.input_source import InputSourceError
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = False
    await _setup(hass, mock_device)
    with patch("custom_components.samsung_tv_frame.media_player.select_input", new_callable=AsyncMock, side_effect=InputSourceError("failed")) as select:
        for _ in range(2):
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(DOMAIN, "select_hdmi", {"entity_id": ENTITY, "input": "HDMI4"}, blocking=True)
    assert select.await_count == 1
async def test_museum_rotation_resumes_staged_image(hass, mock_device):
    from homeassistant.helpers.storage import Store
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = True
    entry = await _setup(hass, mock_device)
    store = Store(hass, 1, f"frame_museum_{entry.entry_id}")
    await store.async_save({"date": "2000-01-01", "owned_ids": ["MY_F0001", "MY_F0002"], "staged_id": "MY_F0002", "staged_artwork": {"title": "Staged"}})
    mock_device.async_get_current_art.return_value = "MY_F0002"
    with patch("custom_components.samsung_tv_frame.media_player.fetch_art", new_callable=AsyncMock) as fetch:
        result = await hass.services.async_call(DOMAIN, "rotate_museum_art", {"entity_id": ENTITY}, blocking=True, return_response=True)
    assert result[ENTITY]["status"] == "updated"
    assert result[ENTITY]["artwork"]["title"] == "Staged"
    fetch.assert_not_awaited()
    mock_device.async_upload_art.assert_not_awaited()
    mock_device.async_delete_art.assert_awaited_once_with("MY_F0001")


async def test_museum_rotation_retries_cleanup_same_day(hass, mock_device):
    from homeassistant.helpers.storage import Store
    from homeassistant.util import dt as dt_util
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = True
    entry = await _setup(hass, mock_device)
    store = Store(hass, 1, f"frame_museum_{entry.entry_id}")
    await store.async_save({"date": dt_util.now().date().isoformat(), "owned_ids": ["MY_F0001", "MY_F0002"], "current_id": "MY_F0002", "artwork": {"title": "Current"}})
    mock_device.async_get_current_art.return_value = "MY_F0002"
    with patch("custom_components.samsung_tv_frame.media_player.fetch_art", new_callable=AsyncMock) as fetch:
        result = await hass.services.async_call(DOMAIN, "rotate_museum_art", {"entity_id": ENTITY}, blocking=True, return_response=True)
    assert result[ENTITY]["status"] == "already_updated"
    fetch.assert_not_awaited()
    mock_device.async_delete_art.assert_awaited_once_with("MY_F0001")
    assert (await store.async_load())["owned_ids"] == ["MY_F0002"]


async def test_museum_cleanup_keeps_image_if_user_selects_it(hass, mock_device):
    from homeassistant.helpers.storage import Store
    from homeassistant.util import dt as dt_util
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = True
    entry = await _setup(hass, mock_device)
    store = Store(hass, 1, f"frame_museum_{entry.entry_id}")
    await store.async_save({"date": dt_util.now().date().isoformat(), "owned_ids": ["MY_F0001", "MY_F0002"], "current_id": "MY_F0002"})
    mock_device.async_get_current_art.return_value = "MY_F0001"
    result = await hass.services.async_call(DOMAIN, "rotate_museum_art", {"entity_id": ENTITY}, blocking=True, return_response=True)
    assert result[ENTITY]["cleanup_pending"] == 1
    mock_device.async_delete_art.assert_not_awaited()

async def test_museum_cleanup_migrates_older_saved_state(hass, mock_device):
    from homeassistant.helpers.storage import Store
    from homeassistant.util import dt as dt_util
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = True
    entry = await _setup(hass, mock_device)
    store = Store(hass, 1, f"frame_museum_{entry.entry_id}")
    await store.async_save({"date": dt_util.now().date().isoformat(), "owned_ids": ["MY_F0001", "MY_F0002"]})
    mock_device.async_get_current_art.return_value = "MY_F0002"
    await hass.services.async_call(DOMAIN, "rotate_museum_art", {"entity_id": ENTITY}, blocking=True, return_response=True)
    mock_device.async_delete_art.assert_awaited_once_with("MY_F0001")
    assert (await store.async_load())["current_id"] == "MY_F0002"

async def test_museum_cleanup_never_guesses_when_current_is_unknown(hass, mock_device):
    from homeassistant.helpers.storage import Store
    from homeassistant.util import dt as dt_util
    mock_device.async_device_info.return_value = {"PowerState": "on"}
    mock_device.async_get_artmode.return_value = True
    entry = await _setup(hass, mock_device)
    store = Store(hass, 1, f"frame_museum_{entry.entry_id}")
    await store.async_save({"date": dt_util.now().date().isoformat(), "owned_ids": ["MY_F0001", "MY_F0002"]})
    mock_device.async_get_current_art.return_value = None
    result = await hass.services.async_call(DOMAIN, "rotate_museum_art", {"entity_id": ENTITY}, blocking=True, return_response=True)
    assert result[ENTITY]["cleanup_pending"] == 2
    mock_device.async_delete_art.assert_not_awaited()
