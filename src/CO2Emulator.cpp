#include "CO2Emulator.h"

CO2Emulator::CO2Emulator()
  : protocol(device, waveform, alarms, HOST_SERIAL),
    receiver(protocol, HOST_SERIAL),
    cli(waveform, alarms, device, storage, CMD_SERIAL),
    web(waveform, alarms, device, storage),
    tftDisplay(waveform, alarms, device),
    lastWaveformUpdate(0), lastParamUpdate(0), dpiCounter(0) {}

void CO2Emulator::begin() {
  CMD_SERIAL.begin(BAUD_RATE_CMD);
  HOST_SERIAL.begin(BAUD_RATE_HOST, SERIAL_8N1, 44, 43);  // RX=44, TX=43 for T-Display S3
  
  delay(1000);
  
  // Initialize TFT first
  #if TFT_ENABLED
  tftDisplay.begin();
  tftDisplay.showMessage("Starting...");
  #endif
  
  storage.begin();
  waveform.setI2CSensor(&i2cSensor);
  i2cSensor.begin();
  
  ConfigStorage::Config cfg = storage.loadConfig();
  waveform.loadFromConfig(cfg);
  alarms.loadFromConfig(cfg);
  
  #if TFT_ENABLED
  tftDisplay.showMessage("WiFi...");
  #endif
  
  web.begin();
  
  #if TFT_ENABLED
  tftDisplay.showMessage("Ready!");
  delay(1000);
  tftDisplay.clear();
  #endif
  
  cli.printWelcome();
}

void CO2Emulator::update() {
  uint32_t now = millis();
  
  cli.update();
  receiver.update();
  device.updateZero();
  web.update();
  
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
