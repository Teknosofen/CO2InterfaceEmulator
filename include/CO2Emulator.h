#ifndef CO2_EMULATOR_H
#define CO2_EMULATOR_H

#include <Arduino.h>
#include "I2CSensorInterface.h"
#include "ConfigStorage.h"
#include "WaveformGenerator.h"
#include "AlarmManager.h"
#include "DeviceState.h"
#include "ProtocolHandler.h"
#include "ProtocolReceiver.h"
#include "CommandLineInterface.h"
#include "WebInterface.h"
#include "TFTDisplay.h"
#include "Config.h"

class CO2Emulator {
private:
  I2CSensorInterface i2cSensor;
  ConfigStorage storage;
  WaveformGenerator waveform;
  AlarmManager alarms;
  DeviceState device;
  ProtocolHandler protocol;
  ProtocolReceiver receiver;
  CommandLineInterface cli;
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
};

#endif // CO2_EMULATOR_H
