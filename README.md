# DJI RS3 gimbal protocol documentation and control software

This project documents the [DJI RS3](https://store.dji.com/ie/product/dji-rs-3) bluetooth low energy (BLE) radio protocol and provides a library and some sample code to control the gimbal from computer programmes.

This documentation has been achieved by reverse-engineering the protocol from 
Android bluetooth packet logs while operating the DJI Ronin app with the aid of OpenAI gpt-5.5. 
It is a work in progress with some limitations (eg currently fastest known gimbal angle update rate
is 1Hz).

When reverse engineering the protocol the device firmware is version ? and the DJI Ronin app version v2.1.2(6936).

This protocol may apply to other bluetooth enabled DJI gimbals but since I only have a RS3 I cannot verify. 

 * [DJI RS3 BLE protocol documentation](./rs3_ble_protocol_spec.md)
 * [DJI RS3 python control library](./python/README.md)
 * [DJI RS3 web control app](https://jdesbonnet.github.io/dji_rs3_control/web/)
 * [Pose stream reverse-engineering experiments](./experiments/pose_stream_experiments.md)

## Web App Screenshot

![RS3 web control app screenshot](./docs/images/rs3-webapp-screenshot.png)
