"""Thin CLI wrapper over the reusable RS3 library."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from time import monotonic

from ..client import FileLogger, RS3Client, install_signal_stop_handler
from ..models import TelemetrySnapshot, Pose, RateCommand, VelocityCommand, Waypoint
from ..protocol.commands import parse_waypoint_text
from ..protocol.telemetry import format_0466_fields


DEFAULT_ADDRESS = "48:1C:B9:DC:8B:99"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control a DJI RS3 gimbal over BLE.")
    parser.add_argument("--address", default=DEFAULT_ADDRESS, help="BLE device identifier or address.")
    parser.add_argument("--timeout", type=float, default=15.0, help="BLE connection timeout in seconds.")
    parser.add_argument("--log", type=Path, help="Append terminal output to this file.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    telemetry = subparsers.add_parser("telemetry", help="Subscribe and print live telemetry.")
    telemetry.add_argument("--seconds", type=float, default=0.0, help="Optional capture duration; 0 means until interrupted.")

    state = subparsers.add_parser("state", help="Request and print current decoded gimbal state.")
    state.add_argument("--once", action="store_true", help="Print one fresh state sample and exit. This is the default.")
    state.add_argument("--watch", action="store_true", help="Continuously print fresh state samples.")
    state.add_argument("--seconds", type=float, default=0.0, help="Optional watch duration; 0 means until interrupted.")
    state.add_argument("--passive", action="store_true", help="Subscribe only; do not send telemetry poll requests.")
    state.add_argument("--raw", action="store_true", help="Include raw decoded telemetry fields.")
    state.add_argument("--timeout", type=float, default=3.0, help="Seconds to wait for a fresh pose sample.")
    state.add_argument("--poll-interval", type=float, default=1.0, help="Seconds between active telemetry poll requests.")

    recenter = subparsers.add_parser("recenter", help="Command the gimbal to return to zero pose.")
    recenter.add_argument("--settle", type=float, default=3.0, help="How long to remain connected after issuing the command.")

    sleep = subparsers.add_parser("sleep", help="Command the gimbal to enter sleep mode.")
    sleep.add_argument("--settle", type=float, default=3.0, help="How long to remain connected after issuing the command.")

    wake = subparsers.add_parser("wake", help="Command the gimbal to wake from sleep mode.")
    wake.add_argument("--settle", type=float, default=3.0, help="How long to remain connected after issuing the command.")

    move = subparsers.add_parser("move", help="Send semantic velocity commands using joystick-style control.")
    move.add_argument("--tilt", type=float, default=0.0, help="Tilt joystick delta around center.")
    move.add_argument("--roll", type=float, default=0.0, help="Roll joystick delta around center.")
    move.add_argument("--pan", type=float, default=0.0, help="Pan joystick delta around center.")
    move.add_argument("--seconds", type=float, default=1.0, help="How long to hold the command.")
    move.add_argument("--rate", type=float, default=5.0, help="Command rate in Hz.")
    move.add_argument("--pre-neutral", type=int, default=3, help="Neutral frames before the motion burst.")
    move.add_argument("--post-neutral", type=int, default=5, help="Neutral frames after the motion burst.")

    rate = subparsers.add_parser("rate", help="Send native angular-rate control in degrees per second.")
    rate.add_argument("--tilt", type=float, default=0.0, help="Tilt rate in degrees per second.")
    rate.add_argument("--roll", type=float, default=0.0, help="Roll rate in degrees per second.")
    rate.add_argument("--pan", type=float, default=0.0, help="Pan rate in degrees per second.")
    rate.add_argument("--seconds", type=float, default=0.5, help="How long to hold the native rate command.")
    rate.add_argument("--rate", type=float, default=5.0, help="Native rate command refresh rate in Hz.")
    rate.add_argument("--max-speed", type=float, default=30.0, help="Safety limit for absolute native rate values.")
    rate.add_argument(
        "--allow-negative",
        action="store_true",
        help="Allow unvalidated negative native rates for protocol experiments.",
    )

    goto = subparsers.add_parser("goto", help="Move to an absolute pose.")
    goto.add_argument("--tilt", type=float, required=True, help="Target tilt in degrees.")
    goto.add_argument("--roll", type=float, default=0.0, help="Target roll in degrees.")
    goto.add_argument("--pan", type=float, required=True, help="Target pan in degrees.")
    goto.add_argument(
        "--duration",
        type=float,
        default=2.0,
        help="Requested move duration in seconds; also keeps the connection open long enough to observe the move.",
    )

    track = subparsers.add_parser("track", help="Send a multi-waypoint track program.")
    track.add_argument(
        "--waypoint",
        action="append",
        type=parse_waypoint_text,
        default=[],
        metavar="TILT,PAN",
        help="Waypoint in degrees. Also accepts TILT,ROLL,PAN. Repeat for multiple waypoints.",
    )
    track.add_argument("--duration", type=float, default=8.0, help="How long to remain connected after issuing the command.")
    track.add_argument("--track-mode", type=lambda value: int(value, 0), default=0x0A)
    track.add_argument("--track-param0", type=int, default=20)
    track.add_argument("--track-param1", type=int, default=20)
    return parser


def format_state(snapshot: TelemetrySnapshot, *, raw: bool) -> str:
    pose = snapshot.pose
    if pose is None:
        text = "state pose=unavailable"
    else:
        age = ""
        if snapshot.pose_timestamp is not None:
            age = f" age={monotonic() - snapshot.pose_timestamp:.2f}s"
        text = f"state tilt={pose.tilt_deg:.1f} roll={pose.roll_deg:.1f} pan={pose.pan_deg:.1f}{age}"

    if snapshot.battery_or_status is not None:
        text += f" battery_or_status={snapshot.battery_or_status:.0f}"
    if raw:
        if snapshot.raw_0d02 is not None:
            text += f" raw_0d02={snapshot.raw_0d02}"
        if snapshot.raw_0466:
            text += f" raw_0466=[{format_0466_fields(snapshot.raw_0466)}]"
    return text


async def run_cli(args: argparse.Namespace) -> None:
    logger = FileLogger(args.log)
    stop_event = asyncio.Event()
    install_signal_stop_handler(stop_event)
    if args.command == "rate":
        if args.seconds < 0:
            raise SystemExit("--seconds must be non-negative")
        if args.rate <= 0:
            raise SystemExit("--rate must be positive")
        if args.max_speed <= 0:
            raise SystemExit("--max-speed must be positive")
        if not args.allow_negative and any(value < 0 for value in (args.tilt, args.roll, args.pan)):
            raise SystemExit("negative native rates are not validated yet; use --allow-negative only for protocol tests")
        if any(abs(value) > args.max_speed for value in (args.tilt, args.roll, args.pan)):
            raise SystemExit("--tilt, --roll, and --pan must not exceed --max-speed")

    log_callback = None if args.command == "state" else logger.emit
    client = RS3Client(args.address, timeout=args.timeout, log_callback=log_callback)

    try:
        await client.connect()
        if args.command == "telemetry":
            if args.seconds == 0:
                await stop_event.wait()
            else:
                await client.stream_telemetry(seconds=args.seconds)
            return

        if args.command == "state":
            if args.timeout < 0:
                raise SystemExit("--timeout must be non-negative")
            if args.poll_interval <= 0:
                raise SystemExit("--poll-interval must be positive")
            if args.seconds < 0:
                raise SystemExit("--seconds must be non-negative")
            if args.once and args.watch:
                raise SystemExit("--once and --watch cannot be used together")

            active = not args.passive
            if not args.watch:
                snapshot = await client.request_state(
                    active=active,
                    timeout=args.timeout,
                    poll_interval=args.poll_interval,
                )
                logger.emit(format_state(snapshot, raw=args.raw))
                return

            deadline = None if args.seconds == 0 else asyncio.get_running_loop().time() + args.seconds
            last_pose_timestamp = None
            while not stop_event.is_set() and (deadline is None or asyncio.get_running_loop().time() < deadline):
                try:
                    snapshot = await client.request_state(
                        active=active,
                        timeout=args.timeout,
                        poll_interval=args.poll_interval,
                    )
                except TimeoutError:
                    logger.emit("state pose=unavailable timeout")
                    continue
                if snapshot.pose_timestamp != last_pose_timestamp:
                    logger.emit(format_state(snapshot, raw=args.raw))
                    last_pose_timestamp = snapshot.pose_timestamp
            return

        if args.command == "recenter":
            await client.recenter()
            await asyncio.sleep(max(0.0, args.settle))
            return

        if args.command == "sleep":
            await client.sleep()
            await asyncio.sleep(max(0.0, args.settle))
            return

        if args.command == "wake":
            await client.wake()
            await asyncio.sleep(max(0.0, args.settle))
            return

        if args.command == "move":
            if args.rate <= 0:
                raise SystemExit("--rate must be positive")
            interval = 1.0 / args.rate
            neutral = VelocityCommand()
            command = VelocityCommand(tilt=args.tilt, roll=args.roll, pan=args.pan)
            for _ in range(args.pre_neutral):
                await client.move_velocity(neutral, label="neutral-pre")
                await asyncio.sleep(interval)
            deadline = asyncio.get_running_loop().time() + max(0.0, args.seconds)
            while asyncio.get_running_loop().time() < deadline and not stop_event.is_set():
                await client.move_velocity(command, label="move")
                await asyncio.sleep(interval)
            for _ in range(args.post_neutral):
                await client.move_velocity(neutral, label="neutral-post")
                await asyncio.sleep(interval)
            return

        if args.command == "rate":
            await client.move_rate(
                RateCommand(tilt_deg_s=args.tilt, roll_deg_s=args.roll, pan_deg_s=args.pan),
                seconds=args.seconds,
                rate=args.rate,
                max_abs_speed_deg_s=args.max_speed,
                allow_negative=args.allow_negative,
            )
            return

        if args.command == "goto":
            if args.duration < 0:
                raise SystemExit("--duration must be non-negative")
            await client.go_to(
                Pose(tilt_deg=args.tilt, roll_deg=args.roll, pan_deg=args.pan),
                duration=args.duration,
            )
            return

        if args.command == "track":
            if not args.waypoint:
                raise SystemExit("track requires at least one --waypoint")
            await client.run_track(
                [Waypoint(tilt_deg=tilt, roll_deg=roll, pan_deg=pan) for tilt, roll, pan in args.waypoint],
                duration=args.duration,
                track_mode=args.track_mode,
                track_param0=args.track_param0,
                track_param1=args.track_param1,
            )
            return

        raise SystemExit(f"unsupported command: {args.command}")
    finally:
        if args.command == "state":
            await client.disconnect_with_options(stop_motion=False)
        else:
            await client.disconnect()
        logger.close()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run_cli(args))


__all__ = ["build_parser", "main", "run_cli"]


if __name__ == "__main__":
    main()
