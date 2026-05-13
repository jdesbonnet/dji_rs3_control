import assert from "node:assert/strict";
import {
  buildAbsoluteAngleFrame,
  buildJoystickFrame,
  buildNativeRateFrame,
  buildNativeRateStopFrame,
  bytesToHex,
  parseFrame,
} from "./protocol.js";

assert.equal(
  bytesToHex(buildJoystickFrame(0x5000)),
  "551604fc020400504004010004000400040000023b6e",
);

assert.equal(
  bytesToHex(buildNativeRateFrame(0x5000, { panDegS: 20 })),
  "5514046d0204005040040cc80000000000808053",
);

assert.equal(
  bytesToHex(buildNativeRateFrame(0x5000, { panDegS: -10 })),
  "5514046d0204005040040c9cff000000008013b3",
);

assert.equal(
  bytesToHex(buildNativeRateStopFrame(0x5000)),
  "5514046d0204005040040c000000000000007f48",
);

const gotoFrame = buildAbsoluteAngleFrame(0x5000, { panDeg: 45, durationS: 2 });
const parsed = parseFrame(gotoFrame);
assert.equal(parsed.cmdSet, 0x04);
assert.equal(parsed.cmdId, 0x14);
assert.equal(parsed.payload.length, 8);
assert.equal(parsed.crc16Ok, true);
assert.equal(parsed.headerCrcOk, true);

console.log("protocol tests passed");
