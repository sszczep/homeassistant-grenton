"""A missed renewal reply must not replace healthy subscription ownership."""

import asyncio
from unittest.mock import AsyncMock, patch

from test_clu_scripts import make_entry, make_hass
from test_clu_shared_listener import Harness, flush, keys
from test_clu_state import coordinator, make_clu

from custom_components.homeassistant_grenton.domain.lua_arguments import (
    split_lua_arguments,
)
from custom_components.homeassistant_grenton.domain.state_object import (
    GrentonVariableValueObject,
)
from custom_components.homeassistant_grenton.state import (
    MISSING_STATE,
    GrentonCluStateAttributeKey,
)


def test_lost_renewal_reply_keeps_reports_and_group_ids_until_next_success(
    monkeypatch, caplog
):
    async def run():
        h = Harness(subscription_id=69)
        api = h.api
        requested = keys(61)
        requested[0] = GrentonCluStateAttributeKey("DIN1", "0")
        with h.patched():
            assert await api.connect()
            assert await api.register_component_states(requested) == [1] * 61
            control, listener = api.protocol, api.report_protocol
            owned_groups = api._groups.copy()
            owned_sockets = h.sockets.copy()
            callback = api.on_subscription_report = AsyncMock()
            receive = control.datagram_received
            drop_one = True

            def receive_after_loss(data, peer):
                nonlocal drop_one
                body = api.cipher.decrypt(data).decode().split(":", 3)[3]
                if drop_one and body.startswith("clientReport:"):
                    drop_one = False
                    return
                receive(data, peer)

            control.datagram_received = receive_after_loss
            control._response_timeout = 0.03
            renewal = asyncio.create_task(api.register_component_states(requested))
            await flush()
            assert not drop_one
            # A later ping reply explains activity during a missed renewal.
            assert await api.ping()
            private_value = "private-renewal-value"
            h.report(
                owned_groups[0].subscription_id,
                ",".join([f'"{private_value}"'] * 30),
            )
            await flush()
            callback.assert_awaited_once_with(
                owned_groups[0].keys, [private_value] * 30
            )

            values = await renewal
            assert values == [MISSING_STATE] * 30 + [1] * 31
            assert api.health.request_timeouts == 1
            assert api.health.connected
            assert api.subscription_count == 3
            assert api._groups == owned_groups
            assert all(group.confirmed for group in owned_groups)
            assert api.protocol is control and api.report_protocol is listener
            assert h.sockets == owned_sockets
            assert not any("clientDestroy" in payload for _, payload in h.sent)
            assert "other_replies_during_wait=1" in caplog.text
            assert "subscription_id=69" in caplog.text
            assert (
                "targets=['DIN1.0', 'var:value1', 'var:value2', '+27 more']"
                in caplog.text
            )
            assert private_value not in caplog.text
            assert not control._pending

            assert await api.register_component_states(requested) == [1] * 61
            assert api._groups == owned_groups
            registrations = [
                (
                    message_id,
                    split_lua_arguments(payload[len("SYSTEM:clientRegister(") : -1]),
                )
                for message_id, payload in h.sent
                if payload.startswith("SYSTEM:clientRegister(")
            ]
            assert len(registrations) == 9
            assert len({message_id for message_id, _ in registrations}) == 9
            assert [args[2] for _, args in registrations] == ["69", "70", "71"] * 3
            assert api.health.request_timeouts == 1
            await api.disconnect()
            assert all(socket.closed for socket in owned_sockets)

    monkeypatch.setattr(
        "custom_components.homeassistant_grenton.domain.api.clu.MIN_SEND_INTERVAL", 0
    )
    asyncio.run(run())


def test_missing_renewal_snapshot_retains_cache_until_freshness_limit(tmp_path):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu1")])
        state = GrentonVariableValueObject("clu1", "", "value")
        coord.register_component_state(state)
        key = coord._state_key(state)
        api = coord._apis["clu1"]
        api.health.record_response()
        api.register_component_states = AsyncMock(return_value=[42])
        with patch(
            "custom_components.homeassistant_grenton.coordinator.monotonic"
        ) as now:
            now.return_value = 100
            assert await coord._send_register("clu1") == {key}
            assert coord.get_value_for_component(state) == 42
            api.register_component_states.return_value = [MISSING_STATE]
            now.return_value = 145
            assert await coord._send_register("clu1") == set()
            assert coord.get_value_for_component(state) == 42
            assert coord.state.get_value_for_component(state) == 42
            assert api.register_component_states.await_count == 2
            now.return_value = 189.9
            assert coord.is_state_fresh(state)
            now.return_value = 190
            assert not coord.is_state_fresh(state)
            assert coord.get_value_for_component(state) is None
            assert coord.state.get_value_for_component(state) == 42
            api.register_component_states.return_value = [43]
            now.return_value = 191
            assert await coord._send_register("clu1") == {key}
            assert coord.is_state_fresh(state)
            assert coord.get_value_for_component(state) == 43
            assert api.register_component_states.await_count == 3
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())
