# RS3 Web Control

This directory contains a dependency-light single page web app for controlling
the RS3 gimbal.

## Run the App

```bash
cd web
python3 -m http.server 8000
```

Open:

```text
http://localhost:8000
```

`localhost` is a secure context for Web Bluetooth in Chromium-based browsers.

## Gateway Mode

Gateway mode is the most reliable path while developing because it reuses the
known working Python BLE stack.

In one terminal:

```bash
cd web
python3 gateway/rs3_gateway.py --address 48:1C:B9:DC:8B:99
```

In another terminal:

```bash
cd web
python3 -m http.server 8000
```

Then open `http://localhost:8000`, keep mode set to `Gateway`, and connect to
`ws://localhost:8765`.

## Browser BLE Mode

Browser BLE mode uses the Web Bluetooth API directly. It requires a compatible
Chromium-based browser and the RS3 BLE service to be accessible through:

```text
0000fff0-0000-1000-8000-00805f9b34fb
```

The app writes to `fff5` and subscribes to `fff4`.

## Validation

Protocol helpers can be checked without hardware:

```bash
npm test
```

Manual hardware checks:

- connect through gateway
- verify pose telemetry updates
- drag joystick slightly and release
- press `Stop`
- run `rate --pan` equivalent from the Rate panel
- send a small go-to pan angle
- recenter

## Safety

The app sends both native rate zero/release and neutral joystick frames on stop.
The joystick also sends neutral frames on pointer release. Native negative
tilt/roll rates remain blocked in the UI because only pan/yaw direction has
been validated in both directions.
