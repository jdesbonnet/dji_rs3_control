"""Trigger calibration once, then passively capture all frames for 30 s.

Sends a single `cmd_type=0x03 cmd_set=0x04 cmd_id=0x08 payload=empty` request
and then stays silent on the BLE link while logging every received frame.
The goal is to characterize what (if anything) follows the `04/30` progress
stream so we can identify the success/failure encoding.

Output is written to `experiments/calibration_capture.json` for later
inspection.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from bleak import BleakClient

from rs3.protocol import build_command_frame, iter_embedded_frames, parse_frame
from rs3.protocol.commands import Command


ADDRESS = "48:1C:B9:DC:8B:99"
NOTIFY_CHAR = "0000fff4-0000-1000-8000-00805f9b34fb"
WRITE_CHAR = "0000fff5-0000-1000-8000-00805f9b34fb"

BASELINE_SECONDS = 2.0
CAPTURE_SECONDS = 120.0
OUTPUT_PATH = Path(__file__).parent / "calibration_capture.json"


async def main() -> None:
    started = monotonic()
    frames: list[dict] = []
    state = {"phase": "baseline"}

    def on_notify(_sender: int, data: bytes) -> None:
        for frame in iter_embedded_frames(bytes(data)):
            try:
                info = parse_frame(frame)
            except ValueError:
                continue
            frames.append({
                "t": monotonic() - started,
                "phase": state["phase"],
                "sender": int(info["sender"]),
                "receiver": int(info["receiver"]),
                "type": int(info["cmd_type"]),
                "set": int(info["cmd_set"]),
                "id": int(info["cmd_id"]),
                "payload": bytes(info["payload"]).hex(),
            })

    async with BleakClient(ADDRESS, timeout=15.0) as client:
        print(f"connected {ADDRESS}")
        await client.start_notify(NOTIFY_CHAR, on_notify)

        print(f"baselining for {BASELINE_SECONDS:.1f} s ...")
        await asyncio.sleep(BASELINE_SECONDS)

        state["phase"] = "capture"
        print("triggering calibration: cmd_type=0x03 cmd_set=0x04 cmd_id=0x08 payload=empty")
        trigger_frame = build_command_frame(
            Command(0x04, 0x03, 0x04, 0x08, b""),
            sequence=0x5000,
        )
        await client.write_gatt_char(WRITE_CHAR, trigger_frame, response=False)
        print(f"sent; capturing silently for {CAPTURE_SECONDS:.0f} s ...")
        await asyncio.sleep(CAPTURE_SECONDS)
        await client.stop_notify(NOTIFY_CHAR)

    OUTPUT_PATH.write_text(json.dumps(frames, indent=2))
    print(f"\nsaved {len(frames)} frames to {OUTPUT_PATH}")

    baseline_keys = {(e["set"], e["id"]) for e in frames if e["phase"] == "baseline"}
    capture = [e for e in frames if e["phase"] == "capture"]

    print(f"\nbaseline (set,id) pairs: "
          f"{sorted(f'{s:02x}/{i:02x}' for s, i in baseline_keys)}")

    prog = [e for e in capture if (e["set"], e["id"]) == (0x04, 0x30)]
    print(f"\n04/30 progress frames during capture: {len(prog)}")
    if prog:
        first_counter = int(prog[0]["payload"][0:2], 16)
        last_counter = int(prog[-1]["payload"][0:2], 16)
        print(f"  first at t={prog[0]['t']:.3f}s counter=0x{first_counter:02x} payload={prog[0]['payload']}")
        print(f"  last  at t={prog[-1]['t']:.3f}s counter=0x{last_counter:02x} payload={prog[-1]['payload']}")
        unique_payloads = sorted({e["payload"] for e in prog})
        nonstandard = [p for p in unique_payloads if not p.endswith("01")]
        if nonstandard:
            print(f"  non-'NN01' payloads observed: {nonstandard}")
        else:
            print(f"  all payloads of form NNxx have second byte == 01")

    novel = [
        e for e in capture
        if (e["set"], e["id"]) not in baseline_keys
        and (e["set"], e["id"]) != (0x04, 0x30)
    ]
    if novel:
        print(f"\nnovel (set,id) pairs during capture: {len(novel)}")
        for e in novel:
            print(
                f"  t={e['t']:.3f}s sender=0x{e['sender']:02x} "
                f"type=0x{e['type']:02x} set=0x{e['set']:02x} "
                f"id=0x{e['id']:02x} payload={e['payload']}"
            )

    if prog:
        tail = [e for e in capture if e["t"] > prog[-1]["t"]]
        print(f"\nframes after last 04/30 ({len(tail)} total):")
        tail_keys = Counter((e["set"], e["id"]) for e in tail)
        for (s, i), count in tail_keys.most_common():
            marker = " [baseline]" if (s, i) in baseline_keys else " [NEW]"
            print(f"  {s:02x}/{i:02x}: {count} frame(s){marker}")
        print("\nfirst 15 tail frames in detail:")
        for e in tail[:15]:
            marker = " [baseline]" if (e["set"], e["id"]) in baseline_keys else " [NEW]"
            print(
                f"  t={e['t']:.3f}s sender=0x{e['sender']:02x} "
                f"type=0x{e['type']:02x} set=0x{e['set']:02x} "
                f"id=0x{e['id']:02x} payload={e['payload']}{marker}"
            )


if __name__ == "__main__":
    asyncio.run(main())
