"""Telemetry decoding helpers."""

from __future__ import annotations

from ..models import Pose, TelemetrySnapshot
from .duml import parse_frame


def iter_embedded_frames(data: bytes) -> list[bytes]:
    frames: list[bytes] = []
    offset = 0
    while offset < len(data):
        start = data.find(b"\x55", offset)
        if start < 0 or start + 3 > len(data):
            break
        length = data[start + 1] | ((data[start + 2] & 0x03) << 8)
        if 13 <= length <= 247 and start + length <= len(data):
            frames.append(data[start : start + length])
            offset = start + length
        else:
            offset = start + 1
    return frames


def decode_0d02_fields(payload: bytes) -> tuple[int, int, int, int] | None:
    if len(payload) < 17:
        return None
    return tuple(
        int.from_bytes(payload[index : index + 4], "little", signed=True)
        for index in (1, 5, 9, 13)
    )


def decode_0466_fields(payload: bytes) -> dict[int, int] | None:
    if not payload:
        return None
    fields: dict[int, int] = {}
    offset = 1
    while offset + 2 <= len(payload):
        tag = payload[offset]
        length = payload[offset + 1]
        offset += 2
        raw = payload[offset : offset + length]
        if len(raw) != length:
            return None
        fields[tag] = int.from_bytes(raw, "little", signed=True)
        offset += length
    return fields


def format_0466_fields(fields: dict[int, int]) -> str:
    return " ".join(f"{tag:02x}={fields[tag]}" for tag in sorted(fields))


def telemetry_from_frame(frame: bytes, previous: TelemetrySnapshot | None = None) -> TelemetrySnapshot | None:
    info = parse_frame(frame)
    cmd_set = int(info["cmd_set"])
    cmd_id = int(info["cmd_id"])
    payload = info["payload"]
    assert isinstance(payload, bytes)

    current = previous or TelemetrySnapshot()
    pose = current.pose
    battery = current.battery_or_status
    raw_0d02 = current.raw_0d02
    raw_0466 = dict(current.raw_0466)

    if cmd_set == 0x0D and cmd_id == 0x02:
        values = decode_0d02_fields(payload)
        if values is None:
            return None
        raw_0d02 = values
        battery = float(values[3])
    elif cmd_set == 0x04 and cmd_id == 0x66:
        fields = decode_0466_fields(payload)
        if fields is None:
            return None
        raw_0466 = fields
        if all(tag in fields for tag in (0x22, 0x23, 0x24)):
            pose = Pose(
                tilt_deg=fields[0x22] / 10.0,
                roll_deg=fields[0x23] / 10.0,
                pan_deg=fields[0x24] / 10.0,
            )
    else:
        return None

    return TelemetrySnapshot(
        pose=pose,
        battery_or_status=battery,
        raw_0d02=raw_0d02,
        raw_0466=raw_0466,
    )
