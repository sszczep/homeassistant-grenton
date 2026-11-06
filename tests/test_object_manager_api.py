"""Object Manager import stays bounded, typed and safe to close on failures."""

import asyncio
import io
import json
import threading
import zipfile
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest

from custom_components.homeassistant_grenton.domain.api.object_manager import (
    INTERFACE_REQUEST_TIMEOUT,
    GrentonObjectManagerApi,
    GrentonObjectManagerAuthError,
    GrentonObjectManagerConnectionError,
    GrentonObjectManagerDataError,
)


def interface_zip(data, *, name="mygrenton/data.json", compression=zipfile.ZIP_STORED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        archive.writestr(name, data)
    return buffer.getvalue()


def corrupted_compressed_zip():
    raw = bytearray(interface_zip('{"name":"House"}', compression=zipfile.ZIP_DEFLATED))
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        member = archive.getinfo("mygrenton/data.json")
        data_offset = (
            member.header_offset
            + 30
            + len(member.filename.encode())
            + len(member.extra)
        )
    raw[data_offset] = (
        0xFF  # Invalid DEFLATE block, while the ZIP directory stays valid.
    )
    return bytes(raw)


def http_session(status=200, data=b""):
    response = AsyncMock(status=status)
    response.read.return_value = data
    context = AsyncMock()
    context.__aenter__.return_value = response
    session = Mock(closed=False, close=AsyncMock())
    session.get.return_value = context
    return session, response


def test_context_closes_session_and_import_parses_outside_event_loop():
    async def run():
        data = {"name": "House", "clus": []}
        session, response = http_session(data=interface_zip(json.dumps(data)))
        api = GrentonObjectManagerApi("http://192.0.2.1:9998/")
        parse = api._parse_interface_zip
        threads = []

        def parser(raw):
            threads.append(threading.get_ident())
            return parse(raw)

        with (
            patch("aiohttp.ClientSession", return_value=session) as factory,
            patch.object(api, "_parse_interface_zip", side_effect=parser),
        ):
            async with api:
                assert await api.fetch_mobile_interface("1234") == data
                assert threads == [threads[0]] and threads[0] != threading.get_ident()
                assert (
                    factory.call_args.kwargs["timeout"].total
                    == INTERFACE_REQUEST_TIMEOUT
                )
                session.get.assert_called_once_with(
                    "http://192.0.2.1:9998/api/v1/interface/hash/1234"
                )
                response.read.assert_awaited_once()
            session.close.assert_awaited_once()
            assert api.session is None
            with pytest.raises(RuntimeError, match="context manager"):
                await api.fetch_mobile_interface("1234")

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure", [TimeoutError(), aiohttp.ClientConnectionError("URL includes PIN")]
)
def test_request_failures_become_connection_errors_and_close_session(failure):
    async def run():
        session, _ = http_session()
        session.get.return_value.__aenter__.side_effect = failure
        api = GrentonObjectManagerApi("http://192.0.2.1:9998")
        with (
            patch("aiohttp.ClientSession", return_value=session),
            pytest.raises(GrentonObjectManagerConnectionError) as caught,
        ):
            async with api:
                await api.fetch_mobile_interface("1234")
        assert "PIN" not in str(caught.value)
        assert api.session is None
        session.close.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,error",
    [(401, GrentonObjectManagerAuthError), (500, GrentonObjectManagerConnectionError)],
)
def test_http_failures_keep_error_type_and_do_not_parse_body(status, error):
    async def run():
        session, response = http_session(status=status)
        with patch("aiohttp.ClientSession", return_value=session), pytest.raises(error):
            async with GrentonObjectManagerApi("http://192.0.2.1:9998") as api:
                await api.fetch_mobile_interface("1234")
        response.read.assert_not_awaited()
        session.close.assert_awaited_once()

    asyncio.run(run())


def test_cancelled_import_closes_session_and_nested_context_cannot_leak_it():
    async def run():
        session, response = http_session()
        started = asyncio.Event()

        async def read():
            started.set()
            await asyncio.Future()

        response.read.side_effect = read
        api = GrentonObjectManagerApi("http://192.0.2.1:9998")

        async def fetch():
            async with api:
                with pytest.raises(RuntimeError, match="already open"):
                    await api.__aenter__()
                await api.fetch_mobile_interface("1234")

        with patch("aiohttp.ClientSession", return_value=session) as factory:
            task = asyncio.create_task(fetch())
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            factory.assert_called_once()
        session.close.assert_awaited_once()
        assert api.session is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "raw",
    [
        b"not a ZIP",
        interface_zip("{}", name="wrong.json"),
        interface_zip("[]"),
        interface_zip("null"),
        interface_zip("{"),
        interface_zip(b"\xff"),
        corrupted_compressed_zip(),
    ],
)
def test_invalid_archives_and_non_object_json_raise_data_errors(raw):
    api = GrentonObjectManagerApi("http://192.0.2.1:9998")
    with pytest.raises(GrentonObjectManagerDataError):
        api._parse_interface_zip(raw)
