const CRC8_INIT = 0x77;
const CRC16_INIT = 0x3692;
export const CENTER = 1024;

function crc8Table() {
  const table = [];
  for (let value = 0; value < 256; value += 1) {
    let crc = value;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = crc & 1 ? (crc >>> 1) ^ 0x8c : crc >>> 1;
    }
    table.push(crc & 0xff);
  }
  return table;
}

function crc16Table() {
  const table = [];
  for (let value = 0; value < 256; value += 1) {
    let crc = value;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = crc & 1 ? (crc >>> 1) ^ 0x8408 : crc >>> 1;
    }
    table.push(crc & 0xffff);
  }
  return table;
}

const CRC8_TABLE = crc8Table();
const CRC16_TABLE = crc16Table();

export function crc8(data, seed = CRC8_INIT) {
  let crc = seed;
  for (const byte of data) {
    crc = CRC8_TABLE[(crc ^ byte) & 0xff];
  }
  return crc;
}

export function crc16(data, seed = CRC16_INIT) {
  let crc = seed;
  for (const byte of data) {
    crc = ((crc >>> 8) ^ CRC16_TABLE[(crc ^ byte) & 0xff]) & 0xffff;
  }
  return crc;
}

export function bytesToHex(data) {
  return [...data].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function hexToBytes(hex) {
  const clean = hex.replace(/\s+/g, "");
  if (clean.length % 2 !== 0) {
    throw new Error("hex string must contain an even number of characters");
  }
  const output = new Uint8Array(clean.length / 2);
  for (let index = 0; index < output.length; index += 1) {
    output[index] = Number.parseInt(clean.slice(index * 2, index * 2 + 2), 16);
    if (Number.isNaN(output[index])) {
      throw new Error("invalid hex string");
    }
  }
  return output;
}

function u16le(value) {
  if (value < 0 || value > 0xffff) {
    throw new Error(`value outside u16 range: ${value}`);
  }
  return [value & 0xff, (value >>> 8) & 0xff];
}

function i16le(value) {
  if (value < -32768 || value > 32767) {
    throw new Error(`value outside int16 range: ${value}`);
  }
  const normalized = value < 0 ? value + 0x10000 : value;
  return [normalized & 0xff, (normalized >>> 8) & 0xff];
}

function readI16le(data, offset) {
  const value = data[offset] | (data[offset + 1] << 8);
  return value & 0x8000 ? value - 0x10000 : value;
}

function readI32le(data, offset) {
  return (
    data[offset] |
    (data[offset + 1] << 8) |
    (data[offset + 2] << 16) |
    (data[offset + 3] << 24)
  );
}

function tenths(value) {
  return Math.round(value * 10);
}

export function buildFrame({ sender = 0x02, receiver, sequence, cmdType = 0x40, cmdSet, cmdId, payload = [] }) {
  const body = payload instanceof Uint8Array ? payload : Uint8Array.from(payload);
  const length = 13 + body.length;
  if (length < 13 || length > 0x3ff) {
    throw new Error(`invalid DUML length: ${length}`);
  }
  const frame = new Uint8Array(length);
  frame[0] = 0x55;
  frame[1] = length & 0xff;
  frame[2] = 0x04 | ((length >>> 8) & 0x03);
  frame[3] = crc8(frame.slice(0, 3));
  frame[4] = sender & 0xff;
  frame[5] = receiver & 0xff;
  frame[6] = sequence & 0xff;
  frame[7] = (sequence >>> 8) & 0xff;
  frame[8] = cmdType & 0xff;
  frame[9] = cmdSet & 0xff;
  frame[10] = cmdId & 0xff;
  frame.set(body, 11);
  const checksum = crc16(frame.slice(0, -2));
  frame[length - 2] = checksum & 0xff;
  frame[length - 1] = (checksum >>> 8) & 0xff;
  return frame;
}

export function parseFrame(frame) {
  if (frame.length < 13 || frame[0] !== 0x55) {
    throw new Error("not a DJI 0x55 frame");
  }
  const length = frame[1] | ((frame[2] & 0x03) << 8);
  if (length !== frame.length) {
    throw new Error(`length mismatch: header=${length} actual=${frame.length}`);
  }
  const storedCrc = frame[frame.length - 2] | (frame[frame.length - 1] << 8);
  const calculatedCrc = crc16(frame.slice(0, -2));
  return {
    length,
    version: frame[2] >>> 2,
    headerCrcOk: frame[3] === crc8(frame.slice(0, 3)),
    crc16Ok: storedCrc === calculatedCrc,
    sender: frame[4],
    receiver: frame[5],
    sequence: frame[6] | (frame[7] << 8),
    cmdType: frame[8],
    cmdSet: frame[9],
    cmdId: frame[10],
    payload: frame.slice(11, -2),
  };
}

export function iterEmbeddedFrames(data) {
  const frames = [];
  let offset = 0;
  while (offset < data.length) {
    const start = data.indexOf(0x55, offset);
    if (start < 0 || start + 3 > data.length) {
      break;
    }
    const length = data[start + 1] | ((data[start + 2] & 0x03) << 8);
    if (length >= 13 && length <= 247 && start + length <= data.length) {
      frames.push(data.slice(start, start + length));
      offset = start + length;
    } else {
      offset = start + 1;
    }
  }
  return frames;
}

export function buildJoystickFrame(sequence, { tilt = 0, roll = 0, pan = 0 } = {}) {
  const payload = [
    ...u16le(clamp(CENTER + Math.round(tilt), 0, 0xffff)),
    ...u16le(clamp(CENTER + Math.round(roll), 0, 0xffff)),
    ...u16le(clamp(CENTER + Math.round(pan), 0, 0xffff)),
    ...u16le(0),
    0x02,
  ];
  return buildFrame({ receiver: 0x04, sequence, cmdSet: 0x04, cmdId: 0x01, payload });
}

export function buildNativeRateFrame(
  sequence,
  { tiltDegS = 0, rollDegS = 0, panDegS = 0, controlFlags = 0x80 } = {},
) {
  const payload = [
    ...i16le(tenths(panDegS)),
    ...i16le(tenths(rollDegS)),
    ...i16le(tenths(tiltDegS)),
    controlFlags & 0xff,
  ];
  return buildFrame({ receiver: 0x04, sequence, cmdSet: 0x04, cmdId: 0x0c, payload });
}

export function buildNativeRateStopFrame(sequence) {
  return buildNativeRateFrame(sequence, { controlFlags: 0x00 });
}

export function buildAbsoluteAngleFrame(
  sequence,
  { tiltDeg = 0, rollDeg = 0, panDeg = 0, durationS = 2.0, controlFlags = 0x01 } = {},
) {
  const durationTenths = clamp(Math.round(durationS * 10), 0, 0xff);
  const payload = [
    ...i16le(tenths(panDeg)),
    ...i16le(tenths(rollDeg)),
    ...i16le(tenths(tiltDeg)),
    controlFlags & 0xff,
    durationTenths,
  ];
  return buildFrame({ receiver: 0x04, sequence, cmdSet: 0x04, cmdId: 0x14, payload });
}

export function buildRecenterFrame(sequence) {
  return buildFrame({ receiver: 0x04, sequence, cmdSet: 0x04, cmdId: 0x4c, payload: [0xfe, 0x01] });
}

export function buildSleepFrame(sequence) {
  return buildFrame({ receiver: 0x04, sequence, cmdSet: 0x04, cmdId: 0x0f, payload: [0x23, 0x01, 0x01] });
}

export function buildWakeFrame(sequence) {
  return buildFrame({ receiver: 0x04, sequence, cmdSet: 0x04, cmdId: 0x0f, payload: [0x23, 0x01, 0x00] });
}

export function telemetryFromFrame(frame, previous = {}) {
  const info = parseFrame(frame);
  if (!info.crc16Ok || !info.headerCrcOk) {
    return null;
  }
  const next = { ...previous };
  if (info.cmdSet === 0x0d && info.cmdId === 0x02) {
    const values = decode0d02(info.payload);
    if (!values) {
      return null;
    }
    next.raw0d02 = values;
    next.batteryOrStatus = values[3];
    next.timestamp = performance.now();
    return next;
  }
  if (info.cmdSet === 0x04 && info.cmdId === 0x66) {
    const fields = decode0466(info.payload);
    if (!fields) {
      return null;
    }
    next.raw0466 = fields;
    if (fields.has(0x22) && fields.has(0x23) && fields.has(0x24)) {
      next.pose = {
        tiltDeg: fields.get(0x22) / 10,
        rollDeg: fields.get(0x23) / 10,
        panDeg: fields.get(0x24) / 10,
      };
      next.poseTimestamp = performance.now();
    }
    next.timestamp = performance.now();
    return next;
  }
  return null;
}

export function decode0d02(payload) {
  if (payload.length < 17) {
    return null;
  }
  return [1, 5, 9, 13].map((offset) => readI32le(payload, offset));
}

export function decode0466(payload) {
  if (payload.length === 0) {
    return null;
  }
  const fields = new Map();
  let offset = 1;
  while (offset + 2 <= payload.length) {
    const tag = payload[offset];
    const length = payload[offset + 1];
    offset += 2;
    if (offset + length > payload.length) {
      return null;
    }
    const raw = payload.slice(offset, offset + length);
    let value;
    if (length === 1) {
      value = raw[0] & 0x80 ? raw[0] - 0x100 : raw[0];
    } else if (length === 2) {
      value = readI16le(raw, 0);
    } else if (length === 4) {
      value = readI32le(raw, 0);
    } else {
      value = [...raw].reduce((result, byte, index) => result + (byte << (8 * index)), 0);
    }
    fields.set(tag, value);
    offset += length;
  }
  return fields;
}

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export class Sequencer {
  constructor(start = 0x5000) {
    this.value = start;
  }

  next() {
    const current = this.value;
    this.value = (this.value + 1) & 0xffff;
    return current;
  }
}
