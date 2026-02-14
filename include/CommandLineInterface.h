#ifndef COMMAND_LINE_INTERFACE_H
#define COMMAND_LINE_INTERFACE_H

#include <Arduino.h>
#include <functional>
#include "WaveformGenerator.h"
#include "DeviceState.h"
#include "ConfigStorage.h"

class CommandLineInterface {
private:
  WaveformGenerator& waveform;
  DeviceState& device;
  ConfigStorage& storage;
  Stream& serial;
  String lineBuffer;
  std::function<void(bool)> usbModeCallback;

  void printHelp();
  void printStatus();
  void processLine(String line);

public:
  CommandLineInterface(WaveformGenerator& wave,
                       DeviceState& dev, ConfigStorage& stor, Stream& ser);

  void setUsbModeCallback(std::function<void(bool)> cb);
  void update();
  void printWelcome();
};

#endif // COMMAND_LINE_INTERFACE_H
