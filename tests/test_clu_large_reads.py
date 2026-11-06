"""Large replies run alone without serializing ordinary CLU requests."""

import asyncio
from types import SimpleNamespace

import pytest
from test_clu_protocol_lifecycle import Socket
from test_clu_shared_listener import ENCRYPTION
from test_clu_state import make_clu

from custom_components.homeassistant_grenton.domain.api.clu import (
    GrentonCluApi,
    GrentonCluApiProtocol,
    _SubscriptionGroup,
)
from custom_components.homeassistant_grenton.domain.api.clu_messages import (
    GrentonCluApiActionRequest,
    GrentonCluApiClientDestroyRequest,
    GrentonCluApiClientRegisterRequest,
    GrentonCluApiFetchValuesRequest,
    GrentonCluApiGetValueRequest,
    GrentonCluApiPingRequest,
)
from custom_components.homeassistant_grenton.state import (
    GrentonCluStateAttributeKey,
    GrentonCluStateVariableKey,
    MissingState,
)


@pytest.fixture(autouse=True)
def no_pacing_delay(monkeypatch):
    # Real send pacing is covered by protocol lifecycle tests. These tests
    # advance tasks without sleeping while deliberately withholding replies.
    monkeypatch.setattr(
        "custom_components.homeassistant_grenton.domain.api.clu.MIN_SEND_INTERVAL", 0
    )


async def flush():
    for _ in range(5):
        await asyncio.sleep(0)


class Harness:
    def __init__(self):
        self.api = GrentonCluApi(make_clu("clu1"), ENCRYPTION)
        self.api.cipher = SimpleNamespace(
            encrypt=lambda data: data, decrypt=lambda data: data
        )
        self.large = GrentonCluStateAttributeKey("THERM1", "9")
        self.small = GrentonCluStateVariableKey("ordinary")
        self.api.large_value_keys.add(self.large)
        self.replace_protocol()

    def replace_protocol(self):
        self.protocol = GrentonCluApiProtocol(self.api)
        self.socket = Socket(self.protocol, reply=False)
        self.api.protocol, self.api.transport = self.protocol, self.socket
        return self.protocol

    async def wait_sent(self, count):
        for _ in range(20):
            if len(self.socket.sent) >= count:
                break
            await asyncio.sleep(0)
        assert len(self.socket.sent) == count

    def reply(self, message_id, payload="pong"):
        self.protocol._process_response(
            f"resp:{self.api.clu.ip}:{message_id}:{payload}"
        )


def ordinary_request(kind, key):
    if kind == "ping":
        return GrentonCluApiPingRequest("00000004")
    if kind == "action":
        return GrentonCluApiActionRequest("Example()", "00000004")
    if kind == "register":
        return GrentonCluApiClientRegisterRequest([key], 0, "00000004")
    if kind == "destroy":
        return GrentonCluApiClientDestroyRequest(1, "00000004")
    return GrentonCluApiFetchValuesRequest([key], "00000004")


@pytest.mark.parametrize("kind", ["ping", "action", "register", "destroy", "fetch"])
def test_large_read_drains_inflight_requests_and_blocks_every_later_request(kind):
    async def run():
        h = Harness()
        protocol = h.protocol
        first = asyncio.create_task(
            protocol.send_request(GrentonCluApiPingRequest("00000001"))
        )
        second = asyncio.create_task(
            protocol.send_request(GrentonCluApiActionRequest("Example()", "00000002"))
        )
        await h.wait_sent(2)
        assert len(protocol._pending) == 2  # Ordinary requests still overlap.
        large = asyncio.create_task(h.api.fetch_component_states([h.large]))
        await flush()
        later = asyncio.create_task(
            protocol.send_request(ordinary_request(kind, h.small))
        )
        await flush()
        assert len(h.socket.sent) == 2
        h.reply("00000001")
        await flush()
        assert len(h.socket.sent) == 2
        h.reply("00000002")
        await h.wait_sent(3)
        large_id = h.socket.sent[2][0].split(":", 3)[2]
        assert h.socket.sent[2][0].endswith(":THERM1:get(9)")
        assert set(protocol._pending) == {large_id}
        h.reply(large_id, "schedule")
        await h.wait_sent(4)
        assert set(protocol._pending) == {"00000004"}
        h.reply("00000004")
        results = await asyncio.gather(first, second, large, later)
        assert all(results) and results[2] == ["schedule"]
        await h.api.disconnect()

    asyncio.run(run())


def test_cancelling_a_queued_large_read_reopens_gate_without_waiting_for_older_reply():
    async def run():
        h = Harness()
        protocol = h.protocol
        first = asyncio.create_task(
            protocol.send_request(GrentonCluApiPingRequest("00000001"))
        )
        await h.wait_sent(1)
        large = asyncio.create_task(h.api.fetch_component_states([h.large]))
        await flush()
        later = asyncio.create_task(
            protocol.send_request(GrentonCluApiPingRequest("00000003"))
        )
        await flush()
        assert len(h.socket.sent) == 1
        large.cancel()
        with pytest.raises(asyncio.CancelledError):
            await large
        await h.wait_sent(2)
        assert set(protocol._pending) == {"00000001", "00000003"}
        h.reply("00000001")
        h.reply("00000003")
        await asyncio.gather(first, later)
        await h.api.disconnect()

    asyncio.run(run())


@pytest.mark.parametrize("exit_kind", ["reply", "timeout", "cancel", "connection_lost"])
def test_large_read_releases_exclusivity_on_every_wait_exit(exit_kind):
    async def run():
        h = Harness()
        protocol = h.protocol
        if exit_kind == "timeout":
            protocol._response_timeout = 0.03
        large = asyncio.create_task(
            protocol.send_request(GrentonCluApiGetValueRequest(h.large, "00000001"))
        )
        await h.wait_sent(1)
        later = asyncio.create_task(
            protocol.send_request(GrentonCluApiPingRequest("00000002"))
        )
        await flush()
        assert len(h.socket.sent) == 1
        if exit_kind == "reply":
            h.reply("00000001", "schedule")
            assert await large
        elif exit_kind == "timeout":
            assert await large is None
        elif exit_kind == "cancel":
            large.cancel()
            with pytest.raises(asyncio.CancelledError):
                await large
        else:
            protocol.connection_lost(None)
            with pytest.raises(ConnectionError):
                await large
            assert await later is None
            h.replace_protocol()
            later = asyncio.create_task(
                h.protocol.send_request(GrentonCluApiPingRequest("00000002"))
            )
        await h.wait_sent(1 if exit_kind == "connection_lost" else 2)
        h.reply("00000002")
        assert await later
        await h.api.disconnect()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["send", "encryption"])
def test_large_read_releases_exclusivity_on_failure_before_waiting_for_reply(failure):
    async def run():
        h = Harness()
        send = h.socket.sendto
        if failure == "send":

            def fail_send(*args):
                raise OSError("send failure")

            h.socket.sendto = fail_send
        else:
            h.api.cipher.encrypt = lambda data: None
        assert (
            await h.protocol.send_request(GrentonCluApiGetValueRequest(h.large)) is None
        )
        h.socket.sendto = send
        h.api.cipher.encrypt = lambda data: data
        later = asyncio.create_task(
            h.protocol.send_request(GrentonCluApiPingRequest("00000002"))
        )
        await h.wait_sent(1)
        h.reply("00000002")
        assert await later
        await h.api.disconnect()

    asyncio.run(run())


def test_exclusive_large_fetch_keeps_other_clus_independent():
    async def run():
        first, other = Harness(), Harness()
        large = asyncio.create_task(first.api.fetch_component_states([first.large]))
        await first.wait_sent(1)
        assert first.socket.sent[0][0].endswith(":THERM1:get(9)")
        ping = asyncio.create_task(
            other.protocol.send_request(GrentonCluApiPingRequest("00000002"))
        )
        await other.wait_sent(1)
        other.reply("00000002")
        assert await ping
        assert not large.done()
        message_id = first.socket.sent[0][0].split(":", 3)[2]
        first.reply(message_id, "schedule")
        assert await large == ["schedule"]
        await asyncio.gather(first.api.disconnect(), other.api.disconnect())

    asyncio.run(run())


def test_large_variable_keeps_fetch_values_and_exclusive_read_protection():
    async def run():
        h = Harness()
        key = GrentonCluStateVariableKey("large_text")
        h.api.large_value_keys = {key}
        read = asyncio.create_task(h.api.fetch_component_states([key]))
        await h.wait_sent(1)
        assert h.socket.sent[0][0].endswith(':SYSTEM:fetchValues({"large_text"})')
        ping = asyncio.create_task(h.api.ping())
        await flush()
        assert len(h.socket.sent) == 1
        message_id = h.socket.sent[0][0].split(":", 3)[2]
        h.reply(message_id, 'values:{"  large variable, text  "}')
        assert await read == ["  large variable, text  "]
        await h.wait_sent(2)
        h.reply(h.socket.sent[1][0].split(":", 3)[2])
        assert await ping
        await h.api.disconnect()

    asyncio.run(run())


def test_shutdown_is_bounded_while_large_read_holds_the_gate(monkeypatch):
    async def run():
        h = Harness()
        h.api._groups = [
            _SubscriptionGroup(
                [h.small],
                1,
                registered=True,
                confirmed=True,
                report_address=("127.0.0.1", 40001),
            )
        ]
        large = asyncio.create_task(h.api.fetch_component_states([h.large]))
        await h.wait_sent(1)
        await asyncio.wait_for(h.api.disconnect(), 0.5)
        assert len(h.socket.sent) == 1  # Cleanup did not overlap the large read.
        assert h.socket.closed and h.api.transport is None
        assert all(isinstance(value, MissingState) for value in await large)
        assert not h.protocol._pending

    monkeypatch.setattr(
        "custom_components.homeassistant_grenton.domain.api.clu.SUBSCRIPTION_CLEANUP_TIMEOUT",
        0.02,
    )
    asyncio.run(run())


@pytest.mark.parametrize("large", [False, True])
def test_read_timeout_identifies_large_data_and_only_safe_target_names(caplog, large):
    async def run():
        h = Harness()
        h.protocol._response_timeout = 0
        keys = (
            [h.large]
            if large
            else [GrentonCluStateVariableKey(f"value{i}") for i in range(8)]
        )
        assert (
            await h.protocol.send_request(
                GrentonCluApiGetValueRequest(keys[0])
                if large
                else GrentonCluApiFetchValuesRequest(keys)
            )
            is None
        )
        message = next(
            record.getMessage()
            for record in caplog.records
            if "Request timeout" in record.getMessage()
        )
        assert f"large={large}" in message
        assert (
            "THERM1.9" in message
            if large
            else "var:value0" in message and "+5 more" in message
        )
        assert "queued=" in message and "targets=" in message
        await h.api.disconnect()

    asyncio.run(run())
