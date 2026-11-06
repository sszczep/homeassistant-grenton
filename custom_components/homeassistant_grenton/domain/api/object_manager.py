"""API client for Grenton Object Manager."""

import asyncio
import io
import json
import zipfile
import zlib
from typing import Any, Self

import aiohttp

INTERFACE_REQUEST_TIMEOUT = 30


class GrentonObjectManagerApi:
    """Handles communication with Grenton Object Manager API."""

    def __init__(self, base_url: str):
        """Initialize the Object Manager API client.

        Args:
            base_url: Base URL of the Grenton Object Manager (e.g., 'http://192.168.1.100:9998')
        """
        self.base_url = base_url.rstrip("/")
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        if self.session is not None and not self.session.closed:
            raise RuntimeError("Object Manager API client is already open")
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=INTERFACE_REQUEST_TIMEOUT)
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):  # type: ignore
        """Async context manager exit."""
        session, self.session = self.session, None
        if session is not None:
            await session.close()

    async def fetch_mobile_interface(self, pin: str) -> dict[str, Any]:
        """Fetch mobile interface data from Grenton Object Manager.

        Args:
            pin: PIN code for authentication

        Returns:
            Parsed mobile interface data as a dictionary

        Raises:
            GrentonObjectManagerAuthError: If authentication fails
            GrentonObjectManagerConnectionError: If connection fails
            GrentonObjectManagerDataError: If data is invalid
        """
        session = self.session
        if session is None or session.closed:
            raise RuntimeError(
                "Use the Object Manager API client as an async context manager"
            )

        url = f"{self.base_url}/api/v1/interface/hash/{pin}"

        try:
            async with session.get(url) as response:
                if response.status == 401:
                    raise GrentonObjectManagerAuthError(
                        "Authentication failed: Invalid PIN"
                    )
                if response.status != 200:
                    raise GrentonObjectManagerConnectionError(
                        f"Failed to fetch interface: HTTP {response.status}"
                    )
                raw_data = await response.read()
            # ZIP decompression and JSON parsing must not block HA's event loop.
            return await asyncio.to_thread(self._parse_interface_zip, raw_data)
        except TimeoutError as error:
            raise GrentonObjectManagerConnectionError(
                "Object Manager request timed out"
            ) from error
        except aiohttp.ClientError as error:
            # aiohttp errors can include the request URL, which contains the PIN.
            raise GrentonObjectManagerConnectionError(
                "Object Manager request failed"
            ) from error

    def _parse_interface_zip(self, zip_data: bytes) -> dict[str, Any]:
        """Parse the interface ZIP file and extract mobile interface data.

        Args:
            zip_data: Raw ZIP file data

        Returns:
            Parsed interface data

        Raises:
            GrentonObjectManagerDataError: If ZIP parsing fails or data is invalid
        """
        try:
            with zipfile.ZipFile(io.BytesIO(zip_data)) as archive:
                if "mygrenton/data.json" not in archive.namelist():
                    raise GrentonObjectManagerDataError(
                        "Invalid interface ZIP: missing mygrenton/data.json"
                    )

                with archive.open("mygrenton/data.json") as interface_file:
                    data = json.load(interface_file)
                if not isinstance(data, dict):
                    raise GrentonObjectManagerDataError(
                        "Interface data must be a JSON object"
                    )
                return data

        except zipfile.BadZipFile as error:
            raise GrentonObjectManagerDataError("Invalid ZIP file format") from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise GrentonObjectManagerDataError(
                "Invalid JSON data in interface file"
            ) from error
        except (
            OSError,
            RuntimeError,
            NotImplementedError,
            EOFError,
            zlib.error,
        ) as error:
            raise GrentonObjectManagerDataError(
                "Failed to read interface ZIP"
            ) from error


class GrentonObjectManagerAuthError(Exception):
    """Raised when authentication with Grenton Object Manager fails."""


class GrentonObjectManagerConnectionError(Exception):
    """Raised when connection to Grenton Object Manager fails."""


class GrentonObjectManagerDataError(Exception):
    """Raised when interface data from Grenton Object Manager is invalid."""
