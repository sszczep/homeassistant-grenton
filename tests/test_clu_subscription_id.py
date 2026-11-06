"""Group IDs route shared-listener reports; outer request IDs remain unique."""

import asyncio
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from probatio import Invalid
from test_clu_scripts import make_entry, make_hass
from test_clu_state import coordinator, make_clu
from test_clu_variables import set_options

from custom_components.homeassistant_grenton.domain.api.clu import GrentonCluApi
from custom_components.homeassistant_grenton.domain.api.clu_messages import (
    GrentonCluApiClientDestroyRequest,
    GrentonCluApiClientRegisterRequest,
)
from custom_components.homeassistant_grenton.domain.encryption import GrentonEncryption
from custom_components.homeassistant_grenton.state import (
    MISSING_STATE,
    GrentonCluStateVariableKey,
)

ENCRYPTION = GrentonEncryption("AAAAAAAAAAAAAAAAAAAAAA==", "AAAAAAAAAAAAAAAAAAAAAA==")


class SubscriptionHarness:
    """Replace only UDP I/O while retaining API grouping, cleanup and locking."""

    def __init__(self, *, subscription_id=1, clu_id="clu1"):
        self.api = GrentonCluApi(
            make_clu(clu_id), ENCRYPTION, subscription_id=subscription_id
        )
        self.requests = []
        self.destroy_results, self.register_results = deque(), deque()
        self.control = Mock()
        self.control.is_closing.return_value = False
        self.api.transport = self.control
        self.api.protocol = SimpleNamespace(
            closed=False,
            active=True,
            transport=self.control,
            send_request=AsyncMock(side_effect=self.send),
        )
        self.listeners = []
        self.api._ensure_report_listener = AsyncMock(side_effect=self.ensure_listener)

    async def ensure_listener(self):
        if self.api.report_protocol is None or not self.api.report_protocol.active:
            listener = Mock()
            listener.is_closing.return_value = False
            self.listeners.append(listener)
            self.api.report_transport = listener
            self.api.report_protocol = SimpleNamespace(
                closed=False, active=True, transport=listener
            )
            self.api._report_address = ("127.0.0.1", 40000 + len(self.listeners))
            self.api._used_subscription_ids = set(self.api._retired_groups)
            self.api._next_subscription_id = self.api.subscription_id
        return True

    async def send(self, request):
        self.requests.append(request)
        if isinstance(request, GrentonCluApiClientDestroyRequest):
            outcome = (
                self.destroy_results.popleft()
                if self.destroy_results
                else request.subscription_id
            )
        elif isinstance(request, GrentonCluApiClientRegisterRequest):
            outcome = self.register_results.popleft() if self.register_results else True
        else:
            raise TypeError(type(request).__name__)
        if callable(outcome):
            outcome = await outcome(request)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome is None:
            return None
        if isinstance(request, GrentonCluApiClientDestroyRequest):
            payload = str(outcome)
        else:
            payload = (
                outcome
                if isinstance(outcome, str)
                else f"clientReport:{request.subscription_id}:{{{','.join('1' for _ in request.keys)}}}"
            )
        return f"resp:192.0.2.1:{request.msg_id}:{payload}"

    @property
    def registrations(self):
        return [
            r
            for r in self.requests
            if isinstance(r, GrentonCluApiClientRegisterRequest)
        ]

    @property
    def destructions(self):
        return [
            r for r in self.requests if isinstance(r, GrentonCluApiClientDestroyRequest)
        ]


def keys(count=1):
    return [GrentonCluStateVariableKey(f"value{i}") for i in range(count)]


@pytest.mark.parametrize("subscription_id", [1, 69, 65535, 69.0])
def test_initial_registration_and_renewal_keep_group_id_and_use_fresh_outer_ids(
    subscription_id,
):
    async def run():
        h = SubscriptionHarness(subscription_id=subscription_id)
        assert type(h.api.subscription_id) is int
        assert await h.api.register_component_states(keys()) == [1]
        group, listener = h.api._groups[0], h.api.report_transport
        assert await h.api.register_component_states(keys()) == [1]
        assert h.api._groups == [group] and group.subscription_id == subscription_id
        assert h.api.report_transport is listener and len(h.listeners) == 1
        assert [r.subscription_id for r in h.registrations] == [
            subscription_id,
            subscription_id,
        ]
        assert len({r.msg_id for r in h.registrations}) == 2
        assert not h.destructions
        assert all(
            r.report_ip == "127.0.0.1" and r.report_port == 40001
            for r in h.registrations
        )
        await h.api.disconnect()

    asyncio.run(run())


def test_multiple_groups_have_distinct_ids_on_one_report_port():
    async def run():
        h = SubscriptionHarness(subscription_id=69)
        assert await h.api.register_component_states(keys(65)) == [1] * 65
        groups = h.api._groups.copy()
        assert [len(g.keys) for g in groups] == [30, 30, 5]
        assert [g.subscription_id for g in groups] == [69, 70, 71]
        assert {r.report_port for r in h.registrations} == {40001}
        await h.api.register_component_states(list(reversed(keys(65))))
        assert h.api._groups == groups
        assert [r.subscription_id for r in h.registrations[-3:]] == [69, 70, 71]
        assert len(h.listeners) == 1 and len({r.msg_id for r in h.registrations}) == 6
        await h.api.disconnect()

    asyncio.run(run())


def test_changing_base_id_destroys_previous_group_before_registering_new_id():
    async def run():
        h = SubscriptionHarness(subscription_id=69)
        await h.api.register_component_states(keys())
        listener = h.api.report_transport
        await h.api.async_set_subscription_id(70.0)
        assert h.api.subscription_id == 70 and len(h.requests) == 1
        assert await h.api.register_component_states(keys()) == [1]
        assert [type(r) for r in h.requests] == [
            GrentonCluApiClientRegisterRequest,
            GrentonCluApiClientDestroyRequest,
            GrentonCluApiClientRegisterRequest,
        ]
        assert [r.subscription_id for r in h.requests] == [69, 69, 70]
        assert all(
            r.report_ip == "127.0.0.1" and r.report_port == 40001 for r in h.requests
        )
        assert h.api.report_transport is listener and h.api.transport is h.control
        await h.api.disconnect()

    asyncio.run(run())


@pytest.mark.parametrize("handover", [False, True])
def test_wrong_report_id_never_updates_state_and_retries_attempted_id(handover, caplog):
    async def run():
        h = SubscriptionHarness(subscription_id=1 if handover else 69)
        if handover:
            await h.api.register_component_states(keys())
            await h.api.async_set_subscription_id(69)
        h.register_results.append('clientReport:1:{"private-state"}')
        assert await h.api.register_component_states(keys()) == [MISSING_STATE]
        group = h.api._groups[0]
        assert group.registered and not group.confirmed and group.subscription_id == 69
        assert await h.api.register_component_states(keys()) == [1]
        assert h.api._groups == [group] and group.confirmed
        assert [r.subscription_id for r in h.registrations[-2:]] == [69, 69]
        assert h.registrations[-1].msg_id != h.registrations[-2].msg_id
        assert len(h.destructions) == int(handover)
        assert "private-state" not in caplog.text
        assert "Unexpected subscription ID" in caplog.text
        await h.api.disconnect()

    asyncio.run(run())


@pytest.mark.parametrize(
    "destroy_result", [None, 999, "private-state", ConnectionError("closed")]
)
def test_failed_destroy_retries_retired_id_before_creating_new_group(
    destroy_result, caplog
):
    async def run():
        h = SubscriptionHarness(subscription_id=69)
        await h.api.register_component_states(keys())
        await h.api.async_set_subscription_id(70)
        h.destroy_results.append(destroy_result)
        assert await h.api.register_component_states(keys()) == [MISSING_STATE]
        assert len(h.registrations) == 1
        assert set(h.api._retired_groups) == {69}
        assert await h.api.register_component_states(keys()) == [1]
        assert [r.subscription_id for r in h.destructions] == [69, 69]
        assert [r.subscription_id for r in h.registrations] == [69, 70]
        assert not h.api._retired_groups and h.api._groups[0].subscription_id == 70
        assert "private-state" not in caplog.text
        await h.api.disconnect()

    asyncio.run(run())


def test_timeout_after_handover_retries_new_id_without_a_second_destroy():
    async def run():
        h = SubscriptionHarness(subscription_id=69)
        await h.api.register_component_states(keys())
        await h.api.async_set_subscription_id(70)
        h.register_results.append(None)
        assert await h.api.register_component_states(keys()) == [MISSING_STATE]
        group = h.api._groups[0]
        assert group.registered and not group.confirmed and group.subscription_id == 70
        assert await h.api.register_component_states(keys()) == [1]
        assert h.api._groups == [group]
        assert [r.subscription_id for r in h.registrations] == [69, 70, 70]
        assert [r.subscription_id for r in h.destructions] == [69]
        await h.api.disconnect()

    asyncio.run(run())


def test_cancellation_while_destroying_keeps_retired_identity_for_retry():
    async def run():
        h = SubscriptionHarness(subscription_id=69)
        await h.api.register_component_states(keys())
        await h.api.async_set_subscription_id(70)
        h.destroy_results.append(asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await h.api.register_component_states(keys())
        assert not h.api._registration_lock.locked()
        assert set(h.api._retired_groups) == {69}
        assert await h.api.register_component_states(keys()) == [1]
        assert [r.subscription_id for r in h.destructions] == [69, 69]
        await h.api.disconnect()

    asyncio.run(run())


def test_cancelled_new_registration_is_tracked_for_later_cleanup():
    async def run():
        h = SubscriptionHarness(subscription_id=69)
        await h.api.register_component_states(keys())
        await h.api.async_set_subscription_id(70)
        h.register_results.append(asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await h.api.register_component_states(keys())
        group = h.api._groups[0]
        assert group.registered and group.subscription_id == 70
        assert await h.api.register_component_states(keys()) == [1]
        assert h.api._groups == [group]
        assert [r.subscription_id for r in h.destructions] == [69]
        await h.api.disconnect()
        assert [r.subscription_id for r in h.destructions] == [69, 70]

    asyncio.run(run())


def test_initial_registration_timeout_is_cleaned_before_configuration_change():
    async def run():
        h = SubscriptionHarness(subscription_id=69)
        h.register_results.append(None)
        assert await h.api.register_component_states(keys()) == [MISSING_STATE]
        await h.api.async_set_subscription_id(70)
        assert await h.api.register_component_states(keys()) == [1]
        assert [r.subscription_id for r in h.requests] == [69, 69, 70]
        await h.api.disconnect()

    asyncio.run(run())


def test_setting_waits_for_inflight_registration_before_changing_desired_id():
    async def run():
        h = SubscriptionHarness(subscription_id=69)
        started, release = asyncio.Event(), asyncio.Event()

        async def registration(request):
            started.set()
            await release.wait()
            return True

        h.register_results.append(registration)
        pending = asyncio.create_task(h.api.register_component_states(keys()))
        await started.wait()
        changed = asyncio.create_task(h.api.async_set_subscription_id(70))
        await asyncio.sleep(0)
        assert not changed.done() and h.api.subscription_id == 69
        release.set()
        assert await pending == [1]
        await changed
        assert await h.api.register_component_states(keys()) == [1]
        assert [r.subscription_id for r in h.requests] == [69, 69, 70]
        await h.api.disconnect()

    asyncio.run(run())


@pytest.mark.parametrize("subscription_id", [0, -1, 65536, 2.5, "69", True, None])
def test_invalid_constructor_and_runtime_id_cannot_mutate_state(subscription_id):
    async def run():
        with pytest.raises(Invalid):
            SubscriptionHarness(subscription_id=subscription_id)
        h = SubscriptionHarness(subscription_id=69)
        with pytest.raises(Invalid):
            await h.api.async_set_subscription_id(subscription_id)
        assert h.api.subscription_id == 69 and not h.requests
        await h.api.disconnect()

    asyncio.run(run())


def test_changing_one_clu_does_not_touch_another_clu_groups_or_ports():
    async def run():
        first, second = (
            SubscriptionHarness(subscription_id=69),
            SubscriptionHarness(subscription_id=10, clu_id="clu2"),
        )
        await first.api.register_component_states(keys())
        await second.api.register_component_states(keys())
        group, listener = second.api._groups[0], second.api.report_transport
        await first.api.async_set_subscription_id(70)
        await first.api.register_component_states(keys())
        assert second.api._groups == [group] and group.subscription_id == 10
        assert second.api.report_transport is listener and len(second.requests) == 1
        await first.api.disconnect()
        await second.api.disconnect()

    asyncio.run(run())


def test_coordinator_changes_only_target_clu_under_its_read_lock(tmp_path):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu1"), make_clu("clu2")])
        first, second = coord._apis["clu1"], coord._apis["clu2"]

        async def set_id(value):
            assert coord._read_locks["clu1"].locked()
            assert not coord._read_locks["clu2"].locked()
            assert value == 69

        first.async_set_subscription_id = AsyncMock(side_effect=set_id)
        second.async_set_subscription_id = AsyncMock()

        async def read(clu_id, required_keys=None):
            assert clu_id == "clu1"
            assert coord._read_locks[clu_id].locked()
            first.async_set_subscription_id.assert_awaited_once_with(69)
            return set()

        coord._read_registered_states = AsyncMock(side_effect=read)
        await coord.async_set_subscription_id("clu1", 69)
        coord._read_registered_states.assert_awaited_once()
        second.async_set_subscription_id.assert_not_awaited()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_coordinator_startup_uses_each_saved_clu_id_and_default_for_older_settings(
    tmp_path,
):
    async def run():
        entry = make_entry()
        set_options(
            entry,
            {
                "clu_read_settings": {
                    "clu1": {"subscription_id": 69, "slow_read_interval": 5},
                    "clu2": {"subscription_id": 10.0, "slow_read_interval": 90},
                    "clu3": {"slow_read_interval": 120},
                }
            },
        )
        hass = await make_hass(tmp_path, [entry])
        clus = [make_clu("clu1"), make_clu("clu2"), make_clu("clu3")]
        coord = coordinator(hass, entry, clus)
        assert {clu_id: api.subscription_id for clu_id, api in coord._apis.items()} == {
            "clu1": 69,
            "clu2": 10,
            "clu3": 1,
        }
        assert all(type(api.subscription_id) is int for api in coord._apis.values())
        assert coord._slow_read_intervals == {"clu1": 5, "clu2": 90, "clu3": 120}
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())
