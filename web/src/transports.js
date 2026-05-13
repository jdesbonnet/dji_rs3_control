import { bytesToHex, hexToBytes, iterEmbeddedFrames } from "./protocol.js";

export const DEFAULT_NOTIFY_CHAR = "0000fff4-0000-1000-8000-00805f9b34fb";
export const DEFAULT_WRITE_CHAR = "0000fff5-0000-1000-8000-00805f9b34fb";
export const DEFAULT_SERVICE = "0000fff0-0000-1000-8000-00805f9b34fb";

class Emitter {
  constructor() {
    this.frameCallbacks = new Set();
    this.statusCallbacks = new Set();
  }

  onFrame(callback) {
    this.frameCallbacks.add(callback);
    return () => this.frameCallbacks.delete(callback);
  }

  onStatus(callback) {
    this.statusCallbacks.add(callback);
    return () => this.statusCallbacks.delete(callback);
  }

  emitFrame(frame) {
    for (const callback of this.frameCallbacks) {
      callback(frame);
    }
  }

  emitStatus(status) {
    for (const callback of this.statusCallbacks) {
      callback(status);
    }
  }
}

export class WebBluetoothTransport extends Emitter {
  constructor({ serviceUuid = DEFAULT_SERVICE } = {}) {
    super();
    this.kind = "web-bluetooth";
    this.serviceUuid = serviceUuid;
    this.device = null;
    this.server = null;
    this.notifyCharacteristic = null;
    this.writeCharacteristic = null;
    this.handleNotification = this.handleNotification.bind(this);
  }

  async connect() {
    if (!navigator.bluetooth) {
      throw new Error("Web Bluetooth is not available in this browser");
    }
    this.emitStatus({ state: "connecting" });
    this.device = await navigator.bluetooth.requestDevice({
      acceptAllDevices: true,
      optionalServices: [this.serviceUuid],
    });
    this.device.addEventListener("gattserverdisconnected", () => {
      this.emitStatus({ state: "disconnected" });
    });
    this.server = await this.device.gatt.connect();
    const service = await this.server.getPrimaryService(this.serviceUuid);
    this.notifyCharacteristic = await service.getCharacteristic(DEFAULT_NOTIFY_CHAR);
    this.writeCharacteristic = await service.getCharacteristic(DEFAULT_WRITE_CHAR);
    this.notifyCharacteristic.addEventListener("characteristicvaluechanged", this.handleNotification);
    await this.notifyCharacteristic.startNotifications();
    this.emitStatus({ state: "connected", detail: this.device.name || this.device.id });
  }

  async disconnect() {
    try {
      if (this.notifyCharacteristic) {
        this.notifyCharacteristic.removeEventListener("characteristicvaluechanged", this.handleNotification);
        await this.notifyCharacteristic.stopNotifications();
      }
    } finally {
      if (this.device?.gatt?.connected) {
        this.device.gatt.disconnect();
      }
      this.emitStatus({ state: "disconnected" });
    }
  }

  async writeFrame(frame) {
    if (!this.writeCharacteristic) {
      throw new Error("Web Bluetooth transport is not connected");
    }
    if (this.writeCharacteristic.writeValueWithoutResponse) {
      await this.writeCharacteristic.writeValueWithoutResponse(frame);
    } else {
      await this.writeCharacteristic.writeValue(frame);
    }
  }

  handleNotification(event) {
    const view = event.target.value;
    const data = new Uint8Array(view.buffer.slice(view.byteOffset, view.byteOffset + view.byteLength));
    for (const frame of iterEmbeddedFrames(data)) {
      this.emitFrame(frame);
    }
  }
}

export class WebSocketGatewayTransport extends Emitter {
  constructor({ url }) {
    super();
    this.kind = "websocket-gateway";
    this.url = url;
    this.socket = null;
  }

  async connect({ address } = {}) {
    this.emitStatus({ state: "connecting" });
    await new Promise((resolve, reject) => {
      const socket = new WebSocket(this.url);
      this.socket = socket;
      socket.addEventListener("open", () => {
        this.emitStatus({ state: "connecting", detail: this.url });
        if (address) {
          socket.send(JSON.stringify({ type: "connect", address }));
        }
        resolve();
      });
      socket.addEventListener("error", () => {
        const error = new Error(`WebSocket connection failed: ${this.url}`);
        this.emitStatus({ state: "error", message: error.message });
        reject(error);
      });
      socket.addEventListener("close", () => {
        this.emitStatus({ state: "disconnected" });
      });
      socket.addEventListener("message", (event) => this.handleMessage(event));
    });
  }

  async disconnect() {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: "disconnect" }));
      this.socket.close();
    }
    this.emitStatus({ state: "disconnected" });
  }

  async writeFrame(frame) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error("WebSocket gateway is not connected");
    }
    this.socket.send(JSON.stringify({ type: "frame", hex: bytesToHex(frame) }));
  }

  handleMessage(event) {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      this.emitStatus({ state: "error", message: "Gateway sent invalid JSON" });
      return;
    }
    if (message.type === "frame") {
      try {
        for (const frame of iterEmbeddedFrames(hexToBytes(message.hex || ""))) {
          this.emitFrame(frame);
        }
      } catch (error) {
        this.emitStatus({ state: "error", message: error.message });
      }
      return;
    }
    if (message.type === "status") {
      this.emitStatus({ state: message.state, detail: message.detail });
      return;
    }
    if (message.type === "error") {
      this.emitStatus({ state: "error", message: message.message || "Gateway error" });
    }
  }
}
