# Pose Stream Experiments

This note records experiments looking for a higher-rate gimbal angle stream over
the DJI RS3 BLE transport. It is intentionally separate from the main protocol
specification because the results are mostly negative or provisional.

## Motivation

The main BLE telemetry frame currently used by the library is `0x04/0x66`.
It carries pose-like fields that match observed pan/tilt/roll behavior, but it
arrives at roughly 1 Hz. That is usable for status display, but too slow for
tight feedback loops or smooth live angle monitoring.

The official DJI RS SDK protocol document describes CAN/UART commands for
gimbal angle retrieval and parameter push:

- `CmdSet=0x0e CmdID=0x02`: obtain attitude angle or joint angle.
- `CmdSet=0x0e CmdID=0x07`: enable or disable gimbal parameter push.
- `CmdSet=0x0e CmdID=0x08`: pushed gimbal parameters, including attitude and
  joint yaw/roll/pitch fields.

The experiments below tested whether these commands have a direct or simple BLE
equivalent on the RS3.

## Commands Tested

### Direct Angle Requests

The SDK angle request command was tested in both a BLE-style mapping and the
literal SDK command set:

- `0x04/0x02 payload=01`
- `0x04/0x02 payload=02`
- `0x0e/0x02 payload=01`
- `0x0e/0x02 payload=02`

No command-specific response was observed. The gimbal continued sending normal
background telemetry, especially `0x04/0x66`.

### Parameter Push Enable/Disable

The SDK parameter push setting was tested as a likely BLE-style mapping:

- `0x04/0x07 payload=00`
- `0x04/0x07 payload=01`
- `0x04/0x07 payload=02`

All variants received an ACK-like response:

```text
sender=04 receiver=02 type=80 set=04 id=07 payload=00
```

This confirms that `0x04/0x07` is a valid BLE command family, but `payload=01`
did not enable a new stream, did not produce `0x04/0x08`, and did not increase
the `0x04/0x66` pose cadence.

The literal SDK push setting was also tested:

- `0x0e/0x07 payload=01`
- `0x0e/0x07 payload=02`

No `0x0e/0x07` ACK and no `0x0e/0x08` stream were observed.

## Passive Baseline

An unfiltered passive monitor after disabling `0x04/0x07` showed the same frame
families seen after attempting to enable push:

| Frame | Observation |
| --- | --- |
| `0x04/0x66` | Pose/status telemetry, about 1 Hz. |
| `0x1c/0x01` | Higher-rate, fixed payload during tests. |
| `0x02/0x80` | Higher-rate, all-zero payload during tests. |
| `0x04/0x10` | Repeating background/config telemetry. |
| `0x0d/0x02` | Repeating telemetry-like frame, about 1 Hz. |
| `0x00/0x42` | Repeating background frame. |
| `0x00/0xf1` | Repeating background frame. |
| `0x04/0x1c` | Repeating background frame. |
| `0x04/0x27` | Repeating background/status frame. |

Because the same families appear passively, they should not be treated as new
streams caused by `0x04/0x07`.

## Motion Capture Findings

During a commanded right pan, `0x04/0x66` changed in a way that is consistent
with the known pose interpretation. In particular, tag `0x24` moved from near
zero to about `0x06e5`, which is `176.5 degrees` if interpreted as signed
little-endian `int16` in 0.1 degree units. A later left pan brought the value
back near `0xffc4`, about `-6.0 degrees`.

This reinforces the current interpretation that `0x04/0x66` carries the usable
BLE pose fields, with angles in 0.1 degree units.

`0x0d/0x02` also changed during motion, but it arrived at roughly the same low
rate and did not line up cleanly with pan angle in the tested captures. It may
represent internal state, sensor data, or control-loop values, but it is not yet
identified as a usable angle source.

## Current Conclusion

The official DJI RS SDK strongly suggests that a high-rate or push-style angle
mechanism exists in the wired SDK protocol. The tested BLE mappings did not
expose it:

- No BLE `0x04/0x08` stream was observed.
- No literal SDK `0x0e/0x08` stream was observed.
- `0x04/0x07` is real and ACKed, but it did not change observable telemetry
  behavior in these tests.
- The only confirmed BLE pose source remains `0x04/0x66`, at approximately
  1 Hz.

## Follow-up Ideas

- Capture the official Ronin app while it displays live angle data, if such a
  view exists, and compare whether it sends any preamble before receiving
  faster angle updates.
- Explore whether `0x04/0x07` has a longer structured payload rather than a
  single control byte.
- Investigate `0x04/0x10` and `0x0d/0x02` with synchronized physical motion,
  but treat them as background telemetry until their fields correlate cleanly
  with gimbal state.
- Search for SDK or firmware references to the BLE-specific command set around
  `0x04/0x07`.
