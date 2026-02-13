#ifndef WEB_INTERFACE_H
#define WEB_INTERFACE_H

#include <Arduino.h>
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <ArduinoJson.h>
#include <functional>
#include "WaveformGenerator.h"
#include "AlarmManager.h"
#include "DeviceState.h"
#include "ConfigStorage.h"
#include "ShdlcSensorInterface.h"
#include "Config.h"

class WebInterface {
private:
  AsyncWebServer server;
  AsyncEventSource events;
  WaveformGenerator& waveform;
  AlarmManager& alarms;
  DeviceState& device;
  ConfigStorage& storage;
  ShdlcSensorInterface& sensor;

  std::function<void(bool)> usbModeCallback;

  float currentCO2Value;
  uint32_t lastDataUpdate;

  void setupRoutes();
  String getIndexHTML();

public:
  WebInterface(WaveformGenerator& wave, AlarmManager& alarm,
               DeviceState& dev, ConfigStorage& stor, ShdlcSensorInterface& sens);

  void setUsbModeCallback(std::function<void(bool)> cb);
  bool begin();
  void update();
};

#endif // WEB_INTERFACE_H
