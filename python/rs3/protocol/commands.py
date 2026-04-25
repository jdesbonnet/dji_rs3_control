"""RS3-specific command builders on top of DUML."""

from __future__ import annotations

from dataclasses import dataclass

from .duml import build_frame, build_joystick_frame


CENTER = 1024


@dataclass(frozen=True)
class Command:
    receiver: int
    cmd_type: int
    cmd_set: int
    cmd_id: int
    payload: bytes = b""


APP_INIT_COMMANDS = [
    Command(0x04, 0x40, 0x00, 0x01),
    Command(0x04, 0x40, 0x00, 0x01),
    Command(0xE5, 0x40, 0x0D, 0x01, bytes.fromhex("000000000000000000")),
    Command(0x27, 0x40, 0x07, 0x0E),
    Command(0x27, 0x40, 0x00, 0x01),
    Command(0xE5, 0x40, 0x00, 0x4F, bytes.fromhex("0100000000ffffffff")),
    Command(0xE5, 0x40, 0x00, 0x32, bytes.fromhex("11")),
    Command(0xE5, 0x40, 0x00, 0x32, bytes.fromhex("11")),
    Command(0xE5, 0x40, 0x00, 0x4F, bytes.fromhex("0100010000ffffffff")),
    Command(0x04, 0x40, 0x00, 0x01),
    Command(0x44, 0x40, 0x00, 0x01),
    Command(0xE5, 0x40, 0x00, 0x4F, bytes.fromhex("0100020000ffffffff")),
    Command(0xE5, 0x40, 0x00, 0x01),
    Command(0x26, 0x40, 0x00, 0x01),
    Command(0x27, 0x40, 0x07, 0x07),
    Command(0xBF, 0x40, 0x00, 0x01),
    Command(0x0B, 0x40, 0x00, 0x01),
    Command(0x32, 0x40, 0x00, 0x01),
]


APP_POLL_PAYLOADS = [
    bytes.fromhex("660cc01d108401000e000c000050000000000000000010"),
    bytes.fromhex("660cc01d103e010000000c000050"),
    bytes.fromhex("6624c01d00001c1051010000000c00005000f103"),
]


def clamp_axis(value: int) -> int:
    return max(0, min(0xFFFF, value))


def int16_bytes(value: int) -> bytes:
    if not -32768 <= value <= 32767:
        raise ValueError(f"value out of int16 range: {value}")
    return value.to_bytes(2, "little", signed=True)


def degrees_to_tenths(angle_deg: float) -> int:
    return int(round(angle_deg * 10.0))


def axis_values_for_direction(direction: str, delta: int) -> tuple[int, int, int]:
    axis0 = axis1 = axis2 = CENTER
    if direction == "left":
        axis2 -= delta
    elif direction == "right":
        axis2 += delta
    elif direction == "up":
        axis0 += delta
    elif direction == "down":
        axis0 -= delta
    elif direction == "axis0":
        axis0 -= delta
    elif direction == "axis1":
        axis1 -= delta
    elif direction == "axis2":
        axis2 -= delta
    else:
        raise ValueError(f"unknown direction: {direction}")
    return axis0, axis1, axis2


def build_command_frame(command: Command, *, sender: int = 0x02, sequence: int) -> bytes:
    return build_frame(
        sender=sender,
        receiver=command.receiver,
        sequence=sequence,
        cmd_type=command.cmd_type,
        cmd_set=command.cmd_set,
        cmd_id=command.cmd_id,
        payload=command.payload,
    )


def build_velocity_frame(*, sequence: int, tilt: int = 0, roll: int = 0, pan: int = 0) -> bytes:
    return build_joystick_frame(
        sequence=sequence,
        axis0=clamp_axis(CENTER + tilt),
        axis1=clamp_axis(CENTER + roll),
        axis2=clamp_axis(CENTER + pan),
    )


def build_recenter_frame(*, sequence: int) -> bytes:
    return build_frame(
        sender=0x02,
        receiver=0x04,
        sequence=sequence,
        cmd_type=0x40,
        cmd_set=0x04,
        cmd_id=0x4C,
        payload=bytes.fromhex("fe01"),
    )


def build_keepalive_0410_frame(*, sequence: int) -> bytes:
    return build_frame(
        sender=0x02,
        receiver=0x04,
        sequence=sequence,
        cmd_type=0x40,
        cmd_set=0x04,
        cmd_id=0x10,
        payload=bytes.fromhex("12"),
    )


def build_track_payload(
    waypoints_deg: list[tuple[float, float, float]],
    *,
    mode: int = 0x0A,
    param0: int = 20,
    param1: int = 20,
) -> bytes:
    if not 0 <= mode <= 0xFF:
        raise ValueError("track mode must fit in one byte")
    if not waypoints_deg:
        raise ValueError("at least one waypoint is required")
    if len(waypoints_deg) > 0xFF:
        raise ValueError("too many waypoints")

    payload = bytearray([mode, len(waypoints_deg)])
    for tilt_deg, roll_deg, pan_deg in waypoints_deg:
        payload.extend(int16_bytes(param0))
        payload.extend(int16_bytes(param1))
        payload.extend(int16_bytes(degrees_to_tenths(roll_deg)))
        payload.extend(int16_bytes(degrees_to_tenths(tilt_deg)))
        payload.extend(int16_bytes(degrees_to_tenths(pan_deg)))
    return bytes(payload)


def build_track_frame(
    waypoints_deg: list[tuple[float, float, float]],
    *,
    sequence: int,
    mode: int = 0x0A,
    param0: int = 20,
    param1: int = 20,
) -> bytes:
    return build_frame(
        sender=0x02,
        receiver=0x04,
        sequence=sequence,
        cmd_type=0x40,
        cmd_set=0x04,
        cmd_id=0x62,
        payload=build_track_payload(waypoints_deg, mode=mode, param0=param0, param1=param1),
    )


def parse_waypoint_text(text: str) -> tuple[float, float, float]:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) == 2:
        tilt_text, pan_text = parts
        roll_text = "0"
    elif len(parts) == 3:
        tilt_text, roll_text, pan_text = parts
    else:
        raise ValueError("waypoint must be tilt,pan or tilt,roll,pan")
    return float(tilt_text), float(roll_text), float(pan_text)
