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

The published DJI RS SDK source uses `cmd_type = 0x03` (request, reply-with-data)
for `get_current_position`, distinct from the `cmd_type = 0x40` (ACK after
execute) default used elsewhere in this library. The earlier tests above used the
default `cmd_type = 0x40`, so the SDK-style cmd_type was retested explicitly:

- `cmd_type=0x03 cmd_set=0x0e cmd_id=0x02 payload=01`
- `cmd_type=0x03 cmd_set=0x0e cmd_id=0x02 payload=02`
- `cmd_type=0x03 cmd_set=0x0e cmd_id=0x02 payload=00`
- `cmd_type=0x03 cmd_set=0x04 cmd_id=0x02 payload=01`
- `cmd_type=0x06 cmd_set=0x0e cmd_id=0x02 payload=01`
- `cmd_type=0x03 cmd_set=0x0e cmd_id=0x02 payload=01` after `--app-init`

None elicited a reply with `set=0e id=02` or `set=04 id=02` (response-direction
bit set). Only the same background frame families seen passively continued to
arrive. The SDK's direct `get_current_position` path therefore appears to be
absent on the RS3 BLE transport regardless of cmd_type, payload variant, or
activation state.

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
- The SDK `get_current_position` form (`cmd_type=0x03 cmd_set=0x0e cmd_id=0x02`)
  is silently dropped on BLE, including under `--app-init` and across `payload`
  variants `00`/`01`/`02`.
- The only confirmed BLE pose source remains `0x04/0x66`, at approximately
  1 Hz.

## cmd_set=0x04 Brute Scan (cmd_type=0x03)

A scan of `cmd_set=0x04` ids `0x00..0xFF` was attempted with `cmd_type=0x03`
and empty payload, skipping the known motion ids `0x01, 0x07, 0x0C, 0x0F,
0x10, 0x14, 0x4C, 0x62`. See `experiments/scan_cmd_set.py`.

**Caution.** Despite using the "query" cmd_type `0x03`, the scan triggered a
calibration routine on the RS3, which then failed. `cmd_type=0x03` is not a
reliable safety shield on this firmware: some ids in `cmd_set=0x04` act on the
gimbal regardless of cmd_type.

The trigger was isolated by sending each suspect id alone with a long wait
window (`experiments/find_calibration_trigger.py`). Confirmed:

- **`cmd_type=0x03 cmd_set=0x04 cmd_id=0x08 payload=empty`** triggers a
  calibration routine on the RS3.
- The first `04/30 payload=NN01` progress frame appears about **5.3 seconds**
  after the request is sent, well past the original 100 ms scan window - which
  is why the original scan misattributed the trigger to an id sent much later.
- Subsequent isolated runs of `0x08` (single command, no follow-up traffic)
  completed successfully. The earlier failure occurred during the original
  brute scan, where the script kept sending unrelated commands at 100 ms
  cadence throughout the calibration routine. The current working hypothesis
  is that the failure was caused by concurrent BLE traffic during the routine,
  not by physical orientation. Recovery from a failed run still requires a
  power-cycle.

`0x08` is now in the default skip list for both `scan_cmd_set.py` and
`find_calibration_trigger.py`.

The scan did surface two new findings worth preserving:

- `req cmd_set=0x04 cmd_id=0x0b` produces a direct reply: `sender=0x04
  type=0x80 set=0x04 id=0x0b payload=000000000000` (six zero bytes when idle).
  This is the first BLE `cmd_set=0x04` id confirmed to return a structured
  reply to a `cmd_type=0x03` request.
- `req cmd_set=0x04 cmd_id=0x1f` produces a direct reply: `sender=0x04
  type=0x80 set=0x04 id=0x1f payload=e100000000000000000000000000000000`
  (17 bytes, leading byte `0xE1`).

During calibration, the gimbal emitted a stream of `04/30 payload=NN01` frames
where the first byte counted `0x00..0x06` in roughly `~500ms` steps - a ~5 Hz
progress stream. This is the rate range we are hunting for, but it appears to
be calibration-progress data, not pose data.

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
