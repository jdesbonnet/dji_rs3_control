# DJI RS 3 BLE Control Protocol

Author: Joe Desbonnet (with aid of gpt-5.4 and gpt-5.5 models)

Last edit:   2026-04-26

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

Additional subsystem endpoint IDs include:

```text
0x0b
0x26
0x27
0x32
0x44
0xbf
```

The exact subsystem assignment for these additional endpoint IDs is `[SPECULATIVE]`.

### 4.2 Command Type

Common command type values:

```text
0x40   request / command
0x80   response / acknowledgement
0x00   stream or poll-style command
```

The bit-level meaning of `cmd_type` is `[SPECULATIVE]`.

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
0       2     u16le  axis0
2       2     u16le  axis1
4       2     u16le  axis2
6       2     u16le  flags
8       1     u8     mode
```

The neutral axis value is `1024` (`0x0400`). Values below neutral move one direction; values above neutral move the opposite direction.

Neutral payload:

```text
000400040004000002
```

Decoded:

```text
axis0 = 1024
axis1 = 1024
axis2 = 1024
flags = 0
mode  = 2
```

### 5.3 Axis Mapping

The joystick axes are:

```text
axis0   tilt / pitch
axis1   roll
axis2   pan / yaw
```

Direction mapping:

```text
axis0 > 1024   tilt up
axis0 < 1024   tilt down
axis1 > 1024   roll positive direction
axis1 < 1024   roll negative direction
axis2 > 1024   pan right
axis2 < 1024   pan left
```

The physical meaning of positive and negative roll direction depends on the gimbal orientation and mounted camera frame of reference.

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

### 6.1 Recenter Command

The recenter command moves the gimbal pose back to zero degrees on all three axes:

```text
sender     0x02
receiver   0x04
cmd_type   0x40
cmd_set    0x04
cmd_id     0x4c
payload    fe01
```

### 6.2 Sleep/Wake Command

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

### 6.3 Gimbal Control Keepalive `[SPECULATIVE]`

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

### 6.4 Status Poll Command `[SPECULATIVE]`

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

### 6.5 Panorama Program Command `[SPECULATIVE]`

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

### 6.5 Panorama Progress Frame `[SPECULATIVE]`

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

### 6.6 Track Waypoint Program Command `[SPECULATIVE]`

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

### 6.7 Track Status Frame `[SPECULATIVE]`

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

## 9. Command Summary

```text
cmd_set  cmd_id  sender  receiver  description
0x04     0x01    0x02    0x04      joystick control
0x04     0x0f    0x02    0x04      sleep/wake control
0x04     0x27    0x04    0x02      sleep status notification
0x04     0x4c    0x02    0x04      recenter to zero pose
0x04     0x62    0x02    0x04      [SPECULATIVE] track waypoint program
0x04     0x63    0x02    0x04      [SPECULATIVE] panorama program start
0x04     0x64    0x04    0x02      [SPECULATIVE] panorama progress notification
0x04     0x6b    0x04    0x02      [SPECULATIVE] track status notification
0x04     0x10    0x02    0x04      [SPECULATIVE] control keepalive / authority
0x04     0x12    0x02    0xe5      [SPECULATIVE] status poll / telemetry configuration
0x0d     0x02    0xe5    0x02      status telemetry
0x04     0x66    0xe5    0x02      status telemetry
```

## 10. Open Items

The following protocol details remain `[SPECULATIVE]`:

- whether `0x04/0x10` is required before joystick control is accepted
- the exact meaning of the `0x04/0x10` response payload
- the exact meaning and units of telemetry fields in `0x0d/0x02`
- the exact field layout of telemetry frame `0x04/0x66`
- the full meaning of `cmd_type`
- the roles of secondary endpoint IDs

## 11. References

- [DJI Wi-Fi Protocol Reverse Engineering, Master Thesis Thomas Christof, 2021](https://www.digidow.eu/publications/2021-christof-masterthesis/Christof_2021_MasterThesis_DJIProtocolReverseEngineering.pdf)
