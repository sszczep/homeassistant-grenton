"""Renewals keep their deadlines and can run between bounded slow-read batches."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from test_clu_scripts import make_entry, make_hass
from test_clu_state import coordinator, make_clu

from custom_components.homeassistant_grenton.domain.api.clu_health import (
    KEEPALIVE_INTERVAL,
    REGISTRATION_INTERVAL,
)
from custom_components.homeassistant_grenton.domain.state_object import (
    GrentonVariableValueObject,
)
from custom_components.homeassistant_grenton.state import MISSING_STATE

COORDINATOR = "custom_components.homeassistant_grenton.coordinator"


async def tick():
    future = asyncio.get_running_loop().create_future()
    asyncio.get_running_loop().call_soon(future.set_result, None)
    await future


async def fixture(tmp_path, *, count=1, slow_count=0):
    entry = make_entry()
    hass = await make_hass(tmp_path, [entry])
    coord = coordinator(
        hass, entry, [make_clu(f"clu{index + 1}") for index in range(count)]
    )
    for api in coord._apis.values():
        api.connect = AsyncMock(return_value=True)
        api.ping = AsyncMock(return_value=True)
        api.disconnect = AsyncMock()
    states = [
        GrentonVariableValueObject("clu1", "", f"slow{index}")
        for index in range(slow_count)
    ]
    for state in states:
        coord.register_component_state(state, read_mode="slow")
    return hass, coord, states


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    async def sleep(self, delay):
        self.waits.append(delay)
        self.now += delay
        await tick()


@pytest.mark.parametrize("register", [False, True])
@pytest.mark.parametrize("overrun", [False, True])
def test_periodic_starts_follow_deadlines_and_skip_missed_ticks(
    tmp_path, register, overrun
):
    async def run():
        hass, coord, _ = await fixture(tmp_path)
        coord.register_component_state(GrentonVariableValueObject("clu1", "", "live"))
        interval = REGISTRATION_INTERVAL if register else KEEPALIVE_INTERVAL
        clock, starts = Clock(), []

        async def work(clu_id):
            starts.append(clock.now)
            if len(starts) == 3:
                raise asyncio.CancelledError
            clock.now += interval * 2 + 3 if overrun else 3

        setattr(coord, "_send_register" if register else "_send_ping", work)
        with (
            patch(f"{COORDINATOR}.monotonic", side_effect=lambda: clock.now),
            patch("asyncio.sleep", side_effect=clock.sleep),
            pytest.raises(asyncio.CancelledError),
        ):
            await coord._periodic_clu_loop("clu1", interval, register=register)
        spacing = interval * 3 if overrun else interval
        assert starts == [interval, interval + spacing, interval + spacing * 2]
        assert all(wait > 0 for wait in clock.waits)
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_slow_polling_uses_the_same_deadline_policy_after_read_failures(tmp_path):
    async def run():
        hass, coord, _ = await fixture(tmp_path)
        clock, starts = Clock(), []
        coord._slow_read_intervals["clu1"] = 60

        async def work(clu_id):
            starts.append(clock.now)
            if len(starts) == 3:
                raise asyncio.CancelledError
            clock.now += 7
            raise RuntimeError("temporary read failure")

        coord._send_slow_poll = work
        with (
            patch(f"{COORDINATOR}.monotonic", side_effect=lambda: clock.now),
            patch("asyncio.sleep", side_effect=clock.sleep),
            pytest.raises(asyncio.CancelledError),
        ):
            await coord._slow_poll_loop("clu1")
        assert starts == [60, 120, 180]
        assert clock.waits == [60, 53, 53]
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("register", [False, True])
def test_a_stalled_clu_does_not_hold_another_clu_timer(tmp_path, register):
    async def run():
        hass, coord, _ = await fixture(tmp_path, count=2)
        for clu_id in coord._apis:
            coord.register_component_state(GrentonVariableValueObject(clu_id, "", "live"))
        clock, calls, healthy = Clock(), {"clu1": 0, "clu2": 0}, asyncio.Event()

        async def work(clu_id):
            calls[clu_id] += 1
            if clu_id == "clu1":
                await asyncio.Future()
            if calls[clu_id] >= 3:
                healthy.set()

        setattr(coord, "_send_register" if register else "_send_ping", work)
        with (
            patch(f"{COORDINATOR}.monotonic", side_effect=lambda: clock.now),
            patch("asyncio.sleep", side_effect=clock.sleep),
        ):
            task = asyncio.create_task(coord._register_loop() if register else coord._ping_loop())
            try:
                await asyncio.wait_for(healthy.wait(), 0.5)
                assert calls["clu1"] == 1
                assert calls["clu2"] >= 3
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_queued_renewal_runs_between_slow_read_batches_without_losing_values(tmp_path):
    async def run():
        hass, coord, states = await fixture(tmp_path, slow_count=65)
        api = coord._apis["clu1"]
        live = GrentonVariableValueObject("clu1", "", "live")
        coord.register_component_state(live)
        entered, release, order = asyncio.Event(), asyncio.Event(), []

        async def read(keys):
            order.append(("poll", len(keys)))
            if len(order) == 1:
                entered.set()
                await release.wait()
            return [21] * len(keys)

        async def renew(keys, **kwargs):
            order.append(("renew", len(keys)))
            return [1] * len(keys)

        api.poll_component_states = AsyncMock(side_effect=read)
        api.register_component_states = AsyncMock(side_effect=renew)
        poll = asyncio.create_task(coord._send_slow_poll("clu1"))
        await entered.wait()
        renewal = asyncio.create_task(coord._send_register("clu1"))
        await tick()
        assert coord._registration_waiters["clu1"] == 1
        assert not coord._registrations_idle["clu1"].is_set()
        release.set()
        received, _ = await asyncio.gather(poll, renewal)
        assert order == [("poll", 30), ("renew", 1), ("poll", 30), ("poll", 5)]
        assert received == {coord._state_key(state) for state in states}
        assert all(coord.state.get_value_for_component(state) == 21 for state in states)
        assert coord._registrations_idle["clu1"].is_set()
        assert coord._registration_waiters["clu1"] == 0
        assert not coord._read_locks["clu1"].locked()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_cancelled_queued_renewal_releases_slow_reads_and_priority_flag(tmp_path):
    async def run():
        hass, coord, _ = await fixture(tmp_path, slow_count=31)
        entered, release = asyncio.Event(), asyncio.Event()
        api = coord._apis["clu1"]

        async def read(keys):
            if api.poll_component_states.await_count == 1:
                entered.set()
                await release.wait()
            return [21] * len(keys)

        api.poll_component_states = AsyncMock(side_effect=read)
        poll = asyncio.create_task(coord._send_slow_poll("clu1"))
        await entered.wait()
        renewal = asyncio.create_task(coord._send_register("clu1"))
        await tick()
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)
        assert coord._registration_waiters["clu1"] == 0
        assert coord._registrations_idle["clu1"].is_set()
        release.set()
        assert len(await poll) == 31
        assert api.poll_component_states.await_count == 2
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_slow_reads_wait_for_every_already_queued_renewal(tmp_path):
    async def run():
        hass, coord, _ = await fixture(tmp_path, slow_count=1)
        coord.register_component_state(GrentonVariableValueObject("clu1", "", "live"))
        api = coord._apis["clu1"]
        first_started, second_started = asyncio.Event(), asyncio.Event()
        release_first, release_second = asyncio.Event(), asyncio.Event()

        async def renew(keys, **kwargs):
            if api.register_component_states.await_count == 1:
                first_started.set()
                await release_first.wait()
            else:
                second_started.set()
                await release_second.wait()
            return [1] * len(keys)

        api.register_component_states = AsyncMock(side_effect=renew)
        api.poll_component_states = AsyncMock(return_value=[21])
        await coord._read_locks["clu1"].acquire()
        first = asyncio.create_task(coord._send_register("clu1"))
        second = asyncio.create_task(coord._send_register("clu1"))
        await tick()
        poll = asyncio.create_task(coord._send_slow_poll("clu1"))
        await tick()
        assert coord._registration_waiters["clu1"] == 2
        coord._read_locks["clu1"].release()
        await first_started.wait()
        release_first.set()
        await second_started.wait()
        assert coord._registration_waiters["clu1"] == 1
        assert not coord._registrations_idle["clu1"].is_set()
        api.poll_component_states.assert_not_awaited()
        release_second.set()
        await asyncio.gather(first, second, poll)
        api.poll_component_states.assert_awaited_once()
        assert coord._registrations_idle["clu1"].is_set()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_completed_batches_are_published_before_a_later_batch_is_cancelled(tmp_path):
    async def run():
        hass, coord, states = await fixture(tmp_path, slow_count=31)
        api = coord._apis["clu1"]
        entered = asyncio.Event()
        coord.async_set_updated_data = Mock()

        async def read(keys):
            if len(keys) == 1:
                entered.set()
                await asyncio.Future()
            return [21] * len(keys)

        api.poll_component_states = AsyncMock(side_effect=read)
        poll = asyncio.create_task(coord._send_slow_poll("clu1"))
        await entered.wait()
        assert all(coord.state.get_value_for_component(state) == 21 for state in states[:30])
        assert all(coord.last_polled(state) is not None for state in states[:30])
        assert coord.last_polled(states[-1]) is None
        coord.async_set_updated_data.assert_called()
        poll.cancel()
        await asyncio.gather(poll, return_exceptions=True)
        assert not coord._read_locks["clu1"].locked()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_shutdown_discards_an_inflight_batch_and_prevents_any_later_read(tmp_path):
    async def run():
        hass, coord, states = await fixture(tmp_path, slow_count=65)
        api = coord._apis["clu1"]
        coord.async_set_updated_data = Mock()

        async def read(keys):
            if api.poll_component_states.await_count == 2:
                coord._stopping = True
            return [21] * len(keys)

        api.poll_component_states = AsyncMock(side_effect=read)
        assert await coord._send_slow_poll("clu1") == set()
        assert api.poll_component_states.await_count == 2
        assert all(coord.state.get_value_for_component(state) == 21 for state in states[:30])
        assert all(coord.last_polled(state) is None for state in states[30:])
        coord.async_set_updated_data.assert_called_once()
        assert not coord._read_locks["clu1"].locked()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_large_conditional_reads_recheck_eligibility_before_every_send(tmp_path):
    async def run():
        hass, coord, _ = await fixture(tmp_path)
        api, enabled, requested = coord._apis["clu1"], True, []
        states = [GrentonVariableValueObject("clu1", "", name) for name in ("mode", "schedule1", "schedule2")]
        coord.register_component_state(states[0], read_mode="slow")
        for state in states[1:]:
            coord.register_component_state(state, read_mode="slow", large_value=True, poll_condition=lambda: enabled)

        async def read(keys):
            nonlocal enabled
            requested.extend(key.name for key in keys)
            if keys[0].name == "schedule1":
                enabled = False
            return [21] * len(keys)

        api.poll_component_states = AsyncMock(side_effect=read)
        assert len(await coord._send_slow_poll("clu1")) == 2
        assert requested == ["mode", "schedule1"]
        assert coord.last_polled(states[2]) is None
        # Explicit readback still bypasses paused schedule polling once.
        await coord._send_slow_poll("clu1", {coord._state_key(states[2])})
        assert requested == ["mode", "schedule1", "schedule2"]
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_failure_in_one_batch_does_not_erase_other_batches(tmp_path):
    async def run():
        hass, coord, states = await fixture(tmp_path, slow_count=31)
        api = coord._apis["clu1"]
        api.poll_component_states = AsyncMock(side_effect=[[MISSING_STATE] * 30, [22]])
        received = await coord._send_slow_poll("clu1")
        assert received == {coord._state_key(states[-1])}
        assert coord.last_polled(states[0]) is None
        assert coord.state.get_value_for_component(states[-1]) == 22
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_startup_has_live_keepalive_and_renewal_workers_before_slow_reads(tmp_path):
    async def run():
        hass, coord, _ = await fixture(tmp_path, slow_count=1)
        live = GrentonVariableValueObject("clu1", "", "live")
        coord.register_component_state(live)
        api = coord._apis["clu1"]
        api.register_component_states = AsyncMock(return_value=[1])
        ping_started, renewal_started = asyncio.Event(), asyncio.Event()

        async def ping_worker():
            ping_started.set()
            await asyncio.Future()

        async def renewal_worker():
            renewal_started.set()
            await asyncio.Future()

        async def startup_read(clu_id, **kwargs):
            await asyncio.wait_for(ping_started.wait(), 0.5)
            await asyncio.wait_for(renewal_started.wait(), 0.5)
            return set()

        coord._ping_loop, coord._register_loop = ping_worker, renewal_worker
        coord._send_slow_poll = AsyncMock(side_effect=startup_read)
        await coord.async_setup()
        workers = [coord._ping_task, coord._register_task]
        await coord.async_shutdown()
        assert all(worker.cancelled() for worker in workers)
        assert not coord._slow_tasks
        await hass.async_stop()

    asyncio.run(run())
