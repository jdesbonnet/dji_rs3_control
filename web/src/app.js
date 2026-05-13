import {
  Sequencer,
  buildAbsoluteAngleFrame,
  buildJoystickFrame,
  buildNativeRateFrame,
  buildNativeRateStopFrame,
  buildRecenterFrame,
  buildSleepFrame,
  buildWakeFrame,
  bytesToHex,
  clamp,
  parseFrame,
  telemetryFromFrame,
} from "./protocol.js";
import { WebBluetoothTransport, WebSocketGatewayTransport } from "./transports.js";

const $ = (id) => document.getElementById(id);

const elements = {
  summary: $("transport-summary"),
  state: $("connection-state"),
  battery: $("battery-value"),
  tilt: $("tilt-value"),
  roll: $("roll-value"),
  pan: $("pan-value"),
  age: $("telemetry-age"),
  poseRate: $("pose-rate"),
  connect: $("connect-button"),
  disconnect: $("disconnect-button"),
  stop: $("stop-button"),
  gatewayUrl: $("gateway-url"),
  bleAddress: $("ble-address"),
  bleService: $("ble-service"),
  log: $("log-output"),
  clearLog: $("clear-log-button"),
  joystickPad: $("joystick-pad"),
  joystickStick: $("joystick-stick"),
  joyTilt: $("joy-tilt"),
  joyPan: $("joy-pan"),
  joystickMax: $("joystick-max"),
  gotoTilt: $("goto-tilt"),
  gotoRoll: $("goto-roll"),
  gotoPan: $("goto-pan"),
  gotoDuration: $("goto-duration"),
  gotoButton: $("goto-button"),
  rateTilt: $("rate-tilt"),
  rateRoll: $("rate-roll"),
  ratePan: $("rate-pan"),
  rateSeconds: $("rate-seconds"),
  rateButton: $("rate-button"),
  recenter: $("recenter-button"),
  sleep: $("sleep-button"),
  wake: $("wake-button"),
};

const state = {
  transport: null,
  sequencer: new Sequencer(),
  telemetry: {},
  poseSamples: [],
  connected: false,
  writeQueue: Promise.resolve(),
  joystick: {
    active: false,
    tilt: 0,
    pan: 0,
    timer: null,
  },
};

function selectedMode() {
  return document.querySelector("input[name='mode']:checked")?.value || "gateway";
}

function numberValue(element, fallback = 0) {
  const value = Number.parseFloat(element.value);
  return Number.isFinite(value) ? value : fallback;
}

function setConnected(connected) {
  state.connected = connected;
  elements.connect.disabled = connected;
  elements.disconnect.disabled = !connected;
}

function setStatus(status) {
  elements.state.textContent = status.state;
  const detail = status.detail ? ` ${status.detail}` : "";
  elements.summary.textContent = `${status.state}${detail}`;
  if (status.state === "connecting") {
    elements.connect.disabled = true;
    elements.disconnect.disabled = false;
  }
  if (status.state === "connected") {
    setConnected(true);
  }
  if (status.state === "disconnected") {
    setConnected(false);
  }
  if (status.state === "error") {
    logLine(`error ${status.message || "unknown error"}`);
  }
}

function logLine(line) {
  const time = new Date().toLocaleTimeString();
  elements.log.textContent += `${time} ${line}\n`;
  elements.log.scrollTop = elements.log.scrollHeight;
}

function updateTelemetry(frame) {
  let info;
  try {
    info = parseFrame(frame);
  } catch (error) {
    logLine(`drop ${error.message}`);
    return;
  }

  const nextTelemetry = telemetryFromFrame(frame, state.telemetry);
  if (nextTelemetry) {
    if (nextTelemetry.poseTimestamp && nextTelemetry.poseTimestamp !== state.telemetry.poseTimestamp) {
      recordPoseSample(nextTelemetry.poseTimestamp);
    }
    state.telemetry = nextTelemetry;
    renderTelemetry();
    return;
  }

  if (info.cmdType === 0x80) {
    logLine(`ack ${info.cmdSet.toString(16).padStart(2, "0")}/${info.cmdId.toString(16).padStart(2, "0")} ${bytesToHex(info.payload)}`);
  }
}

function renderTelemetry() {
  const { pose, batteryOrStatus, poseTimestamp } = state.telemetry;
  if (pose) {
    elements.tilt.textContent = pose.tiltDeg.toFixed(1);
    elements.roll.textContent = pose.rollDeg.toFixed(1);
    elements.pan.textContent = pose.panDeg.toFixed(1);
  }
  if (batteryOrStatus !== undefined) {
    elements.battery.textContent = String(batteryOrStatus);
  }
  if (poseTimestamp) {
    elements.age.textContent = `${((performance.now() - poseTimestamp) / 1000).toFixed(1)}s`;
  }
  elements.poseRate.textContent = formatPoseRate();
}

function recordPoseSample(timestamp) {
  state.poseSamples.push(timestamp);
  const cutoff = performance.now() - 3000;
  while (state.poseSamples.length && state.poseSamples[0] < cutoff) {
    state.poseSamples.shift();
  }
}

function formatPoseRate() {
  const cutoff = performance.now() - 3000;
  while (state.poseSamples.length && state.poseSamples[0] < cutoff) {
    state.poseSamples.shift();
  }
  if (state.poseSamples.length < 2) {
    return "--";
  }
  const spanSeconds = (state.poseSamples[state.poseSamples.length - 1] - state.poseSamples[0]) / 1000;
  if (spanSeconds <= 0) {
    return "--";
  }
  return `${((state.poseSamples.length - 1) / spanSeconds).toFixed(1)} Hz`;
}

async function writeFrame(label, frame) {
  if (!state.transport || !state.connected) {
    throw new Error("not connected");
  }
  await queueFrameWrite(label, frame, { log: true });
}

async function queueFrameWrite(label, frame, { log = true } = {}) {
  const write = async () => {
    if (!state.transport || !state.connected) {
      throw new Error("not connected");
    }
    await state.transport.writeFrame(frame);
    if (log) {
      logLine(`tx ${label} ${bytesToHex(frame)}`);
    }
  };
  state.writeQueue = state.writeQueue.then(write, write);
  return state.writeQueue;
}

async function sendStop() {
  if (!state.transport || !state.connected) {
    return;
  }
  await writeFrame("rate-stop", buildNativeRateStopFrame(state.sequencer.next()));
  for (let index = 0; index < 3; index += 1) {
    await writeFrame("neutral", buildJoystickFrame(state.sequencer.next()));
    await delay(80);
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function connect() {
  const mode = selectedMode();
  const transport =
    mode === "ble"
      ? new WebBluetoothTransport({ serviceUuid: elements.bleService.value.trim() })
      : new WebSocketGatewayTransport({ url: elements.gatewayUrl.value.trim() });

  transport.onStatus(setStatus);
  transport.onFrame(updateTelemetry);
  state.transport = transport;

  try {
    await transport.connect({ address: elements.bleAddress.value.trim() });
    state.poseSamples = [];
    logLine(`connected ${mode}`);
  } catch (error) {
    setStatus({ state: "error", message: error.message });
    setConnected(false);
  }
}

async function disconnect() {
  try {
    await sendStop();
  } catch (error) {
    logLine(`stop failed ${error.message}`);
  }
  if (state.transport) {
    await state.transport.disconnect();
  }
  state.transport = null;
  setConnected(false);
}

async function sendGoto() {
  const durationS = numberValue(elements.gotoDuration, 2);
  const frame = buildAbsoluteAngleFrame(state.sequencer.next(), {
    tiltDeg: numberValue(elements.gotoTilt),
    rollDeg: numberValue(elements.gotoRoll),
    panDeg: numberValue(elements.gotoPan),
    durationS,
  });
  await writeFrame("goto", frame);
}

async function sendRate() {
  const tiltDegS = numberValue(elements.rateTilt);
  const rollDegS = numberValue(elements.rateRoll);
  const panDegS = numberValue(elements.ratePan);
  const seconds = clamp(numberValue(elements.rateSeconds, 0.5), 0, 5);
  if (tiltDegS < 0 || rollDegS < 0) {
    throw new Error("negative tilt/roll native rates are not validated");
  }
  await runRate({ tiltDegS, rollDegS, panDegS, seconds });
}

async function runRate({ tiltDegS, rollDegS, panDegS, seconds }) {
  const intervalMs = 200;
  const deadline = performance.now() + seconds * 1000;
  try {
    while (performance.now() < deadline) {
      await writeFrame(
        "rate",
        buildNativeRateFrame(state.sequencer.next(), { tiltDegS, rollDegS, panDegS }),
      );
      await delay(Math.min(intervalMs, Math.max(0, deadline - performance.now())));
    }
  } finally {
    await writeFrame("rate-stop", buildNativeRateStopFrame(state.sequencer.next()));
  }
}

async function sendUtility(kind) {
  const sequence = state.sequencer.next();
  const frame =
    kind === "recenter"
      ? buildRecenterFrame(sequence)
      : kind === "sleep"
        ? buildSleepFrame(sequence)
        : buildWakeFrame(sequence);
  await writeFrame(kind, frame);
}

function joystickPoint(event) {
  const rect = elements.joystickPad.getBoundingClientRect();
  const radius = Math.min(rect.width, rect.height) / 2;
  const x = clamp(event.clientX - rect.left - radius, -radius, radius);
  const y = clamp(event.clientY - rect.top - radius, -radius, radius);
  const distance = Math.hypot(x, y);
  const scale = distance > radius ? radius / distance : 1;
  return { x: x * scale, y: y * scale, radius };
}

function setJoystickVisual(x, y) {
  elements.joystickStick.style.transform = `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`;
}

function updateJoystick(event) {
  const { x, y, radius } = joystickPoint(event);
  const maxDelta = clamp(numberValue(elements.joystickMax, 220), 20, 700);
  const deadZone = radius * 0.08;
  const pan = Math.abs(x) < deadZone ? 0 : Math.round((x / radius) * maxDelta);
  const tilt = Math.abs(y) < deadZone ? 0 : Math.round((-y / radius) * maxDelta);
  state.joystick.pan = pan;
  state.joystick.tilt = tilt;
  elements.joyPan.textContent = String(pan);
  elements.joyTilt.textContent = String(tilt);
  setJoystickVisual(x, y);
}

function startJoystick(event) {
  if (!state.connected) {
    return;
  }
  state.joystick.active = true;
  elements.joystickPad.setPointerCapture(event.pointerId);
  updateJoystick(event);
  if (!state.joystick.timer) {
    state.joystick.timer = setInterval(async () => {
      if (!state.joystick.active) {
        return;
      }
      try {
        await writeFrame(
          "joystick",
          buildJoystickFrame(state.sequencer.next(), {
            tilt: state.joystick.tilt,
            pan: state.joystick.pan,
          }),
        );
      } catch (error) {
        logLine(`joystick failed ${error.message}`);
      }
    }, 200);
  }
}

async function stopJoystick() {
  state.joystick.active = false;
  state.joystick.tilt = 0;
  state.joystick.pan = 0;
  elements.joyPan.textContent = "0";
  elements.joyTilt.textContent = "0";
  setJoystickVisual(0, 0);
  if (state.joystick.timer) {
    clearInterval(state.joystick.timer);
    state.joystick.timer = null;
  }
  if (state.connected) {
    for (let index = 0; index < 3; index += 1) {
      await writeFrame("neutral", buildJoystickFrame(state.sequencer.next()));
      await delay(80);
    }
  }
}

function bindButton(element, action) {
  element.addEventListener("click", async () => {
    try {
      await action();
    } catch (error) {
      logLine(`error ${error.message}`);
    }
  });
}

elements.connect.addEventListener("click", connect);
elements.disconnect.addEventListener("click", disconnect);
bindButton(elements.stop, sendStop);
bindButton(elements.gotoButton, sendGoto);
bindButton(elements.rateButton, sendRate);
bindButton(elements.recenter, () => sendUtility("recenter"));
bindButton(elements.sleep, () => sendUtility("sleep"));
bindButton(elements.wake, () => sendUtility("wake"));
elements.clearLog.addEventListener("click", () => {
  elements.log.textContent = "";
});

elements.joystickPad.addEventListener("pointerdown", startJoystick);
elements.joystickPad.addEventListener("pointermove", (event) => {
  if (state.joystick.active) {
    updateJoystick(event);
  }
});
elements.joystickPad.addEventListener("pointerup", stopJoystick);
elements.joystickPad.addEventListener("pointercancel", stopJoystick);
elements.joystickPad.addEventListener("lostpointercapture", () => {
  if (state.joystick.active) {
    stopJoystick();
  }
});

window.addEventListener("beforeunload", () => {
  if (state.transport && state.connected) {
    const frame = buildNativeRateStopFrame(state.sequencer.next());
    state.transport.writeFrame(frame).catch(() => {});
  }
});

setInterval(renderTelemetry, 100);
setConnected(false);
