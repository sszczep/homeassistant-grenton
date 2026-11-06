"""Shared UDP reports retain distinct identities and bounded ownership cleanup."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from test_clu_state import make_clu

from custom_components.homeassistant_grenton.domain.api.clu import GrentonCluApi
from custom_components.homeassistant_grenton.domain.api.clu_messages import (
    GrentonCluApiPingRequest,
)
from custom_components.homeassistant_grenton.domain.encryption import GrentonEncryption
from custom_components.homeassistant_grenton.domain.lua_arguments import (
    split_lua_arguments,
)
from custom_components.homeassistant_grenton.state import (
    MISSING_STATE,
    GrentonCluStateVariableKey,
)

ENCRYPTION = GrentonEncryption("AAAAAAAAAAAAAAAAAAAAAA==", "AAAAAAAAAAAAAAAAAAAAAA==")


class Transport:
    """A local fake carries actual encrypted datagrams in both directions."""

    def __init__(self, harness, protocol, address):
        self.harness, self.protocol, self.address = harness, protocol, address
        self.closed = False
        self.sent = []
        protocol.connection_made(self)

    def get_extra_info(self, name):
        return self.address if name == "sockname" else None

    def is_closing(self):
        return self.closed

    def close(self):
        if not self.closed:
            self.closed = True
            asyncio.get_running_loop().call_soon(self.protocol.connection_lost, None)

    def sendto(self, encrypted, peer):
        assert not self.closed
        assert not self.protocol.report_listener, "report listeners never send requests"
        wire = self.harness.api.cipher.decrypt(encrypted).decode()
        _, _, message_id, payload = wire.split(":", 3)
        self.sent.append((message_id, payload))
        self.harness.sent.append((message_id, payload))
        if payload.startswith("SYSTEM:clientRegister("):
            args = split_lua_arguments(
                payload.removeprefix("SYSTEM:clientRegister(")[:-1]
            )
            count = len(split_lua_arguments(args[3][1:-1]))
            result = f"clientReport:{args[2]}:{{{','.join('1' for _ in range(count))}}}"
            if self.harness.register_reply is not None:
                result = self.harness.register_reply
        elif payload.startswith("SYSTEM:clientDestroy("):
            args = split_lua_arguments(
                payload.removeprefix("SYSTEM:clientDestroy(")[:-1]
            )
            if not self.harness.destroy_replies:
                return
            result = args[2]
        elif payload.startswith("SYSTEM:fetchValues("):
            keys = payload.removeprefix("SYSTEM:fetchValues(")[:-1]
            count = len(split_lua_arguments(keys[1:-1]))
            result = f"values:{{{','.join('1' for _ in range(count))}}}"
        elif ":get(" in payload:
            result = "1"
        else:
            result = "true"
        response = f"resp:{peer[0]}:{message_id}:{result}"
        asyncio.get_running_loop().call_soon(
            self.protocol.datagram_received,
            self.harness.api.cipher.encrypt(response.encode()),
            peer,
        )


class Harness:
    def __init__(self, *, subscription_id=1):
        self.api = GrentonCluApi(
            make_clu("clu1"), ENCRYPTION, subscription_id=subscription_id
        )
        self.sockets, self.sent = [], []
        self.destroy_replies = True
        self.register_reply = None
        self.fail_listener = False
        self.pause_listener = None
        self.listener_ports = []

    async def create(self, factory, **kwargs):
        protocol = factory()
        if protocol.report_listener and self.fail_listener:
            raise OSError("listener unavailable")
        port = (
            self.listener_ports.pop(0)
            if protocol.report_listener and self.listener_ports
            else 40000 + len(self.sockets)
        )
        transport = Transport(self, protocol, ("127.0.0.1", port))
        self.sockets.append(transport)
        if protocol.report_listener and self.pause_listener is not None:
            self.pause_listener.set()
            await asyncio.Future()
        return transport, protocol

    def patched(self):
        return patch.object(
            asyncio.get_running_loop(),
            "create_datagram_endpoint",
            side_effect=self.create,
        )

    def report(self, subscription_id, values="1", *, peer=None, protocol=None):
        protocol = protocol or self.api.report_protocol
        wire = f"resp:{self.api.clu.ip}:00000000:clientReport:{subscription_id}:{{{values}}}"
        protocol.datagram_received(
            self.api.cipher.encrypt(wire.encode()),
            peer or (self.api.clu.ip, self.api.clu.port),
        )


def keys(count):
    return [GrentonCluStateVariableKey(f"value{index}") for index in range(count)]


async def flush():
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def test_shared_listener_routes_equal_values_to_distinct_key_groups_and_pings_only_control():
    async def run():
        harness = Harness(subscription_id=69)
        api = harness.api
        requested = keys(2)
        api.large_value_keys = {requested[1]}
        callback = api.on_subscription_report = AsyncMock()
        with harness.patched():
            assert await api.connect()
            assert await api.register_component_states(requested) == [1, 1]
            assert len(harness.sockets) == 2
            assert [group.subscription_id for group in api._groups] == [69, 70]
            assert api.subscription_count == 2
            assert all(
                'clientRegister("127.0.0.1",40001,' in payload
                for _, payload in harness.sent
            )
            for group in api._groups:
                harness.report(group.subscription_id, "12")
            await flush()
            assert callback.await_args_list[0].args == ([requested[0]], [12])
            assert callback.await_args_list[1].args == ([requested[1]], [12])
            before = len(harness.sent)
            assert await api.ping()
            assert len(harness.sent) == before + 1
            assert harness.sent[-1][1] == "checkAlive()"
            assert not harness.sockets[1].sent
            original = api.report_protocol
            ids = [group.subscription_id for group in api._groups]
            old_message_ids = [
                message_id
                for message_id, payload in harness.sent
                if "clientRegister" in payload
            ]
            assert await api.register_component_states(list(reversed(requested))) == [
                1,
                1,
            ]
            assert api.report_protocol is original
            assert [group.subscription_id for group in api._groups] == ids
            assert (
                len(
                    {
                        message_id
                        for message_id, payload in harness.sent
                        if "clientRegister" in payload
                    }
                )
                == len(old_message_ids) * 2
            )
            await api.disconnect()
            assert all(sock.closed for sock in harness.sockets)

    asyncio.run(run())


def test_unknown_retired_bad_count_and_wrong_peer_reports_never_reach_consumers():
    async def run():
        harness = Harness()
        api, requested = harness.api, keys(1)
        callback = api.on_subscription_report = AsyncMock()
        with harness.patched():
            await api.connect()
            await api.register_component_states(requested)
            report = api.report_protocol
            api.health.last_seen = api.health.last_seen_at = None
            harness.report(999)
            harness.report(1, "1,2")
            harness.report(1, "")
            harness.report(1, peer=("192.0.2.200", 1234))
            await flush()
            callback.assert_not_awaited()
            assert api.health.last_seen is None
            assert await api.register_component_states([]) == []
            assert api.report_protocol is report and not report.closed
            count = report._received_report_datagrams
            harness.report(1)
            await flush()
            assert report._received_report_datagrams == count + 1
            assert report._discarded_packets["retired_subscription"] == 1
            callback.assert_not_awaited()
            await api.disconnect()

    asyncio.run(run())


def test_allocator_rolls_over_and_does_not_reuse_retired_ids_before_listener_replacement():
    async def run():
        harness = Harness(subscription_id=65535)
        api, requested = harness.api, keys(31)
        with harness.patched():
            await api.connect()
            await api.register_component_states(requested)
            listener = api.report_protocol
            assert [group.subscription_id for group in api._groups] == [65535, 1]
            await api.register_component_states([])
            await api.register_component_states(requested)
            assert [group.subscription_id for group in api._groups] == [2, 3]
            assert api.report_protocol is listener
            await api.async_set_subscription_id(1)
            await api.register_component_states(requested)
            assert listener.closed
            assert api.report_protocol is not listener
            assert [group.subscription_id for group in api._groups] == [1, 2]
            await api.disconnect()

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad_reply", ["clientReport:1:{}", "clientReport:2:{1}", 'resp:::"private-state"']
)
def test_invalid_registration_never_confirms_group_or_logs_values(bad_reply, caplog):
    async def run():
        harness = Harness()
        harness.register_reply = bad_reply
        with harness.patched():
            await harness.api.connect()
            assert await harness.api.register_component_states(keys(1)) == [
                MISSING_STATE
            ]
            assert harness.api._groups[0].registered
            assert not harness.api._groups[0].confirmed
            assert "private-state" not in caplog.text
            await harness.api.disconnect()

    asyncio.run(run())


def test_listener_creation_failure_and_cancellation_leave_no_bound_report_socket():
    async def run():
        harness = Harness()
        with harness.patched():
            await harness.api.connect()
            harness.fail_listener = True
            assert await harness.api.register_component_states(keys(1)) == [
                MISSING_STATE
            ]
            assert not harness.api._groups and harness.api.report_protocol is None
            harness.fail_listener = False
            harness.pause_listener = asyncio.Event()
            registration = asyncio.create_task(
                harness.api.register_component_states(keys(1))
            )
            await harness.pause_listener.wait()
            registration.cancel()
            with pytest.raises(asyncio.CancelledError):
                await registration
            assert harness.sockets[-1].closed
            assert not harness.api._opening_protocols
            assert harness.api.report_protocol is None
            await harness.api.disconnect()
            assert all(sock.closed for sock in harness.sockets)

    asyncio.run(run())


def test_lost_cleanup_ack_is_bounded_and_disconnect_still_closes_both_ports():
    async def run():
        harness = Harness()
        with harness.patched():
            await harness.api.connect()
            await harness.api.register_component_states(keys(31))
            harness.destroy_replies = False
            with patch(
                "custom_components.homeassistant_grenton.domain.api.clu.SUBSCRIPTION_CLEANUP_TIMEOUT",
                0.01,
            ):
                await asyncio.wait_for(harness.api.disconnect(), 0.2)
            assert all(sock.closed for sock in harness.sockets)
            assert harness.api.transport is harness.api.report_transport is None
            assert not harness.api.protocol and not harness.api.report_protocol

    asyncio.run(run())


def test_queued_normal_request_is_not_sent_after_shutdown_starts():
    async def run():
        harness = Harness()
        api = harness.api
        with harness.patched():
            await api.connect()
            await api._send_lock.acquire()
            request = asyncio.create_task(
                api.protocol.send_request(GrentonCluApiPingRequest())
            )
            await asyncio.sleep(0)
            api._closing = True
            api._send_lock.release()
            assert await request is None
            assert not harness.sent
            api._closing = False
            await api.disconnect()

    asyncio.run(run())


def test_cancelled_shutdown_closes_ports_and_concurrent_disconnect_waits_for_completion():
    async def run():
        harness = Harness()
        api = harness.api
        with harness.patched():
            await api.connect()
            await api.register_component_states(keys(1))
            harness.destroy_replies = False
            first = asyncio.create_task(api.disconnect())
            await flush()
            assert api._closing and not first.done()
            second = asyncio.create_task(api.disconnect())
            await flush()
            assert not second.done()
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            await second
            assert all(sock.closed for sock in harness.sockets)
            assert not api._closing
            assert api.report_protocol is api.protocol is None

    asyncio.run(run())


def test_cancelled_retirement_is_retried_without_reusing_its_id():
    async def run():
        harness = Harness()
        api = harness.api
        requested = keys(1)
        with harness.patched():
            await api.connect()
            await api.register_component_states(requested)
            harness.destroy_replies = False
            task = asyncio.create_task(api.register_component_states([]))
            await flush()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert set(api._retired_groups) == {1}
            assert not api._groups
            assert api.report_protocol.active
            harness.destroy_replies = True
            assert await api.register_component_states(requested) == [1]
            assert not api._retired_groups
            assert api._groups[0].subscription_id == 2
            await api.disconnect()

    asyncio.run(run())


def test_closed_listener_is_replaced_after_old_owned_groups_are_destroyed():
    async def run():
        harness = Harness()
        api = harness.api
        requested = keys(1)
        callback = api.on_subscription_report = AsyncMock()
        with harness.patched():
            await api.connect()
            await api.register_component_states(requested)
            old_listener, old_control = api.report_protocol, api.protocol
            old_listener.close()
            assert await api.register_component_states(requested) == [1]
            assert api.protocol is old_control
            assert api.report_protocol is not old_listener
            assert len(harness.sockets) == 3
            assert "clientDestroy" in harness.sent[-2][1]
            harness.report(1, "99", protocol=old_listener)
            await flush()
            callback.assert_not_awaited()
            harness.report(1, "42")
            await flush()
            assert callback.await_args.args == (requested, [42])
            await api.disconnect()

    asyncio.run(run())


def test_queued_renewal_runs_before_second_slow_read_batch():
    async def run():
        harness = Harness()
        api = harness.api
        requested = keys(1)
        with harness.patched():
            await api.connect()
            await api.register_component_states(requested)
            started, release = asyncio.Event(), asyncio.Event()
            operations = []
            original = api.protocol.send_request

            async def send(request):
                operation = "fetch" if "fetchValues" in request.payload else "register"
                operations.append(operation)
                if len(operations) == 1:
                    started.set()
                    await release.wait()
                return await original(request)

            with patch.object(api.protocol, "send_request", side_effect=send):
                slow = asyncio.create_task(api.fetch_component_states(keys(31)))
                await started.wait()
                renewal = asyncio.create_task(api.register_component_states(requested))
                await flush()
                assert api._registration_waiters == 1
                release.set()
                assert await slow == [1] * 31
                assert await renewal == [1]
            assert operations == ["fetch", "register", "fetch"]
            await api.disconnect()

    asyncio.run(run())


def test_rebase_back_to_previous_id_rejects_os_reuse_of_its_old_report_port():
    async def run():
        harness = Harness()
        api = harness.api
        requested = keys(1)
        with harness.patched():
            await api.connect()
            await api.register_component_states(requested)
            old_address = api._report_address
            await api.async_set_subscription_id(2)
            await api.register_component_states(requested)
            harness.listener_ports = [old_address[1], old_address[1], 45000]
            await api.async_set_subscription_id(1)
            assert await api.register_component_states(requested) == [1]
            assert api._report_address == ("127.0.0.1", 45000)
            assert api._groups[0].subscription_id == 1
            assert all(
                sock.closed for sock in harness.sockets if sock.address == old_address
            )
            await api.disconnect()

    asyncio.run(run())


def test_listener_port_reuse_retries_are_bounded_and_history_survives_reconnect():
    async def run():
        harness = Harness()
        api = harness.api
        with harness.patched():
            await api.connect()
            await api.register_component_states(keys(1))
            old_address = api._report_address
            await api.disconnect()
            await api.connect()
            harness.listener_ports = [old_address[1]] * 32
            assert await api.register_component_states(keys(1)) == [MISSING_STATE]
            assert len(harness.listener_ports) >= 16
            assert api.report_protocol is None
            assert not api._groups
            assert all(
                sock.closed for sock in harness.sockets if sock.address == old_address
            )
            await api.disconnect()

    asyncio.run(run())


def test_return_to_old_base_after_unconfirmed_rebase_still_uses_exact_requested_base():
    async def run():
        harness = Harness()
        api = harness.api
        requested = keys(1)
        with harness.patched():
            await api.connect()
            await api.register_component_states(requested)
            old_listener = api.report_protocol
            await api.async_set_subscription_id(69)
            harness.destroy_replies = False
            with patch(
                "custom_components.homeassistant_grenton.domain.api.clu.SUBSCRIPTION_CLEANUP_TIMEOUT",
                0.01,
            ):
                assert await api.register_component_states(requested) == [MISSING_STATE]
            await api.async_set_subscription_id(1)
            harness.destroy_replies = True
            assert await api.register_component_states(requested) == [1]
            assert api._groups[0].subscription_id == 1
            assert api.report_protocol is not old_listener
            await api.disconnect()

    asyncio.run(run())
