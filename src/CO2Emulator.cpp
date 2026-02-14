#include "CO2Emulator.h"

CO2Emulator::CO2Emulator()
  : cocoSensor(COCO_SERIAL),
    protocol(device, waveform, HOST_SERIAL),
    receiver(protocol, HOST_SERIAL),
    usbReceiver(nullptr),
    cline(waveform, device, storage, CMD_SERIAL),
    web(waveform, device, storage, cocoSensor),
    tftDisplay(waveform, device),
    lastWaveformUpdate(0), lastParamUpdate(0), dpiCounter(0) {}

void CO2Emulator::begin() {
  CMD_SERIAL.begin(BAUD_RATE_CMD);
  HOST_SERIAL.begin(BAUD_RATE_HOST, SERIAL_8N1, 44, 43);  // RX=44, TX=43 for T-Display S3
  COCO_SERIAL.begin(COCO_BAUD_RATE, SERIAL_8N1, COCO_RX_PIN, COCO_TX_PIN);

  delay(1000);

  // Initialize TFT first
  #if TFT_ENABLED
  tftDisplay.begin();
  tftDisplay.showMessage("Starting...");
  #endif

  storage.begin();
  waveform.setCocoSensor(&cocoSensor);
  cocoSensor.begin();

  ConfigStorage::Config cfg = storage.loadConfig();
  waveform.loadFromConfig(cfg);

  #if TFT_ENABLED
  tftDisplay.showMessage("WiFi...");
  #endif

  // Wire callbacks before starting web
  web.setUsbModeCallback([this](bool enabled) { setUsbProtocolMode(enabled); });
  cline.setUsbModeCallback([this](bool enabled) { setUsbProtocolMode(enabled); });
  web.begin();

  #if TFT_ENABLED
  tftDisplay.showMessage("Ready!");
  delay(1000);
  tftDisplay.clear();
  #endif

  cline.printWelcome();
}

void CO2Emulator::setUsbProtocolMode(bool enabled) {
  if (enabled && !device.isUsbProtocolMode()) {
    CMD_SERIAL.println("USB -> PROTOCOL mode");
    device.setUsbMode(DeviceState::UsbMode::PROTOCOL);
    protocol.addOutput(CMD_SERIAL);
    usbReceiver = new ProtocolReceiver(protocol, CMD_SERIAL);
    // Auto-start continuous mode so protocol data flows immediately
    if (!device.isContinuousMode()) {
      device.startContinuousMode();
    }
  } else if (!enabled && device.isUsbProtocolMode()) {
    device.setUsbMode(DeviceState::UsbMode::DEBUG);
    protocol.removeOutput(CMD_SERIAL);
    delete usbReceiver;
    usbReceiver = nullptr;
    CMD_SERIAL.println("USB -> DEBUG mode");
  }
}

bool CO2Emulator::isUsbProtocolMode() const {
  return device.isUsbProtocolMode();
}

void CO2Emulator::update() {
  uint32_t now = millis();

  // CLI only processes in debug mode
  if (!device.isUsbProtocolMode()) {
    cline.update();
  }

  receiver.update();  // Serial1 receiver always active

  // USB receiver only when in protocol mode
  if (usbReceiver) {
    usbReceiver->update();
  }

  device.updateZero();
  web.update();
  cocoSensor.update();

  #if TFT_ENABLED
  tftDisplay.update();
  #endif

  if (device.isContinuousMode() && (now - lastWaveformUpdate >= WAVEFORM_INTERVAL)) {
    lastWaveformUpdate = now;

    bool includeDPI = false;
    uint8_t dpiType = 0;

    if (now - lastParamUpdate >= PARAM_INTERVAL) {
      lastParamUpdate = now;
      includeDPI = true;

      switch (dpiCounter % 4) {
        case 0: dpiType = Protocol::DPI_CO2_STATUS; break;
        case 1: dpiType = Protocol::DPI_ETCO2; break;
        case 2: dpiType = Protocol::DPI_RESP_RATE; break;
        case 3: dpiType = Protocol::DPI_INSP_CO2; break;
      }
      dpiCounter++;

      device.updateParameters(waveform.getETCO2(), waveform.getRespiratoryRate());
    }

    protocol.sendWaveformPacket(includeDPI, dpiType);
  }
}
