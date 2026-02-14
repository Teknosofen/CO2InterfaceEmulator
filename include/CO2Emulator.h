#ifndef CO2_EMULATOR_H
#define CO2_EMULATOR_H

#include <Arduino.h>
#include "ShdlcSensorInterface.h"
#include "ConfigStorage.h"
#include "WaveformGenerator.h"
#include "DeviceState.h"
#include "ProtocolHandler.h"
#include "ProtocolReceiver.h"
#include "CommandLineInterface.h"
#include "WebInterface.h"
#include "TFTDisplay.h"
#include "Config.h"

class CO2Emulator {
private:
  ShdlcSensorInterface cocoSensor;
  ConfigStorage storage;
  WaveformGenerator waveform;
  DeviceState device;
  ProtocolHandler protocol;
  ProtocolReceiver receiver;
  ProtocolReceiver* usbReceiver;
  CommandLineInterface cline;
  WebInterface web;
  TFTDisplay tftDisplay;

  uint32_t lastWaveformUpdate;
  uint32_t lastParamUpdate;
  uint8_t dpiCounter;

  static const uint32_t WAVEFORM_INTERVAL = 10;
  static const uint32_t PARAM_INTERVAL = 1000;

public:
  CO2Emulator();
  void begin();
  void update();
  void setUsbProtocolMode(bool enabled);
  bool isUsbProtocolMode() const;
};

#endif // CO2_EMULATOR_H
