# RS3 Single Page Web App Implementation Plan

## 1. Goal

Build a single page web app for controlling a DJI RS3 gimbal from a browser.
The app must support two transport modes:

1. Browser Web Bluetooth API direct to the gimbal.
2. WebSocket connection to a local BLE gateway.

The UI must provide:

- connection mode selection
- connection status and command/telemetry errors
- live gimbal status, including battery/status and tilt/roll/pan angles
- virtual joystick control
- native angular-rate control where appropriate
- go-to-angle control
- safe stop / neutral behavior

## 2. Current Protocol Assets

Use the existing Python work as the protocol reference:

| Capability | Protocol command | Existing implementation |
| --- | --- | --- |
| BLE notify characteristic | `0000fff4-0000-1000-8000-00805f9b34fb` | `python/rs3/transport/bleak_transport.py` |
| BLE write characteristic | `0000fff5-0000-1000-8000-00805f9b34fb` | `python/rs3/transport/bleak_transport.py` |
| Joystick-style motion | `0x04/0x01` | `build_velocity_frame()` |
| Native angular rate | `0x04/0x0c` | `build_native_rate_frame()` |
| Absolute go-to angle | `0x04/0x14` | `build_absolute_angle_frame()` |
| Recenter | `0x04/0x4c` | `build_recenter_frame()` |
| Sleep/wake | `0x04/0x0f` | `build_sleep_frame()`, `build_wake_frame()` |
| Track waypoint program | `0x04/0x62` | `build_track_frame()` |
| Pose telemetry | `0x04/0x66` | `decode_0466_fields()` |
| Status telemetry | `0x0d/0x02` | `decode_0d02_fields()` |

The web implementation should port only the needed protocol helpers first:

- DUML frame encode/decode
- CRC helpers
- telemetry decoding
- joystick command builder
- native rate command builder
- absolute angle command builder
- sleep/wake/recenter command builders

## 3. Architecture

### 3.1 Frontend App

Recommended stack:

- TypeScript
- Vite
- React or plain TypeScript components
- CSS modules or a small local stylesheet
- No server-side rendering

The app should be usable from `localhost` during development. Direct Web
Bluetooth requires a secure context, which includes `localhost` and HTTPS.

Frontend modules:

| Module | Responsibility |
| --- | --- |
| `protocol/duml.ts` | DUML frame building/parsing and CRC logic |
| `protocol/commands.ts` | RS3 command frame builders |
| `protocol/telemetry.ts` | telemetry frame decoding into app state |
| `transport/transport.ts` | common transport interface |
| `transport/webBluetooth.ts` | browser BLE transport |
| `transport/webSocketGateway.ts` | WebSocket client transport |
| `state/gimbalStore.ts` | connection, telemetry, command state |
| `components/ConnectionPanel.tsx` | choose BLE vs gateway and connect/disconnect |
| `components/StatusPanel.tsx` | battery/status, angles, transport status |
| `components/Joystick.tsx` | pointer/touch virtual joystick |
| `components/GotoPanel.tsx` | absolute angle form |
| `components/CommandBar.tsx` | stop, recenter, sleep, wake |

### 3.2 Transport Interface

Both browser BLE and WebSocket gateway transports should implement the same
interface:

```ts
export interface Rs3Transport {
  readonly kind: "web-bluetooth" | "websocket-gateway";
  connect(): Promise<void>;
  disconnect(): Promise<void>;
  writeFrame(frame: Uint8Array): Promise<void>;
  onFrame(callback: (frame: Uint8Array) => void): () => void;
  onStatus(callback: (status: TransportStatus) => void): () => void;
}
```

Transport status should include:

```ts
export type TransportStatus =
  | { state: "disconnected" }
  | { state: "connecting" }
  | { state: "connected" }
  | { state: "error"; message: string };
```

### 3.3 WebSocket Gateway

The gateway should be a thin local service. Prefer Python because the existing
BLE library already works.

Gateway responsibilities:

- connect to the RS3 using the existing Python BLE transport
- expose a WebSocket server on localhost
- relay browser-originated DUML frames to BLE write characteristic
- relay BLE notification DUML frames to the browser
- optionally provide a small JSON status envelope around binary frames

Recommended WebSocket message types:

```json
{ "type": "connect", "address": "48:1C:B9:DC:8B:99" }
{ "type": "disconnect" }
{ "type": "frame", "hex": "551404..." }
{ "type": "status", "state": "connected" }
{ "type": "error", "message": "..." }
```

Binary WebSocket frames can be added later. JSON with hex is simpler for
debugging and good enough for this control rate.

## 4. Safety Requirements

Safety behavior is part of the product, not an optional enhancement.

- Always provide a prominent stop button.
- Stop sends:
  - native rate zero/release frame `0x04/0x0c payload=00000000000000`
  - several neutral joystick frames `0x04/0x01`
- On pointer release from joystick, send neutral joystick frames.
- On transport disconnect, page unload, or visibility loss, attempt stop.
- Clamp joystick values to a conservative range by default.
- Clamp native rate values to a conservative range by default.
- Keep negative tilt/roll native rate disabled until validated.
- Show when a command is blocked by validation instead of silently ignoring it.

## 5. User Experience

The app should be a compact control panel, not a marketing page.

Recommended layout:

- left column: connection and status
- center: virtual joystick and stop button
- right column: go-to-angle and utility commands
- bottom strip: command log / diagnostics

Status display:

| Field | Source | Display |
| --- | --- | --- |
| Connection mode | app state | Web Bluetooth / Gateway |
| BLE state | transport | disconnected / connecting / connected / error |
| Tilt | `0x04/0x66` tag `0x22` | degrees, one decimal |
| Roll | `0x04/0x66` tag `0x23` | degrees, one decimal |
| Pan | `0x04/0x66` tag `0x24` | degrees, one decimal |
| Battery/status | `0x0d/0x02` decoded field | raw value first, refine later |
| Last telemetry age | timestamp | seconds |

Virtual joystick:

- Pointer/touch drag from center.
- X axis controls pan/yaw.
- Y axis controls tilt/pitch.
- Optional roll slider or separate horizontal control.
- Dead zone around center.
- Sends joystick frames at `5 Hz` while active.
- Sends neutral frames on release.

Go-to-angle:

- Numeric inputs for tilt, roll, pan in degrees.
- Duration input in seconds.
- Send `0x04/0x14`.
- Display the generated command summary and last ACK/error.

## 6. Agent Work Plan

Each agent should own a narrow, non-overlapping slice. Agents should not rewrite
files owned by another agent.

### Agent 1: Project Scaffold

Ownership:

- `web/package.json`
- `web/index.html`
- `web/src/main.tsx`
- `web/src/App.tsx`
- `web/src/styles.css`
- `web/tsconfig.json`
- `web/vite.config.ts`

Tasks:

- Create a Vite TypeScript SPA.
- Add minimal build/test scripts.
- Build the first-screen app shell.
- Add responsive layout containers.
- Leave transport/protocol logic as imported stubs if other agents are working
  in parallel.

Done when:

- `npm install` succeeds.
- `npm run build` succeeds.
- App shell renders connection, status, joystick, and go-to sections.

### Agent 2: Protocol Port

Ownership:

- `web/src/protocol/duml.ts`
- `web/src/protocol/commands.ts`
- `web/src/protocol/telemetry.ts`
- `web/src/protocol/types.ts`

Tasks:

- Port DUML frame encode/decode from Python.
- Port CRC8/CRC16 logic.
- Implement command builders for:
  - joystick neutral and axis movement
  - native rate
  - absolute angle
  - recenter
  - sleep/wake
- Implement telemetry parsing for:
  - `0x04/0x66`
  - `0x0d/0x02`
- Add pure unit tests using known frame examples from protocol docs.

Done when:

- Known Python-generated frames match TypeScript-generated frames.
- Telemetry examples decode to the same fields as Python.
- Invalid CRC/length frames are rejected.

### Agent 3: Transport Layer

Ownership:

- `web/src/transport/transport.ts`
- `web/src/transport/webBluetooth.ts`
- `web/src/transport/webSocketGateway.ts`

Tasks:

- Define common transport interface.
- Implement Web Bluetooth direct connection:
  - request device
  - connect GATT
  - find service/characteristics
  - subscribe to notifications
  - write frames
- Implement WebSocket gateway client:
  - connect/disconnect
  - send frame messages
  - receive frame/status/error messages
- Normalize errors for UI display.

Done when:

- App can instantiate either transport from the same interface.
- Incoming frames flow to the same callback path.
- Transport state changes are observable.

### Agent 4: Gateway Service

Ownership:

- `web/gateway/`
- optional `web/README.md` gateway section

Tasks:

- Build a Python WebSocket-to-BLE gateway using the existing `python/rs3`
  library.
- Accept JSON commands:
  - `connect`
  - `disconnect`
  - `frame`
- Emit JSON events:
  - `status`
  - `frame`
  - `error`
- Add command-line options for BLE address, host, and port.
- Preserve safety behavior on disconnect.

Done when:

- Browser can send a DUML frame through WebSocket and receive notification
  frames back.
- Gateway exits cleanly.
- Gateway sends stop/neutral on disconnect if connected.

### Agent 5: App State and Command Orchestration

Ownership:

- `web/src/state/`
- `web/src/hooks/`

Tasks:

- Create central gimbal state:
  - selected transport
  - connection state
  - latest telemetry
  - last command
  - command log
  - errors
- Wire transport frame callbacks to telemetry parser.
- Implement command send helpers:
  - `sendStop()`
  - `sendJoystick()`
  - `sendNativeRate()`
  - `sendGoto()`
  - `sendRecenter()`
  - `sendSleep()`
  - `sendWake()`
- Enforce safety clamps before writing frames.

Done when:

- UI components can call command helpers without knowing transport details.
- Telemetry updates are reflected in state.
- Stop is available even after command errors if transport remains connected.

### Agent 6: UI Components

Ownership:

- `web/src/components/ConnectionPanel.tsx`
- `web/src/components/StatusPanel.tsx`
- `web/src/components/Joystick.tsx`
- `web/src/components/GotoPanel.tsx`
- `web/src/components/CommandBar.tsx`
- `web/src/components/LogPanel.tsx`

Tasks:

- Implement connection mode selector.
- Implement live status cards or dense status rows.
- Implement virtual joystick with pointer events.
- Implement go-to-angle form.
- Implement stop/recenter/sleep/wake controls.
- Implement command log and error display.
- Keep controls ergonomic on desktop and mobile.

Done when:

- All controls are reachable by keyboard/mouse/touch.
- Text fits at mobile and desktop sizes.
- Stop button remains visible while connected.

### Agent 7: Integration and Hardware Validation

Ownership:

- validation scripts/docs only unless fixing integration bugs

Tasks:

- Validate WebSocket gateway flow first.
- Validate browser BLE flow on Chromium.
- Run hardware checks:
  - connect/disconnect
  - telemetry updates
  - joystick pan small left/right
  - joystick tilt small up/down
  - native rate positive/negative pan
  - go-to angle small pan move
  - stop while moving
  - recenter
- Record exact commands and observed telemetry in a validation log.

Done when:

- The app can safely control the gimbal through both transports.
- Known browser limitations are documented.
- Any unsafe/unvalidated control remains hidden or explicitly gated.

## 7. Implementation Order

Recommended sequence:

1. Scaffold the SPA.
2. Port protocol helpers with tests.
3. Build WebSocket gateway and gateway transport.
4. Wire state and command orchestration against gateway transport.
5. Build UI components against state.
6. Add Web Bluetooth direct transport.
7. Perform hardware validation.
8. Polish layout and diagnostics.

This order gives the team a debuggable local gateway path before dealing with
browser Web Bluetooth constraints.

## 8. Validation Checklist

Protocol:

- TypeScript command frame hex matches Python for representative commands.
- CRC errors are detected.
- Telemetry frames decode consistently with Python.

Gateway:

- Connects to BLE.
- Forwards browser commands to BLE.
- Forwards BLE notifications to browser.
- Sends stop behavior on disconnect.

UI:

- Direct BLE mode can connect on supported browsers.
- Gateway mode can connect through local WebSocket.
- Status panel updates in real time.
- Joystick stops on pointer release.
- Stop button stops native rate and joystick movement.
- Go-to command moves to requested angle without LCD preview message.

Hardware:

- Small joystick pan motion works.
- Small joystick tilt motion works.
- Native rate positive pan works.
- Native rate negative pan works.
- Go-to pan works.
- Recenter works.
- Sleep/wake works.

## 9. Open Questions

- Should roll controls be visible by default or placed behind an advanced mode?
- Should native tilt/roll rate remain disabled until directly validated?
- Should the gateway expose raw DUML frames for debugging in the UI?
- Should telemetry polling be automatic, passive, or user selectable?
- Should browser BLE mode support remembered devices where the browser allows it?

## 10. Definition of Done

The web app is done when:

- A user can open one page and choose Web Bluetooth or WebSocket gateway.
- The app shows current pose/status while connected.
- The user can move the gimbal with a virtual joystick.
- The user can command a specific absolute angle.
- The user can stop motion immediately.
- The app has conservative clamps and documented unsafe/unvalidated paths.
- The gateway path works on a machine where Python BLE control already works.
- The direct Web Bluetooth path works on a supported Chromium browser.
