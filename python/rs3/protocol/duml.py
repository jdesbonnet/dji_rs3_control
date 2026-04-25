"""DJI DUML frame primitives used by the RS3 BLE transport."""

from __future__ import annotations


CRC8_INIT = 0x77
CRC16_INIT = 0x3692


def _crc8_table() -> list[int]:
    table: list[int] = []
    for value in range(256):
        crc = value
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
        table.append(crc & 0xFF)
    return table


def _crc16_table() -> list[int]:
    table: list[int] = []
    for value in range(256):
        crc = value
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
        table.append(crc & 0xFFFF)
    return table


CRC8_TABLE = _crc8_table()
CRC16_TABLE = _crc16_table()


def crc8(data: bytes, seed: int = CRC8_INIT) -> int:
    crc = seed
    for byte in data:
        crc = CRC8_TABLE[(crc ^ byte) & 0xFF]
    return crc


def crc16(data: bytes, seed: int = CRC16_INIT) -> int:
    crc = seed
    for byte in data:
        crc = ((crc >> 8) ^ CRC16_TABLE[(crc ^ byte) & 0xFF]) & 0xFFFF
    return crc


def build_frame(
    *,
    sender: int,
    receiver: int,
    sequence: int,
    cmd_type: int,
    cmd_set: int,
    cmd_id: int,
    payload: bytes = b"",
) -> bytes:
    length = 13 + len(payload)
    if not 0 <= length <= 0x3FF:
        raise ValueError(f"invalid DUML length: {length}")

    version_and_len_hi = 0x04 | ((length >> 8) & 0x03)
    frame = bytearray([0x55, length & 0xFF, version_and_len_hi])
    frame.append(crc8(frame))
    frame.extend(
        [
            sender & 0xFF,
            receiver & 0xFF,
            sequence & 0xFF,
            (sequence >> 8) & 0xFF,
            cmd_type & 0xFF,
            cmd_set & 0xFF,
            cmd_id & 0xFF,
        ]
    )
    frame.extend(payload)
    checksum = crc16(frame)
    frame.extend([checksum & 0xFF, (checksum >> 8) & 0xFF])
    return bytes(frame)


def joystick_payload(
    *,
    axis0: int = 1024,
    axis1: int = 1024,
    axis2: int = 1024,
    flags: int = 0,
    mode: int = 2,
) -> bytes:
    payload = bytearray()
    for value in (axis0, axis1, axis2, flags):
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"joystick value outside u16 range: {value}")
        payload.extend(value.to_bytes(2, "little"))
    payload.append(mode & 0xFF)
    return bytes(payload)


def build_joystick_frame(
    *,
    sequence: int,
    axis0: int = 1024,
    axis1: int = 1024,
    axis2: int = 1024,
    flags: int = 0,
    mode: int = 2,
) -> bytes:
    return build_frame(
        sender=0x02,
        receiver=0x04,
        sequence=sequence,
        cmd_type=0x40,
        cmd_set=0x04,
        cmd_id=0x01,
        payload=joystick_payload(
            axis0=axis0,
            axis1=axis1,
            axis2=axis2,
            flags=flags,
            mode=mode,
        ),
    )


def parse_frame(frame: bytes) -> dict[str, object]:
    if len(frame) < 13 or frame[0] != 0x55:
        raise ValueError("not a DJI 0x55 frame")
    length = frame[1] | ((frame[2] & 0x03) << 8)
    if length != len(frame):
        raise ValueError(f"length mismatch: header={length} actual={len(frame)}")

    stored_header_crc = frame[3]
    calculated_header_crc = crc8(frame[:3])
    stored_crc = frame[-2] | (frame[-1] << 8)
    calculated_crc = crc16(frame[:-2])

    return {
        "length": length,
        "version": frame[2] >> 2,
        "header_crc_ok": stored_header_crc == calculated_header_crc,
        "crc16_ok": stored_crc == calculated_crc,
        "sender": frame[4],
        "receiver": frame[5],
        "sequence": frame[6] | (frame[7] << 8),
        "cmd_type": frame[8],
        "cmd_set": frame[9],
        "cmd_id": frame[10],
        "payload": frame[11:-2],
    }
