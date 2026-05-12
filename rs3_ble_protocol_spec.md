# DJI RS 3 BLE Control Protocol

Author: Joe Desbonnet (with aid of gpt-5.4 and gpt-5.5 models)

Last edit:   2026-05-12

## 1. Overview

The DJI RS 3 BLE control protocol transports [DUML (DJI Universal Markup Lanaguage)](https://www.darknavy.org/blog/fatal_vulnerabilities_compromising_dji_control_devices/#duml-protocol) 
frames over a Bluetooth Low Energy GATT service. Clients write command frames to the control characteristic and receive responses or telemetry from the notification characteristic.

Fields, commands, or semantics marked `[SPECULATIVE]` are not fully characterized and should be treated as unstable until validated against the target firmware.

> [!CAUTION]
> The protocol has been reverse engineered with the aid of bluetooth HCI logs from an Android phone and OpenAI gpt-5.5 model. 
> It is presented without any warranty whatsoever. 
> While damage to a gimbal is unlikely from use of unoffical software this cannot be absolutely gauranteed. 
> Use with caution.

## 2. BLE Transport

### 2.1 Characteristics

The protocol uses one write characteristic and one notification characteristic:

```text
notify characteristic  0000fff4-0000-1000-8000-00805f9b34fb
write characteristic   0000fff5-0000-1000-8000-00805f9b34fb
```

The client enables notifications on the notify characteristic before sending control commands.

Typical ATT handles:

```text
notify value handle    0x0012
notify CCCD handle     0x0013
write value handle     0x0015
```

Implementations should prefer characteristic UUID discovery over hard-coded handles.

### 2.2 Data Flow

The normal data flow is:

```text
client -> gimbal   ATT Write Command to fff5
gimbal -> client   ATT Handle Value Notification from fff4
```

Application payloads are DUML frames. A single BLE notification may contain one DUML frame or multiple concatenated DUML frames.

## 3. DUML Frame Format

### 3.1 Packet Layout

Each DUML frame has the following structure:

```text
offset  size  field
0       1     start byte, always 0x55
1       1     total_length_lo
2       1     version_and_length_hi
3       1     header_crc8
4       1     sender
5       1     receiver
6       2     sequence, little-endian
8       1     cmd_type
9       1     cmd_set
10      1     cmd_id
11      var   payload
end-2   2     frame_crc16, little-endian
```

Horizontal byte map, where `N` is the total frame length:

<table>
  <thead>
    <tr>
      <th>Byte(s)</th>
      <th>0</th>
      <th>1</th>
      <th>2</th>
      <th>3</th>
      <th>4</th>
      <th>5</th>
      <th>6..7</th>
      <th>8</th>
      <th>9</th>
      <th>10</th>
      <th>11..N-3</th>
      <th>N-2..N-1</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>Field</th>
      <td>start</td>
      <td>len_lo</td>
      <td>ver_len_hi</td>
      <td>hdr_crc8</td>
      <td>snd</td>
      <td>rcv</td>
      <td>seq</td>
      <td>cmd_type</td>
      <td>cmd_set</td>
      <td>cmd_id</td>
      <td>payload</td>
      <td>frame_crc16</td>
    </tr>
    <tr>
      <th>Encoding</th>
      <td><code>0x55</code></td>
      <td><code>len[7:0]</code></td>
      <td><code>ver + len[9:8]</code></td>
      <td><code>u8</code></td>
      <td><code>u8</code></td>
      <td><code>u8</code></td>
      <td><code>u16le</code></td>
      <td><code>u8</code></td>
      <td><code>u8</code></td>
      <td><code>u8</code></td>
      <td>variable</td>
      <td><code>u16le</code></td>
    </tr>
  </tbody>
</table>

The total frame length includes the header, payload, and trailing CRC16.

### 3.2 Length and Version

The frame length is encoded across bytes `1` and `2`:

```text
length = byte1 | ((byte2 & 0x03) << 8)
```

For the frames described here, byte `2` is normally `0x04`, corresponding to DUML protocol version `1` with no high length bits set.

### 3.3 Header CRC8

The header CRC is calculated over bytes `0..2`:

```text
initial value          0x77
reflected polynomial   0x31
covered bytes          start, length low, version/length high
```

### 3.4 Frame CRC16

The frame CRC is calculated over the complete frame excluding the final two CRC bytes:

```text
initial value          0x3692
reflected polynomial   CCITT 0x1021
byte order             little-endian
```

## 4. Endpoints and Command Types

### 4.1 Endpoint IDs

The following endpoint IDs are used by the control protocol:

```text
0x02   client controller
0x04   gimbal motion controller
0xe5   telemetry/status endpoint
```

Additional subsystem endpoint IDs whos function is unknown include:

```text
0x0b
0x26
0x27
0x32
0x44
0xbf
```

### 4.2 Command Type

Common command type values:

```text
0x40   request / command
0x80   response / acknowledgement
0x00   stream or poll-style command
```

The bit-level meaning of `cmd_type` is `[SPECULATIVE]`.

### 4.3 Command Summary

Ordered by command code (`cmd_set` / `cmd_id`):

| Command code | Sender | Receiver | Description |
| --- | --- | --- | --- |
| `0x04/0x01` | `0x02` | `0x04` | joystick control |
| `0x04/0x0c` | `0x02` | `0x04` | native speed / rate control `[PARTIAL]` |
| `0x04/0x0f` | `0x02` | `0x04` | sleep/wake control |
| `0x04/0x10` | `0x02` | `0x04` | `[SPECULATIVE]` control keepalive / authority |
| `0x04/0x12` | `0x02` | `0xe5` | `[SPECULATIVE]` status poll / telemetry configuration |
| `0x04/0x14` | `0x02` | `0x04` | absolute angle control |
| `0x04/0x27` | `0x04` | `0x02` | sleep status notification |
| `0x04/0x4c` | `0x02` | `0x04` | recenter to zero pose |
| `0x04/0x62` | `0x02` | `0x04` | `[SPECULATIVE]` track waypoint program |
| `0x04/0x63` | `0x02` | `0x04` | `[SPECULATIVE]` panorama program start |
| `0x04/0x64` | `0x04` | `0x02` | `[SPECULATIVE]` panorama progress notification |
| `0x04/0x66` | `0xe5` | `0x02` | status telemetry |
| `0x04/0x6b` | `0x04` | `0x02` | `[SPECULATIVE]` track status notification |
| `0x0d/0x02` | `0xe5` | `0x02` | status telemetry |

## 5. Joystick Control Command

### 5.1 Command Identity

Joystick motion is controlled with command set `0x04`, command id `0x01`:

```text
sender     0x02
receiver   0x04
cmd_type   0x40
cmd_set    0x04
cmd_id     0x01
```

### 5.2 Payload Layout

The joystick payload is 9 bytes:

```text
offset  size  type   field
0       2     u16le  axis0 (tilt / pitch)
2       2     u16le  axis1 (roll)
4       2     u16le  axis2 (pan / yaw)
6       2     u16le  flags (set to 0, function unknown)
8       1     u8     mode  (set to 2 in snoop logs, function unknown)
```

The neutral axis value is `1024` (`0x0400`). Values below neutral move one direction; values above neutral move the opposite direction.

### 5.4 Command Cadence

Joystick commands are streamed while motion is requested. A controller should send:

1. several neutral frames before motion
2. repeated non-neutral frames while motion is held
3. several neutral frames on release

Recommended stream rate:

```text
5 Hz
```

Typical app-style deflection magnitudes:

```text
small test input     +/- 80 to +/- 120
normal input         +/- 350 to +/- 400
neutral              1024
```

### 5.5 Example Payloads

```text
neutral        000400040004000002
pan left       000400048302000002   axis2 = 643
pan right      000400048e05000002   axis2 = 1422
tilt up        820500040004000002   axis0 = 1410
tilt down      850200040004000002   axis0 = 645
roll negative  000483030004000002   axis1 = 899
roll positive  00047d040004000002   axis1 = 1149
```

The roll examples use `+/-125` from neutral. They are representative payloads, not calibrated maximums.

## 6. Control Session Commands

### 6.1 Native Speed / Rate Control Command `[PARTIAL]`

The native speed command appears to command calibrated gimbal angular rate,
unlike joystick command `0x04/0x01`, whose axis values are controller
deflection units. This command was identified from DJI R SDK prior art and
validated with a small positive pan/yaw movement on RS 3 BLE.

```text
sender     0x02
receiver   0x04
cmd_type   0x40
cmd_set    0x04
cmd_id     0x0c
payload    7 bytes
```

Payload layout, based on DJI R SDK prior art and one live positive pan/yaw
test:

```text
offset  size  type           field
0       2     s16le/u16le    axis2 / pan / yaw speed, likely 0.1 deg/s
2       2     s16le/u16le    axis1 / roll speed, likely 0.1 deg/s [SPECULATIVE]
4       2     s16le/u16le    axis0 / tilt / pitch speed, likely 0.1 deg/s [SPECULATIVE]
6       1     u8             control flags [SPECULATIVE]
```

Likely control flag bits from DJI R SDK prior art:

```text
bit 7  speed control takeover when set; release speed control when clear
bit 3  camera focal length compensation disable when set [SPECULATIVE]
bits 0..2,4..6 reserved
```

Validated examples:

```text
payload 00000000000000  -> response payload 00, no observed movement
payload 00000000000080  -> response payload 00, no observed movement
payload 14000000000080  -> response payload 00, pan moved about +1.0 deg
```

Live validation on 2026-05-12:

- baseline pose before testing: `tilt=0.0 roll=0.0 pan=89.9`
- zero/release payload `00000000000000` received response
  `0x04/0x0c payload=00`
- zero/takeover payload `00000000000080` received response
  `0x04/0x0c payload=00`
- positive pan-speed payload `14000000000080` received response
  `0x04/0x0c payload=00`
- telemetry during the positive pan-speed test moved from approximately
  `pan=90.2` to `pan=91.2`
- final normal state sample reported `tilt=0.0 roll=0.0 pan=91.2`

Further work is needed before exposing this as a high-level API: validate
negative/reverse direction semantics, roll and tilt axes, the exact signedness
of the speed fields, flag bit `0x04`, and the firmware's speed-command timeout.
Based on DJI R SDK behavior, controllers should send zero/release after a speed
test and should stream repeated speed commands for continuous rate control.

### 6.2 Absolute Angle Control Command

The absolute angle command moves selected axes to absolute pose targets without
using the track/waypoint preview command.

```text
sender     0x02
receiver   0x04
cmd_type   0x40
cmd_set    0x04
cmd_id     0x14
payload    8 bytes
```

Payload layout, based on live pan/yaw validation and DJI R SDK prior art:

```text
offset  size  type   field
0       2     s16le  axis2 / pan / yaw target, tenths of a degree
2       2     s16le  axis1 / roll target, tenths of a degree [SPECULATIVE]
4       2     s16le  axis0 / tilt / pitch target, tenths of a degree [SPECULATIVE]
6       1     u8     control flags [SPECULATIVE]
7       1     u8     duration or speed parameter, likely tenths of a second [SPECULATIVE]
```

The tested control byte was `0x0d`. Based on DJI R SDK prior art, the likely bit
layout is:

```text
bit 0  absolute control when set
bit 1  axis2 / pan / yaw invalid when set
bit 2  axis1 / roll invalid when set
bit 3  axis0 / tilt / pitch invalid when set
bits 4..7 reserved
```

This interpretation means `0x0d` requests absolute control with pan/yaw valid
and roll plus tilt ignored.

Validated examples:

```text
payload c201000000000d14  -> pan target 45.0 deg, roll/tilt ignored, parameter 0x14
payload 0000000000000d14  -> pan target 0.0 deg, roll/tilt ignored, parameter 0x14
```

Live validation on 2026-05-12:

- starting pose before the first test: `tilt=0.0 roll=0.0 pan=89.5`
- `0x04/0x14` payload `0000000000000d14` received response
  `0x04/0x14 payload=00` and moved pan to `0.0`
- `0x04/0x14` payload `c201000000000d14` moved pan to `45.0`
- final normal state sample reported `tilt=0.0 roll=0.0 pan=45.1`

This appears to be the generic no-preview absolute angle command. Further work
is needed to validate roll, tilt, the full control flag byte, and the exact
meaning of the final parameter byte.

### 6.3 Recenter Command

The recenter command moves the gimbal pose back to zero degrees on all three axes:

```text
sender     0x02
receiver   0x04
cmd_type   0x40
cmd_set    0x04
cmd_id     0x4c
payload    fe01
```

### 6.4 Sleep/Wake Command

Sleep/wake is controlled with command set `0x04`, command id `0x0f`:

```text
sender     0x02
receiver   0x04
cmd_type   0x40
cmd_set    0x04
cmd_id     0x0f
```

Payload:

```text
23 01 01    enter sleep
23 01 00    wake / leave sleep
```

The gimbal can report sleep state through status notification `0x04/0x27`:

```text
0000000001    asleep
0000000000    awake
```

### 6.5 Gimbal Control Keepalive `[SPECULATIVE]`

The following command may act as a control keepalive or control-authority request:

```text
sender     0x02
receiver   0x04
cmd_type   0x40
cmd_set    0x04
cmd_id     0x10
payload    12
```

The corresponding response format is:

```text
sender     0x04
receiver   0x02
cmd_type   0x80
cmd_set    0x04
cmd_id     0x10
payload    00120100
```

The required cadence and exact semantics of this command are `[SPECULATIVE]`.

### 6.6 Status Poll Command `[SPECULATIVE]`

The telemetry/status endpoint accepts command set `0x04`, command id `0x12`:

```text
sender     0x02
receiver   0xe5
cmd_type   0x00
cmd_set    0x04
cmd_id     0x12
```

Known payload forms include:

```text
660cc01d108401000e000c000050000000000000000010
660cc01d103e010000000c000050
6624c01d00001c1051010000000c00005000f103
```

This command appears to request or configure status reporting. It is not required for basic passive notification reception. Its side effects are `[SPECULATIVE]`.

### 6.7 Panorama Program Command `[SPECULATIVE]`

The panorama program command starts an autonomous multi-position panorama movement:

```text
sender     0x02
receiver   0x04
cmd_type   0x40
cmd_set    0x04
cmd_id     0x63
payload    10 bytes
```

Observed payload:

```text
a6ff5a0039f406040201
```

Interpreted as signed little-endian 16-bit values:

```text
-90, 90, -3015, 1030, 258
```

The first two fields are likely pan/yaw sweep bounds in whole degrees. In the same movement, telemetry tag `0x24` swept approximately from `-900` to `+900`, matching the existing `0.1 degrees` telemetry scale.

The remaining fields are `[SPECULATIVE]`. They may describe vertical sweep bounds, camera field of view, grid shape, shot spacing, row count, direction, or panorama mode.

### 6.8 Panorama Progress Frame `[SPECULATIVE]`

During panorama execution, the gimbal sends progress notifications:

```text
sender     0x04
receiver   0x02
cmd_type   0x00
cmd_set    0x04
cmd_id     0x64
payload    5 bytes
```

Observed payload shape:

```text
01 NN 00 18 00
```

`NN` increments as the panorama progresses. `0x0018` is likely the total shot count, `24` decimal.

The client acknowledges each progress frame with:

```text
sender     0x02
receiver   0x04
cmd_type   0x80
cmd_set    0x04
cmd_id     0x64
payload    empty
```

### 6.9 Track Waypoint Program Command `[SPECULATIVE]`

The track waypoint command starts or updates an autonomous movement through one or more pan/tilt waypoints:

```text
sender     0x02
receiver   0x04
cmd_type   0x40
cmd_set    0x04
cmd_id     0x62
payload    2 + N * 10 bytes
```

Payload header:

```text
offset  size  type  field
0       1     u8    mode, observed 0x0a
1       1     u8    waypoint count
```

Each waypoint record is 10 bytes:

```text
offset  size  type   field
0       2     s16le  parameter 0, observed 20
2       2     s16le  parameter 1, observed 20
4       2     s16le  axis1 / roll target, observed 0
6       2     s16le  axis0 / tilt target, likely tenths of a degree
8       2     s16le  axis2 / pan target, tenths of a degree
```

Observed 3-waypoint payload:

```text
0a031400140000001501cffd140014000000c1017bfb14001400000048ff8a04
```

Decoded:

```text
mode  = 0x0a
count = 3

record 0: parameter0=20 parameter1=20 axis1=0 axis0=277  axis2=-561
record 1: parameter0=20 parameter1=20 axis1=0 axis0=449  axis2=-1157
record 2: parameter0=20 parameter1=20 axis1=0 axis0=-184 axis2=1162
```

The app preview moved the gimbal through poses matching these `axis0` and `axis2` values in telemetry frame `0x04/0x66`.

The first two per-waypoint parameters are `[SPECULATIVE]`. They may represent speed, interpolation, dwell, easing, or track timing. The observed value was `20` for both fields.

### 6.10 Track Status Frame `[SPECULATIVE]`

Track execution status uses command id `0x6b`:

```text
sender     0x04
receiver   0x02
cmd_type   0x00
cmd_set    0x04
cmd_id     0x6b
```

The client periodically queries the track state with:

```text
sender     0x02
receiver   0x04
cmd_type   0x40
cmd_set    0x04
cmd_id     0x6b
payload    00000162
```

The status payload changes while the track preview is running. Field layout is `[SPECULATIVE]`.

## 7. Telemetry

### 7.1 Notification Transport

Telemetry is delivered as DUML frames through the `fff4` notification characteristic.

Receivers should scan each notification payload for one or more valid `0x55` DUML frames and verify CRCs before decoding.

### 7.2 Status Frame `0x0d / 0x02`

Telemetry frame:

```text
sender     0xe5
receiver   0x02
cmd_set    0x0d
cmd_id     0x02
```

The payload contains four little-endian signed 32-bit values followed by additional status bytes:

```text
field   type
f0      s32le
f1      s32le
f2      s32le
f3      s32le
tail    bytes
```

`f0..f2` is believed to be the balancing current being consumed by axis0..2 gimbals. A well balanced gimbal will minimize these values.  `f3` is battery state of charge with 100% charge as indicated by the device LCD display to be 2702.

### 7.3 Status Frame `0x04 / 0x66`

Telemetry frame:

```text
sender     0xe5
receiver   0x02
cmd_set    0x04
cmd_id     0x66
```

This frame carries structured state data from the telemetry/status endpoint. The payload uses a leading byte followed by tag-length-value records:

```text
offset  size  field
0       1     header or version byte
1       1     tag
2       1     value length
3       var   value, little-endian signed integer
...           repeated tag/length/value records
```

Known tags include:

```text
tag   size  meaning
0x06  1     [SPECULATIVE] axis0-related small state value
0x07  1     [SPECULATIVE] axis1-related small state value
0x08  1     [SPECULATIVE] axis2-related small state value
0x0a  1     unknown
0x0b  1     unknown
0x0c  1     unknown
0x22  2     axis0 tilt pose, signed tenths of a degree
0x23  2     axis1 roll pose, signed tenths of a degree
0x24  2     axis2  pan pose, signed tenths of a degree
```

The `0x22`, `0x23`, and `0x24` fields change coherently during one-axis joystick motion and are the best current candidates for gimbal pose feedback.

For pan/yaw, tag `0x24` ranges from `-1800` to `+1800` over a full rotation (TODO: one of those values can't be inclusive because -180 is the same angle as +180). This indicates a scale of `0.1 degrees` per unit, with wrap at `+/-180 degrees`.

The same `0.1 degrees` scale is believed to also apply to tag `0x22` and tag `0x23`. Unlike the pan gimbal, roll and tilt gimbals have a limited range of rotation.

## 8. Recommended Client Behavior

### 8.1 Passive Telemetry Client

A passive client should:

1. connect over BLE
2. subscribe to `fff4`
3. parse DUML frames from notifications
4. avoid sending status poll commands unless needed

### 8.2 Joystick Control Client

A joystick client should:

1. connect over BLE
2. subscribe to `fff4`
3. send several neutral `0x04/0x01` joystick frames
4. stream signed axis deflections at approximately `5 Hz`
5. send several neutral frames on release

For initial bring-up, use small deflections such as `+/-80` or `+/-120`.

### 8.3 Safety Behavior

A client should always send neutral joystick frames before disconnecting or after interrupted movement. A client should also clamp axis values to the valid unsigned 16-bit range.

Recommended neutral-stop sequence:

```text
send neutral joystick frame
wait 100-200 ms
send neutral joystick frame
wait 100-200 ms
send neutral joystick frame
```

For native speed command `0x04/0x0c`, a client should send a zero/release speed
payload after any test or interrupted movement:

```text
00000000000000
```

## 9. Related Reverse Engineering Work

Public work on other DJI gimbals and DJI internal protocols suggests that the
RS 3 BLE protocol is part of a broader DJI pattern rather than a one-off design.
The common theme is that DJI reuses similar gimbal data models across different
outer transports and frame formats.

### 9.1 DUML Across DJI Products

Community DUML dissectors and protocol writeups describe the same core packet
shape used here:

- `0x55` frame delimiter
- packed length/version field
- header CRC
- sender and receiver endpoint IDs
- sequence number
- command type
- command set and command id
- command-specific payload
- trailing CRC16

The `o-gs/dji-firmware-tools` DUML dissectors identify endpoint `0x04` as
`Gimbal` and command set `0x04` as `Gimbal`, matching the RS 3 BLE captures in
this document. Its gimbal command table also lists nearby commands that are
useful search targets for RS 3 work:

```text
0x04/0x01   Gimbal Control
0x04/0x0a   Gimbal Ext Ctrl Degree / Rotate / Angle Set
0x04/0x0c   Gimbal Ext Ctrl Accel / Speed Control
0x04/0x14   Gimbal Abs Angle Control
0x04/0x4c   Gimbal Reset And Set Mode
```

These names should not be assumed to map one-to-one to RS 3 firmware behavior,
but they support the interpretation that command set `0x04` is the right area
to search for generic gimbal angle and speed controls.

### 9.2 DUML Over CAN on Osmo / Zenmuse Gimbals

CBUnmanned's Osmo / Zenmuse X3 / X5 reverse-engineering notes report a CAN bus
between the Osmo handle and gimbal running at `1,000,000 bps`. The captured CAN
payload stream appears to contain normal `0x55` DUML frames split across
multiple 8-byte CAN frames.

This is directly relevant to the RS 3 BLE work because it suggests DUML is the
application protocol and BLE is only one transport. Other DJI products appear to
carry the same style of DUML packet over CAN, UART, USB/network, or Wi-Fi.

### 9.3 RS2 / Ronin SDK CAN Protocol

The public RS2 / Ronin CAN work is semantically close, but not byte-for-byte the
same as the RS 3 BLE DUML frames documented here. Projects such as
`ceinem/dji_rs2_ros_controller`, ArduPilot's `mount-djirs2-driver.lua`, and
`ConstantRobotics/DJIR_SDK` are based on DJI R SDK protocol behavior over CAN.

Notable differences:

- The RS2 / Ronin SDK frame described by ArduPilot starts with `0xaa`, not
  DUML's `0x55`.
- ArduPilot documents CAN frame id `0x223` for host-to-gimbal and `0x222` for
  gimbal-to-host.
- The command namespace in the ArduPilot driver uses command set `0x0e`, not
  RS 3 BLE's observed `0x04` gimbal command set.

Notable similarities:

- Position control uses yaw, roll, and pitch as signed `int16` values.
- Angle units are tenths of a degree.
- A control byte selects relative vs absolute control and marks individual axes
  invalid.
- A duration byte uses units of `0.1 s`.
- Position feedback also reports yaw, roll, and pitch as signed tenths of a
  degree.

The RS2 / Ronin SDK control shape is therefore a strong semantic clue. It
supports the hypothesis that RS 3 should have a no-LCD absolute angle command
whose payload contains three signed axis targets, validity/absolute bits, and
possibly a duration or speed field.

### 9.4 DJI Onboard SDK Gimbal Model

DJI's Onboard SDK documentation describes gimbal angle and speed control using
the same basic data model:

- angle control has yaw, roll, pitch, mode, and duration fields
- yaw, roll, and pitch are signed `int16` values in `0.1 degree` units
- duration is in `0.1 s`
- speed control uses yaw, roll, and pitch rates in `0.1 deg/s`

This is not proof that the RS 3 BLE firmware accepts the same packet format, but
it is independent confirmation that signed tenths-of-a-degree axis values are a
standard DJI gimbal representation.

### 9.5 Working Hypotheses From Prior Art

- The current `0x04/0x62` RS 3 command is best treated as a track/waypoint
  preview command, not as a generic goto command. This matches the gimbal LCD
  showing a preview-complete message after a one-waypoint `goto`.
- A cleaner no-LCD absolute move has been validated as `0x04/0x14`.
- Native speed/rate control has been partially validated as `0x04/0x0c`, but
  reverse direction, roll, tilt, and all flag semantics still need controlled
  testing before this should become a normal high-level API.
- Candidate `0x04/0x0a` may still represent related degree or rotate control
  based on older DUML dissector naming.
- A closed-loop goto can still be built using `0x04/0x01` joystick/velocity
  control plus `0x04/0x66` pose telemetry if lower-level continuous control is
  preferred.
- Cross-product command names are useful hints, but command IDs and payload
  layouts must be validated on RS 3 firmware before being documented as fact.

## 10. Open Items

The following protocol details remain `[SPECULATIVE]`:

- whether `0x04/0x10` is required before joystick control is accepted
- the exact meaning of the `0x04/0x10` response payload
- the exact meaning and units of telemetry fields in `0x0d/0x02`
- the exact field layout of telemetry frame `0x04/0x66`
- the full meaning of `cmd_type`
- the roles of secondary endpoint IDs
- validate roll and tilt behavior for `0x04/0x14`
- characterize the `0x04/0x14` control flag byte and final duration/speed byte
- validate negative/reverse direction, roll, and tilt behavior for `0x04/0x0c`
- characterize the `0x04/0x0c` control flag byte and speed-command timeout
- determine whether `0x04/0x0a` implements related degree or rotate control

## 11. References

- [DJI Wi-Fi Protocol Reverse Engineering, Master Thesis Thomas Christof, 2021](https://www.digidow.eu/publications/2021-christof-masterthesis/Christof_2021_MasterThesis_DJIProtocolReverseEngineering.pdf)
- [DJI Protocol packet-structure writeup](https://www.push-force.dev/article/73)
- [o-gs/dji-firmware-tools DUML dissectors](https://github.com/o-gs/dji-firmware-tools/tree/master/comm_dissector/wireshark)
- [CBUnmanned Osmo / Zenmuse X3 / X5 CAN reverse-engineering notes](https://www.cbunmanned.com/blog/dji-osmozenmuse-x3-amp-x5-aftermarket-uav-integration)
- [ceinem/dji_rs2_ros_controller](https://github.com/ceinem/dji_rs2_ros_controller)
- [ArduPilot DJI RS2 mount driver](https://github.com/ArduPilot/ardupilot/blob/master/libraries/AP_Scripting/drivers/mount-djirs2-driver.lua)
- [ConstantRobotics/DJIR_SDK](https://github.com/ConstantRobotics/DJIR_SDK)
- [DJI Onboard SDK Gimbal AngleData](https://developer.dji.com/onboard-api-reference/structDJI_1_1OSDK_1_1Gimbal_1_1AngleData.html)
- [DJI Onboard SDK Gimbal SpeedData](https://developer.dji.com/onboard-api-reference/structDJI_1_1OSDK_1_1Gimbal_1_1SpeedData.html)
