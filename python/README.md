# DJI RS3 Python Control Library

This directory contains the Python control code for the DJI RS3 BLE protocol.
It is currently a repo-local library, not an installed Python package.

Run commands from this directory:

```bash
cd ./dji_rs3_control/python
```

The normal control CLI is:

```bash
python3 -m rs3.cli.ctl ...
```

The protocol/debug CLI is:

```bash
python3 -m rs3.cli.probe ...
```

## Requirements

The library uses `bleak` for Bluetooth LE:

```bash
python3 -m pip install bleak
```

Linux BLE access may require suitable Bluetooth permissions. The code uses the
RS3 BLE service characteristics discovered during protocol work:

- notifications: `0000fff4-0000-1000-8000-00805f9b34fb`
- writes: `0000fff5-0000-1000-8000-00805f9b34fb`

The default device identifier is currently:

```text
48:1C:B9:DC:8B:99
```

Override it with `--address` when needed.

## Normal CLI

Use `rs3.cli.ctl` for normal control operations. It speaks in semantic gimbal
terms: `tilt`, `roll`, and `pan`.

Show help:

```bash
python3 -m rs3.cli.ctl --help
```

Print live telemetry:

```bash
python3 -m rs3.cli.ctl telemetry
python3 -m rs3.cli.ctl telemetry --seconds 10
```

Recenter the gimbal:

```bash
python3 -m rs3.cli.ctl recenter
```

Put the gimbal to sleep or wake it:

```bash
python3 -m rs3.cli.ctl sleep
python3 -m rs3.cli.ctl wake
```

Send joystick-style velocity control:

```bash
python3 -m rs3.cli.ctl move --pan -80 --seconds 1.0
python3 -m rs3.cli.ctl move --tilt 60 --seconds 1.0
python3 -m rs3.cli.ctl move --roll -40 --seconds 1.0
```

`move` is a velocity-style command. It does not mean "move to this angle".
It means "hold a virtual joystick away from center for this long".

The axis values, such as `--pan -80`, are joystick deflection units:

- `0` means neutral, no commanded motion on that axis
- larger absolute values command faster motion
- the sign chooses direction
- values are not degrees, and are not degrees per second

`--seconds` controls how long the non-neutral command is held. For example,
`--seconds 1.0` sends movement frames for about one second, then sends neutral
frames to stop.

`--rate` controls how often movement frames are sent while the command is held.
The default is `5 Hz`, which matches the observed app behavior. Treat `--rate`
as protocol cadence rather than speed control; use larger or smaller axis
values to change speed.

Move to an absolute pose using the native track command:

```bash
python3 -m rs3.cli.ctl goto --tilt 10 --pan -30
python3 -m rs3.cli.ctl goto --tilt 0 --roll 0 --pan 0
```

Angles for `goto` are degrees. The current implementation uses the discovered
`0x04/0x62` track/waypoint command internally.

Run a multi-waypoint track:

```bash
python3 -m rs3.cli.ctl track \
  --waypoint 0,0 \
  --waypoint 10,-30 \
  --waypoint -5,45
```

Waypoint syntax is:

```text
TILT,PAN
TILT,ROLL,PAN
```

All waypoint values are degrees.

## Probe CLI

Use `rs3.cli.probe` when investigating protocol behavior. It exposes lower-level
axis controls, raw pose-unit track payloads, optional app-init replay, polling,
frame dumps, and telemetry logging.

Show help:

```bash
python3 -m rs3.cli.probe --help
```

Send a raw pan/yaw joystick command:

```bash
python3 -m rs3.cli.probe axis2 --delta 80 --duration 1.0 --telemetry
```

Try the opposite direction:

```bash
python3 -m rs3.cli.probe axis2 --delta -80 --duration 1.0 --telemetry
```

For probe joystick commands, `--delta` is the raw joystick offset from the
neutral value of `1024`.

For raw axes:

```text
axis0 value = 1024 - delta
axis1 value = 1024 - delta
axis2 value = 1024 - delta
```

So:

```bash
python3 -m rs3.cli.probe axis2 --delta 80
```

sends `axis2 = 944`, while:

```bash
python3 -m rs3.cli.probe axis2 --delta -80
```

sends `axis2 = 1104`.

For named directions, `--delta` is applied according to the direction name:

```text
left  -> axis2 below 1024
right -> axis2 above 1024
up    -> axis0 above 1024
down  -> axis0 below 1024
```

`--duration` is the probe equivalent of `--seconds` in the normal CLI. It is how
long the movement or command wait period lasts, in seconds. For joystick
commands, the script sends non-neutral frames for `--duration`, then sends
neutral frames to stop. For `recenter` and `track`, the command is sent once and
the script remains connected for `--duration` so telemetry can be observed.

Raw axis mapping:

```text
axis0 = tilt / pitch
axis1 = roll
axis2 = pan / yaw
```

Named directions are also available:

```bash
python3 -m rs3.cli.probe left --delta 80 --duration 1.0
python3 -m rs3.cli.probe right --delta 80 --duration 1.0
python3 -m rs3.cli.probe up --delta 80 --duration 1.0
python3 -m rs3.cli.probe down --delta 80 --duration 1.0
```

Probe track waypoints use raw protocol pose units, unlike the normal CLI:

```bash
python3 -m rs3.cli.probe track --waypoint 100,-300 --duration 5 --telemetry
```

Raw probe waypoint syntax is:

```text
AXIS0,AXIS2
AXIS0,AXIS1,AXIS2
```

These values are converted internally to degrees by dividing by `10`, matching
the current tenths-of-a-degree interpretation.

Useful probe options:

```bash
python3 -m rs3.cli.probe axis2 --delta 80 --duration 1.0 --dump-frames
python3 -m rs3.cli.probe axis2 --delta 80 --duration 1.0 --log probe.log
python3 -m rs3.cli.probe axis2 --delta 80 --duration 1.0 --dry-run
```

Avoid `--poll`, `--app-init`, and `--keepalive-0410` unless you are explicitly
testing protocol setup behavior.

## Python Library

The public package is `rs3`.

```python
from rs3 import Pose, RS3Client, VelocityCommand, Waypoint
```

### Async API

Use `RS3Client` when integrating into an async application.

```python
import asyncio

from rs3 import Pose, RS3Client, VelocityCommand


async def main() -> None:
    client = RS3Client("48:1C:B9:DC:8B:99", log_callback=print)
    await client.connect()
    try:
        await client.move_velocity(VelocityCommand(pan=-80))
        await asyncio.sleep(1.0)
        await client.stop_motion()

        await client.go_to(Pose(tilt_deg=0.0, roll_deg=0.0, pan_deg=0.0))
    finally:
        await client.disconnect()


asyncio.run(main())
```

Important async methods:

- `connect()`
- `disconnect()`
- `move_velocity(VelocityCommand(...))`
- `stop_motion()`
- `recenter()`
- `sleep()`
- `wake()`
- `go_to(Pose(...), method="track")`
- `run_track([Waypoint(...), ...])`
- `stream_telemetry(seconds=None)`

The latest decoded telemetry is available as:

```python
client.telemetry
```

When `0x04/0x66` pose tags are present, `client.telemetry.pose` contains:

```python
Pose(tilt_deg=..., roll_deg=..., pan_deg=...)
```

### Sync API

`RS3` is a small synchronous convenience wrapper. Each operation opens and
closes its own BLE session.

```python
from rs3 import Pose, RS3, VelocityCommand


gimbal = RS3("48:1C:B9:DC:8B:99", log_callback=print)
gimbal.sleep()
gimbal.wake()
gimbal.move_velocity(VelocityCommand(pan=-80))
gimbal.go_to(Pose(tilt_deg=0.0, roll_deg=0.0, pan_deg=0.0))
```

For repeated or long-running control, prefer the async `RS3Client` API so one
connection can be kept open.

## Coordinate System

The public API uses:

```text
tilt = pitch axis
roll = roll axis
pan  = yaw axis
```

The underlying protocol axis mapping is:

```text
axis0 = tilt / pitch
axis1 = roll
axis2 = pan / yaw
```

Angles exposed by the public API are degrees. The protocol telemetry and
waypoint payloads appear to use signed tenths of a degree internally.

## Current Limitations

- `move_velocity()` currently accepts joystick deflection units, not calibrated
  degrees per second.
- `go_to()` currently supports only `method="track"`.
- BLE discovery is not implemented yet; pass the device address explicitly when
  the default address is not correct.
- The project is repo-local for now. Run from `python/` or set
  `PYTHONPATH=/path_to_project_dir/dji_rs3_control/python`.
