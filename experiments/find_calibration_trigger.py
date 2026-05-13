"""Find which cmd_set=0x04 id triggers calibration with cmd_type=0x03.

Walks the suspect range 0x22..0x37 one id at a time, sending the request and
then watching for the calibration-progress signature `04/30 payload=NN01` for
up to WAIT_PER_ID seconds. Stops on the first trigger so the user only has to
reset the gimbal once.

Side note: any `0x80`-typed direct reply to a request is printed inline so we
can also capture incidental GET-style hits along the way.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from bleak import BleakClient

from rs3.protocol import build_command_frame, iter_embedded_frames, parse_frame
from rs3.protocol.commands import Command


ADDRESS = "48:1C:B9:DC:8B:99"
NOTIFY_CHAR = "0000fff4-0000-1000-8000-00805f9b34fb"
WRITE_CHAR = "0000fff5-0000-1000-8000-00805f9b34fb"

CALIBRATION_SIGNATURE = (0x04, 0x30)
DEFAULT_SKIP = "0x01,0x07,0x08,0x0c,0x0f,0x10,0x14,0x4c,0x62"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id-start", type=lambda v: int(v, 0), default=0x22)
    parser.add_argument("--id-end", type=lambda v: int(v, 0), default=0x37)
    parser.add_argument("--wait", type=float, default=3.0)
    parser.add_argument("--skip", default=DEFAULT_SKIP)
    args = parser.parse_args()
    skip_ids = {int(token, 0) for token in args.skip.split(",") if token.strip()}
    started = monotonic()
    saw_calibration = asyncio.Event()
    state: dict[str, object] = {
        "last_send_id": None,
        "first_cal_frame": None,
    }

    def on_notify(_sender: int, data: bytes) -> None:
        for frame in iter_embedded_frames(bytes(data)):
            try:
                info = parse_frame(frame)
            except ValueError:
                continue
            entry = {
                "t": monotonic() - started,
                "sender": int(info["sender"]),
                "type": int(info["cmd_type"]),
                "set": int(info["cmd_set"]),
                "id": int(info["cmd_id"]),
                "payload": bytes(info["payload"]).hex(),
            }
            if (entry["set"], entry["id"]) == CALIBRATION_SIGNATURE:
                if state["first_cal_frame"] is None:
                    state["first_cal_frame"] = entry
                    saw_calibration.set()
                continue
            last_send_id = state["last_send_id"]
            if (
                isinstance(last_send_id, int)
                and entry["type"] & 0x80
                and entry["set"] == 0x04
                and entry["id"] == last_send_id
            ):
                print(
                    f"  reply to 0x{last_send_id:02x}: "
                    f"type=0x{entry['type']:02x} payload={entry['payload']}"
                )

    sequence = 0x5000
    triggered_by: int | None = None

    async with BleakClient(ADDRESS, timeout=15.0) as client:
        print(f"connected {ADDRESS}")
        await client.start_notify(NOTIFY_CHAR, on_notify)
        await asyncio.sleep(1.0)
        print(f"scanning ids 0x{args.id_start:02x}..0x{args.id_end:02x}, {args.wait:.1f}s per id, "
              f"stop on 04/30, skipping {sorted(f'0x{i:02x}' for i in skip_ids)}")

        for cmd_id in range(args.id_start, args.id_end + 1):
            if cmd_id in skip_ids:
                continue
            print(f"  send 0x{cmd_id:02x} ...", flush=True)
            state["last_send_id"] = cmd_id
            frame = build_command_frame(
                Command(0x04, 0x03, 0x04, cmd_id, b""),
                sequence=sequence,
            )
            sequence += 1
            await client.write_gatt_char(WRITE_CHAR, frame, response=False)
            try:
                await asyncio.wait_for(saw_calibration.wait(), timeout=args.wait)
            except asyncio.TimeoutError:
                continue
            triggered_by = cmd_id
            break

        await client.stop_notify(NOTIFY_CHAR)

    print()
    if triggered_by is None:
        print("No 04/30 trigger detected across the full range.")
        return
    print(f"*** CALIBRATION TRIGGER: cmd_id=0x{triggered_by:02x} ***")
    first = state["first_cal_frame"]
    if isinstance(first, dict):
        print(
            f"first 04/30 frame: t={first['t']:.2f}s "
            f"sender=0x{first['sender']:02x} "
            f"type=0x{first['type']:02x} "
            f"payload={first['payload']}"
        )


if __name__ == "__main__":
    asyncio.run(main())
