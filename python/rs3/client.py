"""Async high-level RS3 client."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from typing import TextIO

from .models import Pose, TelemetrySnapshot, VelocityCommand, Waypoint
from .protocol import (
    APP_INIT_COMMANDS,
    APP_POLL_PAYLOADS,
    Command,
    build_keepalive_0410_frame,
    build_recenter_frame,
    build_sleep_frame,
    build_track_frame,
    build_velocity_frame,
    build_wake_frame,
    decode_0466_fields,
    decode_0d02_fields,
    iter_embedded_frames,
    parse_frame,
)
from .protocol.commands import build_command_frame
from .protocol.telemetry import format_0466_fields, telemetry_from_frame
from .transport import BleakRS3Transport


LogCallback = Callable[[str], None]


class RS3Client:
    """Async semantic control client."""

    def __init__(
        self,
        device_identifier: str,
        *,
        timeout: float = 15.0,
        log_callback: LogCallback | None = None,
    ) -> None:
        self.transport = BleakRS3Transport(device_identifier, timeout=timeout)
        self.sequence = 0x5000
        self.started = monotonic()
        self.log_callback = log_callback
        self.telemetry = TelemetrySnapshot()

    def elapsed(self) -> float:
        return monotonic() - self.started

    def _next_sequence(self) -> int:
        sequence = self.sequence
        self.sequence += 1
        return sequence

    def emit(self, line: str) -> None:
        if self.log_callback is not None:
            self.log_callback(line)

    async def connect(self) -> None:
        await self.transport.connect()
        self.emit(f"{self.elapsed():8.3f}s connected {self.transport.device_identifier}")
        await self.transport.start_notifications(self._handle_notification)
        self.emit(f"{self.elapsed():8.3f}s subscribed {self.transport.NOTIFY_CHAR}")

    async def disconnect(self) -> None:
        await self.disconnect_with_options(stop_motion=True)

    async def disconnect_with_options(self, *, stop_motion: bool = True) -> None:
        if not self.transport.is_connected:
            return
        try:
            if stop_motion:
                await self.stop_motion()
        finally:
            try:
                await self.transport.stop_notifications()
            except Exception:
                pass
            await self.transport.disconnect()
            self.emit(f"{self.elapsed():8.3f}s disconnected")

    async def initialize_like_app(self) -> None:
        for command in APP_INIT_COMMANDS:
            await self.send_command(command, label="app-init")
            await asyncio.sleep(0.05)

    async def poll_once(self, payload_index: int = 0) -> None:
        payload = APP_POLL_PAYLOADS[min(payload_index, len(APP_POLL_PAYLOADS) - 1)]
        command = Command(0xE5, 0x00, 0x04, 0x12, payload)
        await self.send_command(command, label="poll-0412")

    async def request_state(
        self,
        *,
        active: bool = True,
        timeout: float = 3.0,
        poll_interval: float = 1.0,
    ) -> TelemetrySnapshot:
        """Return a fresh state snapshot, actively polling if requested."""

        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")

        started = monotonic()
        deadline = started + timeout
        poll_index = 0

        while monotonic() <= deadline:
            if self.telemetry.pose is not None and (self.telemetry.pose_timestamp or 0.0) >= started:
                return self.telemetry

            if active:
                await self.poll_once(poll_index)
                poll_index += 1

            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(poll_interval, remaining, 0.25 if not active else poll_interval))

        raise TimeoutError("timed out waiting for fresh pose telemetry")

    async def keepalive_0410(self) -> None:
        frame = build_keepalive_0410_frame(sequence=self._next_sequence())
        await self.write_frame(frame, label="keepalive-0410")

    async def stop_motion(self, repeats: int = 3, interval: float = 0.1) -> None:
        if not self.transport.is_connected:
            return
        for _ in range(repeats):
            await self.move_velocity(VelocityCommand(), label="neutral-stop")
            await asyncio.sleep(interval)

    async def move_velocity(self, command: VelocityCommand, *, label: str = "move") -> None:
        frame = build_velocity_frame(
            sequence=self._next_sequence(),
            tilt=int(round(command.tilt)),
            roll=int(round(command.roll)),
            pan=int(round(command.pan)),
        )
        await self.write_frame(frame, label=label)

    async def recenter(self) -> None:
        frame = build_recenter_frame(sequence=self._next_sequence())
        await self.write_frame(frame, label="recenter")

    async def sleep(self) -> None:
        frame = build_sleep_frame(sequence=self._next_sequence())
        await self.write_frame(frame, label="sleep")

    async def wake(self) -> None:
        frame = build_wake_frame(sequence=self._next_sequence())
        await self.write_frame(frame, label="wake")

    async def go_to(
        self,
        pose: Pose,
        *,
        method: str = "track",
        duration: float = 5.0,
        track_mode: int = 0x0A,
        track_param0: int = 20,
        track_param1: int = 20,
    ) -> None:
        if method != "track":
            raise NotImplementedError("only method='track' is implemented")
        waypoint = Waypoint(tilt_deg=pose.tilt_deg, roll_deg=pose.roll_deg, pan_deg=pose.pan_deg)
        await self.run_track(
            [waypoint],
            duration=duration,
            track_mode=track_mode,
            track_param0=track_param0,
            track_param1=track_param1,
        )

    async def run_track(
        self,
        waypoints: list[Waypoint],
        *,
        duration: float = 5.0,
        track_mode: int = 0x0A,
        track_param0: int = 20,
        track_param1: int = 20,
    ) -> None:
        frame = build_track_frame(
            [(waypoint.tilt_deg, waypoint.roll_deg, waypoint.pan_deg) for waypoint in waypoints],
            sequence=self._next_sequence(),
            mode=track_mode,
            param0=track_param0,
            param1=track_param1,
        )
        await self.write_frame(frame, label="track")
        await asyncio.sleep(max(0.0, duration))

    async def send_command(self, command: Command, *, label: str) -> None:
        frame = build_command_frame(command, sequence=self._next_sequence())
        await self.write_frame(frame, label=label)

    async def write_frame(self, frame: bytes, *, label: str) -> None:
        self.emit(f"{self.elapsed():8.3f}s write {label} {frame.hex()}")
        await self.transport.write_frame(frame)

    async def stream_telemetry(self, seconds: float | None = None) -> None:
        deadline = None if seconds is None else monotonic() + seconds
        while deadline is None or monotonic() < deadline:
            await asyncio.sleep(0.1)

    async def _handle_notification(self, raw: bytes) -> None:
        for frame in iter_embedded_frames(raw):
            updated = telemetry_from_frame(frame, self.telemetry)
            if updated is not None:
                self.telemetry = updated
            self._emit_notification(frame)

    def _emit_notification(self, frame: bytes) -> None:
        try:
            info = parse_frame(frame)
        except ValueError:
            return
        cmd_set = int(info["cmd_set"])
        cmd_id = int(info["cmd_id"])
        payload = info["payload"]
        assert isinstance(payload, bytes)

        if cmd_set == 0x0D and cmd_id == 0x02:
            values = decode_0d02_fields(payload)
            if values is not None:
                self.emit(
                    f"{self.elapsed():8.3f}s telemetry 0d/02 "
                    f"f0={values[0]:6d} f1={values[1]:6d} "
                    f"f2={values[2]:6d} f3={values[3]:6d}"
                )
            return

        if cmd_set == 0x04 and cmd_id == 0x66:
            fields = decode_0466_fields(payload)
            if fields is None:
                return
            pose = ""
            if all(tag in fields for tag in (0x22, 0x23, 0x24)):
                pose = (
                    f" pose(tilt={fields[0x22] / 10.0:.1f} "
                    f"roll={fields[0x23] / 10.0:.1f} pan={fields[0x24] / 10.0:.1f})"
                )
            self.emit(
                f"{self.elapsed():8.3f}s telemetry 04/66 "
                f"tlv=[{format_0466_fields(fields)}]{pose}"
            )


class FileLogger:
    """Shared CLI/logger utility."""

    def __init__(self, path: Path | None = None) -> None:
        self._handle: TextIO | None = None
        if path is not None:
            self._handle = path.open("a", encoding="utf-8")

    def emit(self, line: str) -> None:
        print(line, flush=True)
        if self._handle is not None:
            self._handle.write(line + "\n")
            self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def install_signal_stop_handler(stop_event: asyncio.Event) -> None:
    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)


__all__ = ["FileLogger", "RS3Client", "install_signal_stop_handler"]
