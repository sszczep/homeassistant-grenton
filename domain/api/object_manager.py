"""API client for Grenton Object Manager."""

import logging
from typing import Any
import aiohttp
import io
import zipfile
import json

_LOGGER = logging.getLogger(__name__)


class GrentonObjectManagerApi:
    """Handles communication with Grenton Object Manager API."""
    
    def __init__(self, base_url: str):
        """Initialize the Object Manager API client.
        
        Args:
            base_url: Base URL of the Grenton Object Manager (e.g., 'http://192.168.1.100:9998')
        """
        self.base_url = base_url.rstrip('/')
        self.session: aiohttp.ClientSession | None = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb): # type: ignore
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
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
        if not self.session:
            raise RuntimeError("API client not initialized. Use async context manager or call connect() first.")
        
        url = f"{self.base_url}/api/v1/interface/hash/{pin}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    raw_data = await response.read()
                    return self._parse_interface_zip(raw_data)
                elif response.status == 401:
                    raise GrentonObjectManagerAuthError("Authentication failed: Invalid PIN")
                else:
                    raise GrentonObjectManagerConnectionError(
                        f"Failed to fetch interface: HTTP {response.status}"
                    )
        except aiohttp.ClientError as e:
            raise GrentonObjectManagerConnectionError(f"Connection error: {e}")
    
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
            with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
                _LOGGER.debug("Fetched and opened interface ZIP successfully")
                _LOGGER.debug("ZIP contents: %s", z.namelist())
                
                if "mygrenton/data.json" not in z.namelist():
                    raise GrentonObjectManagerDataError(
                        "Invalid interface ZIP: missing mygrenton/data.json"
                    )
                
                with z.open("mygrenton/data.json") as f:
                    text = f.read().decode("utf-8")
                    return json.loads(text)
        
        except zipfile.BadZipFile:
            raise GrentonObjectManagerDataError("Invalid ZIP file format")
        except json.JSONDecodeError:
            raise GrentonObjectManagerDataError("Invalid JSON data in interface file")
        except Exception as e:
            raise GrentonObjectManagerDataError(f"Failed to parse interface data: {e}")


class GrentonObjectManagerAuthError(Exception):
    """Raised when authentication with Grenton Object Manager fails."""
    pass


class GrentonObjectManagerConnectionError(Exception):
    """Raised when connection to Grenton Object Manager fails."""
    pass


class GrentonObjectManagerDataError(Exception):
    """Raised when interface data from Grenton Object Manager is invalid."""
    pass
