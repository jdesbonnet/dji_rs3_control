"""Synchronous convenience wrapper for the async RS3 client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from .client import RS3Client
from .models import Pose, RateCommand, TelemetrySnapshot, VelocityCommand, Waypoint


class RS3:
    """Blocking convenience API for scripts that do not want asyncio."""

    def __init__(self, device_identifier: str, **kwargs: object) -> None:
        self._device_identifier = device_identifier
        self._kwargs = kwargs

    def _run(self, action: Callable[[RS3Client], Awaitable[Any]]) -> Any:
        async def wrapped() -> Any:
            client = RS3Client(self._device_identifier, **self._kwargs)
            await client.connect()
            try:
                return await action(client)
            finally:
                await client.disconnect()

        return asyncio.run(wrapped())

    def connect(self) -> None:
        raise NotImplementedError("The sync wrapper manages its own connection per operation")

    def disconnect(self) -> None:
        raise NotImplementedError("The sync wrapper manages its own connection per operation")

    def recenter(self) -> None:
        self._run(lambda client: client.recenter())

    def sleep(self) -> None:
        self._run(lambda client: client.sleep())

    def wake(self) -> None:
        self._run(lambda client: client.wake())

    def request_state(self, **kwargs: object) -> TelemetrySnapshot:
        return self._run(lambda client: client.request_state(**kwargs))

    def move_velocity(self, command: VelocityCommand) -> None:
        self._run(lambda client: client.move_velocity(command))

    def move_rate(self, command: RateCommand, **kwargs: object) -> None:
        self._run(lambda client: client.move_rate(command, **kwargs))

    def go_to(self, pose: Pose, **kwargs: object) -> None:
        self._run(lambda client: client.go_to(pose, **kwargs))

    def run_track(self, waypoints: list[Waypoint], **kwargs: object) -> None:
        self._run(lambda client: client.run_track(waypoints, **kwargs))


__all__ = ["RS3"]
