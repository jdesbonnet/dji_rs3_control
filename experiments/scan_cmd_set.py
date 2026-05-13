"""Brute-scan a DUML cmd_set / id space looking for any reply.

For each id in [--id-start, --id-end], send a single DUML frame with the
configured cmd_type, cmd_set, and payload, then wait --window seconds and
attribute any frames received in that window to the request.

A 2-second pre-scan establishes a baseline of (set, id) pairs the gimbal
emits passively, so the summary only highlights *novel* responses.

Usage:
    python3 experiments/scan_cmd_set.py
    python3 experiments/scan_cmd_set.py --cmd-set 0x0e --payload 01
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from bleak import BleakClient

from rs3.protocol import build_command_frame, iter_embedded_frames, parse_frame
from rs3.protocol.commands import Command


DEFAULT_ADDRESS = "48:1C:B9:DC:8B:99"
NOTIFY_CHAR = "0000fff4-0000-1000-8000-00805f9b34fb"
WRITE_CHAR = "0000fff5-0000-1000-8000-00805f9b34fb"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    parser.add_argument("--cmd-set", type=lambda v: int(v, 0), default=0x04)
    parser.add_argument("--cmd-type", type=lambda v: int(v, 0), default=0x03)
    parser.add_argument("--receiver", type=lambda v: int(v, 0), default=0x04)
    parser.add_argument("--payload", default="", help="Hex string, e.g. '01'")
    parser.add_argument("--id-start", type=lambda v: int(v, 0), default=0x00)
    parser.add_argument("--id-end", type=lambda v: int(v, 0), default=0xFF)
    parser.add_argument("--window", type=float, default=0.10,
                        help="Seconds to wait for a reply after each request.")
    parser.add_argument("--baseline-seconds", type=float, default=2.0)
    parser.add_argument(
        "--skip",
        default="0x01,0x07,0x08,0x0c,0x0f,0x10,0x14,0x4c,0x62",
        help="Comma-separated cmd_ids to skip even with cmd_type=0x03 (known motion/state changers in cmd_set=0x04, plus 0x08 which triggers calibration).",
    )
    args = parser.parse_args()

    skip_ids = {int(token, 0) for token in args.skip.split(",") if token.strip()}

    payload = bytes.fromhex(args.payload)

    started = monotonic()
    state: dict[str, object] = {
        "pending_id": None,
        "pending_t": 0.0,
        "baseline_keys": set(),
    }
    received_per_id: dict[int, list[dict]] = defaultdict(list)
    baseline_frames: list[dict] = []

    def on_notify(_sender: int, data: bytes) -> None:
        now = monotonic() - started
        for frame in iter_embedded_frames(bytes(data)):
            try:
                info = parse_frame(frame)
            except ValueError:
                continue
            entry = {
                "t": now,
                "sender": int(info["sender"]),
                "receiver": int(info["receiver"]),
                "type": int(info["cmd_type"]),
                "set": int(info["cmd_set"]),
                "id": int(info["cmd_id"]),
                "payload": bytes(info["payload"]).hex(),
            }
            pending_id = state["pending_id"]
            pending_t = state["pending_t"]
            if (
                isinstance(pending_id, int)
                and isinstance(pending_t, float)
                and now - pending_t <= args.window
            ):
                received_per_id[pending_id].append(entry)
            else:
                baseline_frames.append(entry)

    sequence = 0x5000
    async with BleakClient(args.address, timeout=15.0) as client:
        print(f"connected {args.address}")
        await client.start_notify(NOTIFY_CHAR, on_notify)
        print(f"subscribed {NOTIFY_CHAR}")

        print(f"baselining for {args.baseline_seconds:.1f}s ...")
        await asyncio.sleep(args.baseline_seconds)
        baseline_keys = {(e["set"], e["id"]) for e in baseline_frames}
        state["baseline_keys"] = baseline_keys
        print(f"baseline (set,id) pairs: "
              f"{sorted(f'{s:02x}/{i:02x}' for s, i in baseline_keys)}")

        ids = [i for i in range(args.id_start, args.id_end + 1) if i not in skip_ids]
        print(f"scanning cmd_set=0x{args.cmd_set:02x} ids 0x{args.id_start:02x}..0x{args.id_end:02x} "
              f"(type=0x{args.cmd_type:02x}, payload={args.payload!r}, "
              f"window={args.window:.2f}s, skipping {sorted(f'0x{i:02x}' for i in skip_ids)})")
        for cmd_id in ids:
            state["pending_id"] = cmd_id
            state["pending_t"] = monotonic() - started
            frame = build_command_frame(
                Command(args.receiver, args.cmd_type, args.cmd_set, cmd_id, payload),
                sequence=sequence,
            )
            sequence += 1
            await client.write_gatt_char(WRITE_CHAR, frame, response=False)
            await asyncio.sleep(args.window)
        state["pending_id"] = None

        await asyncio.sleep(0.5)
        await client.stop_notify(NOTIFY_CHAR)

    print("\n=== Summary ===")
    novel: list[tuple[int, dict]] = []
    for cmd_id, entries in sorted(received_per_id.items()):
        for entry in entries:
            key = (entry["set"], entry["id"])
            response_direction = bool(entry["type"] & 0x80)
            matches_scan_set = entry["set"] == args.cmd_set
            if key in baseline_keys and not (response_direction and matches_scan_set):
                continue
            novel.append((cmd_id, entry))

    if not novel:
        print("no novel replies detected.")
        print(f"  ({sum(len(v) for v in received_per_id.values())} total frames seen during scan, "
              f"all matched baseline keys)")
        return

    print(f"{len(novel)} novel reply candidates:")
    for cmd_id, entry in novel:
        marker = ""
        if entry["set"] == args.cmd_set and entry["id"] == cmd_id and (entry["type"] & 0x80):
            marker = " <-- direct reply"
        elif entry["type"] & 0x80:
            marker = " <-- response-direction"
        print(
            f"  req id=0x{cmd_id:02x} -> "
            f"sender=0x{entry['sender']:02x} type=0x{entry['type']:02x} "
            f"set=0x{entry['set']:02x} id=0x{entry['id']:02x} "
            f"payload={entry['payload']}{marker}"
        )


if __name__ == "__main__":
    asyncio.run(main())
