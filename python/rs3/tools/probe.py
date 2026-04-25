"""Protocol-oriented probing tool for RS3 reverse engineering."""

from __future__ import annotations

import argparse
import asyncio
import signal
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TextIO

from bleak import BleakClient

from ..protocol import (
    APP_INIT_COMMANDS,
    APP_POLL_PAYLOADS,
    CENTER,
    Command,
    axis_values_for_direction,
    build_command_frame,
    build_keepalive_0410_frame,
    build_recenter_frame,
    build_track_frame,
    build_velocity_frame,
    decode_0466_fields,
    decode_0d02_fields,
    iter_embedded_frames,
    parse_frame,
)
from ..protocol.telemetry import format_0466_fields


DEFAULT_ADDRESS = "48:1C:B9:DC:8B:99"
NOTIFY_CHAR = "0000fff4-0000-1000-8000-00805f9b34fb"
WRITE_CHAR = "0000fff5-0000-1000-8000-00805f9b34fb"


@dataclass
class ProbeOptions:
    direction: str
    address: str
    delta: int
    duration: float
    rate: float
    pre_neutral: int
    post_neutral: int
    app_init: bool
    poll: bool
    keepalive_0410: bool
    monitor: bool
    telemetry: bool
    dump_frames: bool
    log: Path | None
    waypoints: list[tuple[int, int, int]]
    track_mode: int
    track_param0: int
    track_param1: int
    raw_receiver: int
    raw_cmd_type: int
    raw_cmd_set: int | None
    raw_cmd_id: int | None
    raw_payload: bytes
    dry_run: bool


class ProbeController:
    def __init__(self, client: object, *, dry_run: bool, log_handle: TextIO | None = None) -> None:
        self.client = client
        self.dry_run = dry_run
        self.log_handle = log_handle
        self.sequence = 0x5000
        self.started = monotonic()

    def elapsed(self) -> float:
        return monotonic() - self.started

    def emit(self, line: str) -> None:
        print(line, flush=True)
        if self.log_handle is not None:
            self.log_handle.write(line + "\n")
            self.log_handle.flush()

    async def write_frame(self, frame: bytes, label: str) -> None:
        self.emit(f"{self.elapsed():8.3f}s write {label} {frame.hex()}")
        if self.dry_run:
            return
        await self.client.write_gatt_char(WRITE_CHAR, frame, response=False)

    async def send_command(self, command: Command, label: str) -> None:
        frame = build_command_frame(command, sequence=self.sequence)
        self.sequence += 1
        await self.write_frame(frame, label)

    async def send_velocity(self, *, tilt: int = 0, roll: int = 0, pan: int = 0, label: str) -> None:
        frame = build_velocity_frame(sequence=self.sequence, tilt=tilt, roll=roll, pan=pan)
        self.sequence += 1
        await self.write_frame(frame, label)

    async def send_neutral(self, *, label: str) -> None:
        await self.send_velocity(label=label)


def parse_probe_waypoint_text(text: str) -> tuple[int, int, int]:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) == 2:
        axis0_text, axis2_text = parts
        axis1_text = "0"
    elif len(parts) == 3:
        axis0_text, axis1_text, axis2_text = parts
    else:
        raise argparse.ArgumentTypeError("waypoint must be axis0,axis2 or axis0,axis1,axis2")
    try:
        return int(axis0_text), int(axis1_text), int(axis2_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("waypoint values must be integers") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Protocol-oriented RS3 BLE probing tool.")
    parser.add_argument(
        "direction",
        choices=["left", "right", "up", "down", "axis0", "axis1", "axis2", "recenter", "track", "raw"],
    )
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    parser.add_argument("--delta", type=int, default=180, help="Signed joystick delta around the 1024 center point.")
    parser.add_argument("--duration", type=float, default=1.0)
    parser.add_argument("--rate", type=float, default=5.0)
    parser.add_argument("--pre-neutral", type=int, default=3)
    parser.add_argument("--post-neutral", type=int, default=5)
    parser.add_argument("--app-init", action="store_true")
    parser.add_argument("--poll", action="store_true")
    parser.add_argument("--keepalive-0410", action="store_true")
    parser.add_argument("--monitor", action="store_true")
    parser.add_argument("--telemetry", action="store_true")
    parser.add_argument("--dump-frames", action="store_true")
    parser.add_argument("--log", type=Path)
    parser.add_argument(
        "--waypoint",
        action="append",
        type=parse_probe_waypoint_text,
        default=[],
        metavar="AXIS0,AXIS2",
        help="Track waypoint in raw pose units; may also be AXIS0,AXIS1,AXIS2. Repeat for multiple waypoints.",
    )
    parser.add_argument("--track-mode", type=lambda value: int(value, 0), default=0x0A)
    parser.add_argument("--track-param0", type=int, default=20)
    parser.add_argument("--track-param1", type=int, default=20)
    parser.add_argument("--raw-receiver", type=lambda value: int(value, 0), default=0x04)
    parser.add_argument("--raw-type", type=lambda value: int(value, 0), default=0x40)
    parser.add_argument("--raw-set", type=lambda value: int(value, 0), help="Raw DUML command set, for example 0x04.")
    parser.add_argument("--raw-id", type=lambda value: int(value, 0), help="Raw DUML command id, for example 0x0f.")
    parser.add_argument("--raw-payload", default="", help="Raw DUML payload as hex, for example 230101.")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def parse_args(argv: list[str] | None = None) -> ProbeOptions:
    args = build_parser().parse_args(argv)
    if args.rate <= 0:
        raise SystemExit("--rate must be positive")
    if args.duration < 0:
        raise SystemExit("--duration must be non-negative")
    if args.direction == "track" and not args.waypoint:
        raise SystemExit("track action requires at least one --waypoint")
    if args.direction == "raw" and (args.raw_set is None or args.raw_id is None):
        raise SystemExit("raw action requires --raw-set and --raw-id")
    try:
        raw_payload = bytes.fromhex(args.raw_payload)
    except ValueError as exc:
        raise SystemExit("--raw-payload must be valid hex") from exc

    return ProbeOptions(
        direction=args.direction,
        address=args.address,
        delta=args.delta,
        duration=args.duration,
        rate=args.rate,
        pre_neutral=args.pre_neutral,
        post_neutral=args.post_neutral,
        app_init=args.app_init,
        poll=args.poll,
        keepalive_0410=args.keepalive_0410,
        monitor=args.monitor,
        telemetry=args.telemetry,
        dump_frames=args.dump_frames,
        log=args.log,
        waypoints=args.waypoint,
        track_mode=args.track_mode,
        track_param0=args.track_param0,
        track_param1=args.track_param1,
        raw_receiver=args.raw_receiver,
        raw_cmd_type=args.raw_type,
        raw_cmd_set=args.raw_set,
        raw_cmd_id=args.raw_id,
        raw_payload=raw_payload,
        dry_run=args.dry_run,
    )


async def run_probe(options: ProbeOptions) -> None:
    stop_event = asyncio.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    log_handle = options.log.open("a", encoding="utf-8") if options.log is not None else None
    try:
        if options.dry_run:
            class DryClient:
                async def write_gatt_char(self, *_args: object, **_kwargs: object) -> None:
                    return None

            controller = ProbeController(DryClient(), dry_run=True, log_handle=log_handle)
            await run_sequence(controller, options, stop_event)
            return

        async with BleakClient(options.address, timeout=15.0) as client:
            controller = ProbeController(client, dry_run=False, log_handle=log_handle)
            controller.emit(f"{controller.elapsed():8.3f}s connected {options.address}")
            await client.start_notify(
                NOTIFY_CHAR,
                lambda _sender, data: on_notify(
                    controller,
                    bytes(data),
                    monitor=options.monitor,
                    telemetry=options.telemetry,
                    dump_frames=options.dump_frames,
                ),
            )
            controller.emit(f"{controller.elapsed():8.3f}s subscribed {NOTIFY_CHAR}")
            try:
                await run_sequence(controller, options, stop_event)
            finally:
                for _ in range(max(3, options.post_neutral)):
                    await controller.send_neutral(label="neutral-stop")
                    await asyncio.sleep(0.1)
                await client.stop_notify(NOTIFY_CHAR)
                controller.emit(f"{controller.elapsed():8.3f}s stopped")
    finally:
        if log_handle is not None:
            log_handle.close()


async def run_sequence(controller: ProbeController, options: ProbeOptions, stop_event: asyncio.Event) -> None:
    keepalive_task: asyncio.Task[None] | None = None
    poll_task: asyncio.Task[None] | None = None

    async def keepalive_loop() -> None:
        while not stop_event.is_set():
            frame = build_keepalive_0410_frame(sequence=controller.sequence)
            controller.sequence += 1
            await controller.write_frame(frame, "keepalive-0410")
            await asyncio.sleep(1.0)

    async def poll_loop() -> None:
        index = 0
        while not stop_event.is_set():
            payload = APP_POLL_PAYLOADS[min(index, len(APP_POLL_PAYLOADS) - 1)]
            await controller.send_command(Command(0xE5, 0x00, 0x04, 0x12, payload), "poll-0412")
            index += 1
            await asyncio.sleep(1.0)

    if options.app_init:
        for command in APP_INIT_COMMANDS:
            await controller.send_command(command, "app-init")
            await asyncio.sleep(0.05)
    if options.keepalive_0410:
        keepalive_task = asyncio.create_task(keepalive_loop())
    if options.poll:
        poll_task = asyncio.create_task(poll_loop())

    interval = 1.0 / options.rate
    for _ in range(options.pre_neutral):
        if stop_event.is_set():
            break
        await controller.send_neutral(label="neutral-pre")
        await asyncio.sleep(interval)

    if options.direction == "recenter":
        frame = build_recenter_frame(sequence=controller.sequence)
        controller.sequence += 1
        await controller.write_frame(frame, "recenter")
        deadline = monotonic() + options.duration
        while monotonic() < deadline and not stop_event.is_set():
            await asyncio.sleep(interval)
    elif options.direction == "track":
        frame = build_track_frame(
            [(axis0 / 10.0, axis1 / 10.0, axis2 / 10.0) for axis0, axis1, axis2 in options.waypoints],
            sequence=controller.sequence,
            mode=options.track_mode,
            param0=options.track_param0,
            param1=options.track_param1,
        )
        controller.sequence += 1
        await controller.write_frame(frame, "track")
        deadline = monotonic() + options.duration
        while monotonic() < deadline and not stop_event.is_set():
            await asyncio.sleep(interval)
    elif options.direction == "raw":
        assert options.raw_cmd_set is not None
        assert options.raw_cmd_id is not None
        await controller.send_command(
            Command(
                options.raw_receiver,
                options.raw_cmd_type,
                options.raw_cmd_set,
                options.raw_cmd_id,
                options.raw_payload,
            ),
            "raw",
        )
        deadline = monotonic() + options.duration
        while monotonic() < deadline and not stop_event.is_set():
            await asyncio.sleep(interval)
    else:
        axis0, axis1, axis2 = axis_values_for_direction(options.direction, options.delta)
        tilt = axis0 - CENTER
        roll = axis1 - CENTER
        pan = axis2 - CENTER
        deadline = monotonic() + options.duration
        while monotonic() < deadline and not stop_event.is_set():
            await controller.send_velocity(tilt=tilt, roll=roll, pan=pan, label=options.direction)
            await asyncio.sleep(interval)

    for _ in range(options.post_neutral):
        if stop_event.is_set():
            break
        await controller.send_neutral(label="neutral-post")
        await asyncio.sleep(interval)

    for task in (keepalive_task, poll_task):
        if task is not None:
            task.cancel()


def on_notify(controller: ProbeController, raw: bytes, *, monitor: bool, telemetry: bool, dump_frames: bool) -> None:
    if not monitor and not telemetry and not dump_frames:
        return
    for frame in iter_embedded_frames(raw):
        try:
            info = parse_frame(frame)
        except ValueError:
            continue
        cmd_set = int(info["cmd_set"])
        cmd_id = int(info["cmd_id"])
        payload = info["payload"]
        assert isinstance(payload, bytes)

        if dump_frames:
            controller.emit(
                f"{controller.elapsed():8.3f}s frame sender={int(info['sender']):02x} "
                f"receiver={int(info['receiver']):02x} type={int(info['cmd_type']):02x} "
                f"set={cmd_set:02x} id={cmd_id:02x} payload={payload.hex()}"
            )
        if telemetry and cmd_set == 0x0D and cmd_id == 0x02:
            values = decode_0d02_fields(payload)
            if values is not None:
                controller.emit(
                    f"{controller.elapsed():8.3f}s telemetry 0d/02 "
                    f"f0={values[0]:6d} f1={values[1]:6d} "
                    f"f2={values[2]:6d} f3={values[3]:6d}"
                )
                continue
        if telemetry and cmd_set == 0x04 and cmd_id == 0x66:
            fields = decode_0466_fields(payload)
            if fields is None:
                controller.emit(f"{controller.elapsed():8.3f}s telemetry 04/66 payload={payload.hex()}")
            else:
                pose = ""
                if all(tag in fields for tag in (0x22, 0x23, 0x24)):
                    pose = (
                        f" pose(tilt={fields[0x22] / 10.0:.1f} "
                        f"roll={fields[0x23] / 10.0:.1f} pan={fields[0x24] / 10.0:.1f})"
                    )
                controller.emit(
                    f"{controller.elapsed():8.3f}s telemetry 04/66 "
                    f"tlv=[{format_0466_fields(fields)}]{pose}"
                )
            continue
        if monitor and (cmd_set, cmd_id) in {(0x04, 0x10), (0x04, 0x27), (0x0D, 0x02), (0x04, 0x4C), (0x04, 0x6B)}:
            controller.emit(
                f"{controller.elapsed():8.3f}s notify sender={int(info['sender']):02x} "
                f"set={cmd_set:02x} id={cmd_id:02x} payload={payload.hex()}"
            )


def main(argv: list[str] | None = None) -> None:
    asyncio.run(run_probe(parse_args(argv)))


__all__ = ["build_parser", "main", "on_notify", "parse_args", "run_probe", "run_sequence"]
