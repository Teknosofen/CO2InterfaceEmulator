#ifndef COMMAND_LINE_INTERFACE_H
#define COMMAND_LINE_INTERFACE_H

#include <Arduino.h>
#include "WaveformGenerator.h"
#include "AlarmManager.h"
#include "DeviceState.h"
#include "ConfigStorage.h"

class CommandLineInterface {
private:
  WaveformGenerator& waveform;
  AlarmManager& alarms;
  DeviceState& device;
  ConfigStorage& storage;
  Stream& serial;
  String lineBuffer;
  
  void printHelp();
  void printStatus();
  void processLine(String line);
  
public:
  CommandLineInterface(WaveformGenerator& wave, AlarmManager& alarm, 
                       DeviceState& dev, ConfigStorage& stor, Stream& ser);
  
  void update();
  void printWelcome();
};

#endif // COMMAND_LINE_INTERFACE_H
