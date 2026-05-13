#!/usr/bin/env python3
"""Minimal WebSocket-to-BLE gateway for the RS3 web app.

The implementation intentionally uses only the Python standard library plus the
repo-local rs3 package. Browser clients send JSON text messages containing DUML
frame hex, and the gateway relays BLE notification frames back as JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from rs3.protocol import build_native_rate_frame, build_velocity_frame, iter_embedded_frames  # noqa: E402
from rs3.transport.bleak_transport import BleakRS3Transport  # noqa: E402


DEFAULT_ADDRESS = "48:1C:B9:DC:8B:99"
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.write_lock = asyncio.Lock()

    async def handshake(self) -> None:
        request = await self.reader.readuntil(b"\r\n\r\n")
        lines = request.decode("latin1").split("\r\n")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        ws_key = headers.get("sec-websocket-key")
        if not ws_key:
            raise ValueError("missing Sec-WebSocket-Key")
        accept = base64.b64encode(hashlib.sha1((ws_key + GUID).encode("ascii")).digest()).decode("ascii")
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "\r\n"
        )
        self.writer.write(response.encode("ascii"))
        await self.writer.drain()

    async def read_text(self) -> str | None:
        header = await self.reader.readexactly(2)
        first, second = header
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", await self.reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", await self.reader.readexactly(8))[0]
        mask = await self.reader.readexactly(4) if masked else b""
        payload = bytearray(await self.reader.readexactly(length))
        if masked:
            for index, byte in enumerate(payload):
                payload[index] = byte ^ mask[index % 4]

        if opcode == 0x8:
            return None
        if opcode == 0x9:
            await self.write_frame(0xA, bytes(payload))
            return ""
        if opcode != 0x1:
            raise ValueError(f"unsupported websocket opcode {opcode}")
        return payload.decode("utf-8")

    async def write_json(self, message: dict[str, Any]) -> None:
        await self.write_text(json.dumps(message, separators=(",", ":")))

    async def write_text(self, text: str) -> None:
        await self.write_frame(0x1, text.encode("utf-8"))

    async def write_frame(self, opcode: int, payload: bytes) -> None:
        async with self.write_lock:
            header = bytearray([0x80 | opcode])
            length = len(payload)
            if length < 126:
                header.append(length)
            elif length <= 0xFFFF:
                header.append(126)
                header.extend(struct.pack("!H", length))
            else:
                header.append(127)
                header.extend(struct.pack("!Q", length))
            self.writer.write(bytes(header) + payload)
            await self.writer.drain()

    async def close(self) -> None:
        try:
            await self.write_frame(0x8, b"")
        except Exception:
            pass
        self.writer.close()
        await self.writer.wait_closed()


class GatewaySession:
    def __init__(self, websocket: WebSocketConnection, *, default_address: str, timeout: float) -> None:
        self.websocket = websocket
        self.default_address = default_address
        self.timeout = timeout
        self.transport: BleakRS3Transport | None = None
        self.sequence = 0x5000

    def next_sequence(self) -> int:
        sequence = self.sequence
        self.sequence = (self.sequence + 1) & 0xFFFF
        return sequence

    async def run(self) -> None:
        await self.websocket.write_json({"type": "status", "state": "disconnected"})
        while True:
            text = await self.websocket.read_text()
            if text is None:
                break
            if not text:
                continue
            try:
                message = json.loads(text)
                await self.handle_message(message)
            except Exception as exc:
                await self.websocket.write_json({"type": "error", "message": str(exc)})
        await self.disconnect()

    async def handle_message(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "connect":
            await self.connect(str(message.get("address") or self.default_address))
        elif kind == "disconnect":
            await self.disconnect()
        elif kind == "frame":
            await self.write_ble(bytes.fromhex(str(message.get("hex") or "")))
        elif kind == "stop":
            await self.send_stop()
        else:
            raise ValueError(f"unsupported message type: {kind}")

    async def connect(self, address: str) -> None:
        await self.disconnect()
        await self.websocket.write_json({"type": "status", "state": "connecting", "detail": address})
        self.transport = BleakRS3Transport(address, timeout=self.timeout)
        await self.transport.connect()
        await self.transport.start_notifications(self.on_ble_notification)
        await self.websocket.write_json({"type": "status", "state": "connected", "detail": address})

    async def disconnect(self) -> None:
        if self.transport is None:
            return
        try:
            await self.send_stop()
        except Exception:
            pass
        try:
            await self.transport.stop_notifications()
        except Exception:
            pass
        await self.transport.disconnect()
        self.transport = None
        await self.websocket.write_json({"type": "status", "state": "disconnected"})

    async def write_ble(self, frame: bytes) -> None:
        if self.transport is None:
            raise RuntimeError("BLE transport is not connected")
        await self.transport.write_frame(frame)

    async def send_stop(self) -> None:
        if self.transport is None:
            return
        await self.transport.write_frame(
            build_native_rate_frame(
                sequence=self.next_sequence(),
                tilt_deg_s=0.0,
                roll_deg_s=0.0,
                pan_deg_s=0.0,
                control_flags=0x00,
            )
        )
        for _ in range(3):
            await self.transport.write_frame(build_velocity_frame(sequence=self.next_sequence()))
            await asyncio.sleep(0.08)

    async def on_ble_notification(self, data: bytes) -> None:
        for frame in iter_embedded_frames(data):
            await self.websocket.write_json({"type": "frame", "hex": frame.hex()})


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    default_address: str,
    timeout: float,
) -> None:
    websocket = WebSocketConnection(reader, writer)
    session = GatewaySession(websocket, default_address=default_address, timeout=timeout)
    try:
        await websocket.handshake()
        await session.run()
    except asyncio.IncompleteReadError:
        await session.disconnect()
    except Exception as exc:
        try:
            await websocket.write_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
        await session.disconnect()
    finally:
        await websocket.close()


async def main_async(args: argparse.Namespace) -> None:
    server = await asyncio.start_server(
        lambda reader, writer: handle_client(
            reader,
            writer,
            default_address=args.address,
            timeout=args.timeout,
        ),
        args.host,
        args.port,
    )
    print(f"RS3 gateway listening on ws://{args.host}:{args.port}", flush=True)
    async with server:
        await server.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RS3 WebSocket/BLE gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser


def main() -> None:
    asyncio.run(main_async(build_parser().parse_args()))


if __name__ == "__main__":
    main()
