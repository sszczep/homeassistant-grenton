"""Per-CLU subscription IDs persist independently and apply without reloads."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from probatio import Invalid
from test_clu_scripts import make_entry, make_hass
from test_clu_variables import configure_manager, set_options
from test_integration_configuration import fields

from custom_components.homeassistant_grenton.clu_settings import (
    subscription_id,
    validate_subscription_id,
)


@pytest.mark.parametrize(
    "value",
    [None, True, False, 0, -1, 1.5, 65536, "69", float("nan"), float("inf")],
)
def test_invalid_subscription_ids_are_rejected_and_saved_values_fall_back(value):
    with pytest.raises(Invalid):
        validate_subscription_id(value)
    assert (
        subscription_id(
            {"clu_read_settings": {"clu1": {"subscription_id": value}}}, "clu1"
        )
        == 1
    )


@pytest.mark.parametrize("value", [1, 69, 69.0, 65535])
def test_valid_subscription_ids_are_normalized_to_integers(value):
    assert validate_subscription_id(value) == value
    assert type(validate_subscription_id(value)) is int


@pytest.mark.parametrize(
    "options",
    [{}, {"clu_read_settings": []}, {"clu_read_settings": {"clu1": []}}],
)
def test_missing_or_malformed_settings_keep_the_existing_id(options):
    assert subscription_id(options, "clu1") == 1


def test_subscription_ids_are_resolved_independently_for_each_clu():
    options = {
        "clu_read_settings": {
            "clu1": {"subscription_id": 69, "slow_read_interval": 120},
            "clu2": {"subscription_id": 70},
        }
    }
    assert subscription_id(options, "clu1") == 69
    assert subscription_id(options, "clu2") == 70
    assert subscription_id(options, "clu3") == 1


async def open_settings(tmp_path, options=None, runtime=None):
    entry = make_entry(
        interface={
            "clus": [{"id": "clu1", "name": "Main"}, {"id": "clu2", "name": "Gate"}]
        }
    )
    set_options(entry, options or {})
    hass = await make_hass(tmp_path, [entry])
    if runtime is not None:
        entry.runtime_data = SimpleNamespace(coordinator=runtime)
    manager = configure_manager(hass, entry)
    menu = await manager.async_init(entry.entry_id)
    form = await manager.async_configure(
        menu["flow_id"], {"next_step_id": "clu_read_settings"}
    )
    form = await manager.async_configure(form["flow_id"], {"clu_id": "clu1"})
    form = await manager.async_configure(
        form["flow_id"], {"next_step_id": "clu_read_interval"}
    )
    return hass, entry, manager, form


def test_native_clu_popup_defaults_to_one_and_persists_while_unloaded(tmp_path):
    async def run():
        original = {
            "entities": {"temperature": {"read_mode": "slow"}},
            "clu_read_settings": {
                "clu1": {"slow_read_interval": 120, "keep": True},
                "clu2": {"slow_read_interval": 5, "subscription_id": 70},
            },
        }
        hass, entry, manager, form = await open_settings(tmp_path, original)
        selectors = fields(form)
        assert selectors["subscription_id"]["default"] == 1
        number = selectors["subscription_id"]["selector"]["number"]
        assert number["min"] == 1
        assert number["max"] == 65535
        assert number["step"] == 1
        assert number["mode"] == "box"
        result = await manager.async_configure(
            form["flow_id"], {"slow_read_interval": 120, "subscription_id": 69}
        )
        assert result["type"] == "create_entry"
        assert dict(entry.options) == {
            **original,
            "clu_read_settings": {
                **original["clu_read_settings"],
                "clu1": {
                    "slow_read_interval": 120,
                    "subscription_id": 69,
                    "keep": True,
                },
            },
        }
        hass.config_entries.async_schedule_reload.assert_not_called()
        reopened = await manager.async_init(entry.entry_id)
        reopened = await manager.async_configure(
            reopened["flow_id"], {"next_step_id": "clu_read_settings"}
        )
        reopened = await manager.async_configure(
            reopened["flow_id"], {"clu_id": "clu2"}
        )
        reopened = await manager.async_configure(
            reopened["flow_id"], {"next_step_id": "clu_read_interval"}
        )
        assert fields(reopened)["subscription_id"]["default"] == 70
        manager.async_abort(reopened["flow_id"])
        await hass.async_stop()

    asyncio.run(run())


def test_id_change_applies_only_to_the_selected_clu_without_restarting_timer(tmp_path):
    async def run():
        runtime = SimpleNamespace(
            async_set_subscription_id=AsyncMock(),
            async_set_slow_read_interval=AsyncMock(),
        )
        hass, entry, manager, form = await open_settings(tmp_path, runtime=runtime)
        result = await manager.async_configure(
            form["flow_id"], {"slow_read_interval": 60, "subscription_id": 69}
        )
        assert result["type"] == "create_entry"
        runtime.async_set_subscription_id.assert_awaited_once_with("clu1", 69)
        runtime.async_set_slow_read_interval.assert_not_awaited()
        assert entry.options["clu_read_settings"]["clu1"]["subscription_id"] == 69
        hass.config_entries.async_schedule_reload.assert_not_called()
        await hass.async_stop()

    asyncio.run(run())


def test_saving_unchanged_settings_reconciles_subscription_without_restarting_timer(
    tmp_path,
):
    async def run():
        runtime = SimpleNamespace(
            async_set_subscription_id=AsyncMock(),
            async_set_slow_read_interval=AsyncMock(),
        )
        options = {"clu_read_settings": {"clu1": {"subscription_id": 69}}}
        hass, _, manager, form = await open_settings(tmp_path, options, runtime)
        result = await manager.async_configure(
            form["flow_id"], {"slow_read_interval": 60, "subscription_id": 69}
        )
        assert result["type"] == "create_entry"
        runtime.async_set_subscription_id.assert_awaited_once_with("clu1", 69)
        runtime.async_set_slow_read_interval.assert_not_awaited()
        await hass.async_stop()

    asyncio.run(run())


def test_all_settings_validate_before_any_runtime_or_persisted_changes(tmp_path):
    async def run():
        runtime = SimpleNamespace(
            async_set_subscription_id=AsyncMock(),
            async_set_slow_read_interval=AsyncMock(),
        )
        hass, entry, manager, form = await open_settings(tmp_path, runtime=runtime)
        result = await manager.async_configure(
            form["flow_id"], {"slow_read_interval": 60.5, "subscription_id": 69.5}
        )
        assert result["errors"] == {
            "slow_read_interval": "invalid_configuration",
            "subscription_id": "invalid_configuration",
        }
        assert entry.options == {}
        runtime.async_set_subscription_id.assert_not_awaited()
        runtime.async_set_slow_read_interval.assert_not_awaited()
        manager.async_abort(result["flow_id"])
        await hass.async_stop()

    asyncio.run(run())


def test_unchanged_saved_id_repairs_runtime_drift_after_an_interrupted_save(tmp_path):
    async def run():
        runtime = SimpleNamespace(
            subscription_id=7,
            async_set_slow_read_interval=AsyncMock(),
        )

        async def reconcile(clu_id, identifier):
            assert clu_id == "clu1"
            runtime.subscription_id = identifier

        runtime.async_set_subscription_id = AsyncMock(side_effect=reconcile)
        options = {"clu_read_settings": {"clu1": {"subscription_id": 1}}}
        hass, entry, manager, form = await open_settings(tmp_path, options, runtime)
        result = await manager.async_configure(
            form["flow_id"], {"slow_read_interval": 60, "subscription_id": 1}
        )
        assert result["type"] == "create_entry"
        assert runtime.subscription_id == 1
        assert entry.options["clu_read_settings"]["clu1"]["subscription_id"] == 1
        runtime.async_set_subscription_id.assert_awaited_once_with("clu1", 1)
        runtime.async_set_slow_read_interval.assert_not_awaited()
        await hass.async_stop()

    asyncio.run(run())


def test_runtime_failure_keeps_existing_options_and_polling_timer(tmp_path):
    async def run():
        runtime = SimpleNamespace(
            async_set_subscription_id=AsyncMock(
                side_effect=HomeAssistantError("offline")
            ),
            async_set_slow_read_interval=AsyncMock(),
        )
        original = {"clu_read_settings": {"clu1": {"subscription_id": 1}}}
        hass, entry, manager, form = await open_settings(tmp_path, original, runtime)
        result = await manager.async_configure(
            form["flow_id"], {"slow_read_interval": 120, "subscription_id": 69}
        )
        assert result["type"] == "form"
        assert result["errors"] == {"base": "cannot_apply_configuration"}
        assert entry.options == original
        runtime.async_set_slow_read_interval.assert_not_awaited()
        assert fields(result)["subscription_id"]["default"] == 69
        manager.async_abort(result["flow_id"])
        await hass.async_stop()

    asyncio.run(run())


def test_old_polling_only_submissions_retain_the_saved_subscription_id(tmp_path):
    async def run():
        runtime = SimpleNamespace(
            async_set_subscription_id=AsyncMock(),
            async_set_slow_read_interval=AsyncMock(),
        )
        options = {"clu_read_settings": {"clu1": {"subscription_id": 69}}}
        hass, entry, manager, form = await open_settings(tmp_path, options, runtime)
        result = await manager.async_configure(
            form["flow_id"], {"slow_read_interval": 120}
        )
        assert result["type"] == "create_entry"
        assert entry.options["clu_read_settings"]["clu1"]["subscription_id"] == 69
        runtime.async_set_subscription_id.assert_awaited_once_with("clu1", 69)
        runtime.async_set_slow_read_interval.assert_awaited_once_with("clu1", 120)
        await hass.async_stop()

    asyncio.run(run())
