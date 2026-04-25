"""Bleak-backed BLE transport for DJI RS3 devices."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from bleak import BleakClient

from ..errors import ConnectionError


NotificationCallback = Callable[[bytes], Awaitable[None] | None]


class BleakRS3Transport:
    """Thin BLE transport wrapper."""

    NOTIFY_CHAR = "0000fff4-0000-1000-8000-00805f9b34fb"
    WRITE_CHAR = "0000fff5-0000-1000-8000-00805f9b34fb"

    def __init__(self, device_identifier: str, *, timeout: float = 15.0) -> None:
        self.device_identifier = device_identifier
        self.timeout = timeout
        self._client: BleakClient | None = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        self._client = BleakClient(self.device_identifier, timeout=self.timeout)
        try:
            await self._client.connect()
        except Exception as exc:  # pragma: no cover
            raise ConnectionError(str(exc)) from exc

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def start_notifications(self, callback: NotificationCallback) -> None:
        client = self._require_client()

        async def dispatch(_sender: object, data: bytearray) -> None:
            result = callback(bytes(data))
            if result is not None:
                await result

        await client.start_notify(self.NOTIFY_CHAR, dispatch)

    async def stop_notifications(self) -> None:
        client = self._require_client()
        await client.stop_notify(self.NOTIFY_CHAR)

    async def write_frame(self, frame: bytes) -> None:
        client = self._require_client()
        await client.write_gatt_char(self.WRITE_CHAR, frame, response=False)

    def _require_client(self) -> BleakClient:
        if self._client is None:
            raise ConnectionError("transport is not connected")
        return self._client
